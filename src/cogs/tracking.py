"""Discord listeners for activity tracking + guild lifecycle.

Discord のイベントを受けて ``features/tracking`` ``features/guilds``
``features/meta`` のサービス関数に委譲する。スラッシュコマンドは持たない。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import discord
from discord.ext import commands, tasks
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    DEFAULT_EMBED_COLOR,
    MAX_VOICE_SESSION_SECONDS,
    MIN_MESSAGE_LENGTH,
)
from src.database.engine import async_session
from src.database.models import LevelRoleAward
from src.features.guilds import service as guilds_service
from src.features.leveling.service import (
    get_user_lifetime_levels,
    get_user_lifetime_levels_static_and_live,
)
from src.features.meta import service as meta_service
from src.features.reactions import service as reactions_service
from src.features.tracking import service as tracking_service
from src.level_roles import (
    DEFAULT_LEVEL_ROLE_GRANT_MODE,
    LEVEL_ROLE_GRANT_MODE_REPLACE,
    LEVEL_ROLE_GRANT_MODE_STACK,
)
from src.utils import today_local

logger = logging.getLogger(__name__)


@runtime_checkable
class _Sendable(Protocol):
    async def send(self, *args: object, **kwargs: object) -> object: ...


class TrackingCog(commands.Cog):
    """メッセージ・ボイスのアクティビティを ``daily_stats`` に集計する。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # on_ready は再接続でも発火するため、初回のみ初期化する
        self._initialized = False
        # 高頻度イベントで毎回 full 集計しないための簡易スロットリング
        self._level_role_check_cache: dict[tuple[str, str], float] = {}
        # 同一レベルの重複通知を抑制する短期キャッシュ
        self._level_up_notify_cache: dict[tuple[str, str, int], float] = {}
        # VC 接続中の live voice で通知済み/処理済みの最大レベル
        self._live_voice_level_cache: dict[tuple[str, str], int] = {}

    async def cog_unload(self) -> None:
        if self._level_role_sync_loop.is_running():
            self._level_role_sync_loop.cancel()
        if self._live_voice_level_loop.is_running():
            self._live_voice_level_loop.cancel()

    def _prune_level_up_notify_cache(self, now: float) -> None:
        """古い level-up 通知キャッシュを掃除して無制限増加を防ぐ。"""
        # 通知抑止窓は 30 秒だが、余裕を見て 5 分より古いものを削除。
        expire_before = now - 300.0
        stale_keys = [
            key for key, ts in self._level_up_notify_cache.items() if ts < expire_before
        ]
        for key in stale_keys:
            self._level_up_notify_cache.pop(key, None)

    async def _resolve_message_author_is_bot(
        self,
        session: AsyncSession,
        *,
        channel_id: int,
        message_id: int,
        author_id: str,
    ) -> bool:
        """メッセージ作者の bot 判定を meta 優先で解決する。

        古いメッセージの作者が ``user_meta`` に未登録の場合だけ、対象メッセージを
        取得して作者情報を補完する。取得できない場合は従来通り人扱いに倒す。
        """
        author_bot_flag = await meta_service.get_user_bot_flag(session, author_id)
        if author_bot_flag is not None:
            return author_bot_flag

        channel = None
        get_channel = getattr(self.bot, "get_channel", None)
        if get_channel is not None:
            channel = get_channel(channel_id)
        if channel is None:
            fetch_channel = getattr(self.bot, "fetch_channel", None)
            if fetch_channel is not None:
                try:
                    channel = await fetch_channel(channel_id)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    logger.info(
                        "Could not fetch channel for reaction author bot check "
                        "channel=%s message=%s author=%s",
                        channel_id,
                        message_id,
                        author_id,
                    )
                    return False

        fetch_message = getattr(channel, "fetch_message", None)
        if fetch_message is None:
            return False

        try:
            message = await fetch_message(message_id)
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            logger.info(
                "Could not fetch message for reaction author bot check "
                "channel=%s message=%s author=%s",
                channel_id,
                message_id,
                author_id,
            )
            return False

        author = getattr(message, "author", None)
        if author is None or str(getattr(author, "id", "")) != author_id:
            return False

        display_name = str(
            getattr(author, "display_name", None) or getattr(author, "name", author_id)
        )
        display_avatar = getattr(author, "display_avatar", None)
        avatar_url = str(display_avatar.url) if display_avatar is not None else None
        is_bot = bool(getattr(author, "bot", False))
        await meta_service.upsert_user_meta(
            session,
            user_id=author_id,
            display_name=display_name,
            avatar_url=avatar_url,
            is_bot=is_bot,
        )
        return is_bot

    async def _get_total_level(
        self, guild_id: str, user_id: str, *, include_live_voice: bool = True
    ) -> int:
        async with async_session() as session:
            levels = await get_user_lifetime_levels(
                session,
                guild_id,
                user_id,
                include_live_voice=include_live_voice,
            )
        if levels is None:
            return 0
        return levels.total.level

    async def _notify_level_up(
        self,
        member: discord.Member,
        *,
        new_level: int,
        place: object | None,
    ) -> None:
        if place is None:
            logger.info(
                "Skip level-up notify (no place) user=%s guild=%s level=%d",
                member.id,
                member.guild.id,
                new_level,
            )
            return
        sender = place if isinstance(place, _Sendable) else None
        if sender is None:
            logger.info(
                (
                    "Skip level-up notify (place has no send) "
                    "user=%s guild=%s level=%d place=%s"
                ),
                member.id,
                member.guild.id,
                new_level,
                type(place).__name__,
            )
            return
        raw_display_name = getattr(member, "display_name", None) or getattr(
            member, "name", str(member.id)
        )
        display_name = discord.utils.escape_mentions(
            discord.utils.escape_markdown(str(raw_display_name))
        )
        msg = (
            f"レベルアップ！ **{display_name}** さんが "
            f"**Lv {new_level}** になりました。"
        )
        delete_after_seconds = 30
        delete_at = int(datetime.now(UTC).timestamp()) + delete_after_seconds
        embed = discord.Embed(
            title="レベルアップ",
            description=msg,
            color=DEFAULT_EMBED_COLOR,
            timestamp=datetime.now(UTC),
        )
        embed.set_footer(text=f"{delete_after_seconds}秒後に削除")
        embed.add_field(
            name="このメッセージの削除まで",
            value=f"<t:{delete_at}:R>",
            inline=False,
        )
        try:
            await sender.send(
                embed=embed,
                delete_after=delete_after_seconds,
            )
        except (discord.Forbidden, discord.HTTPException, TypeError):
            logger.info(
                "Failed to notify level-up user=%s guild=%s level=%d",
                member.id,
                member.guild.id,
                new_level,
            )

    def _should_notify_level_up(
        self, *, guild_id: str, user_id: str, level: int
    ) -> bool:
        key = (guild_id, user_id, level)
        now = time.monotonic()
        self._prune_level_up_notify_cache(now)
        last = self._level_up_notify_cache.get(key, 0.0)
        if now - last < 30.0:
            return False
        self._level_up_notify_cache[key] = now
        return True

    async def _process_level_progress(
        self,
        *,
        member: discord.Member,
        prev_level: int,
        place: object | None = None,
        new_level: int | None = None,
    ) -> None:
        guild_id = str(member.guild.id)
        user_id = str(member.id)
        if new_level is not None:
            resolved_level = new_level
        else:
            resolved_level = await self._get_total_level(guild_id, user_id)
        if resolved_level > prev_level:
            member_voice = getattr(member, "voice", None)
            if getattr(member_voice, "channel", None) is not None:
                cache_key = (guild_id, user_id)
                self._live_voice_level_cache[cache_key] = max(
                    resolved_level,
                    self._live_voice_level_cache.get(cache_key, resolved_level),
                )
            if self._should_notify_level_up(
                guild_id=guild_id, user_id=user_id, level=resolved_level
            ):
                await self._notify_level_up(
                    member, new_level=resolved_level, place=place
                )
            await self._apply_level_roles_if_needed(
                member, force=True, current_level=resolved_level
            )
            return
        await self._apply_level_roles_if_needed(member, current_level=resolved_level)

    def _get_place_from_channel_id(
        self, guild: discord.Guild, channel_id: int
    ) -> object | None:
        resolver = getattr(guild, "get_channel_or_thread", None)
        if callable(resolver):
            resolved = resolver(channel_id)
            return resolved if resolved is not None else None
        return guild.get_channel(channel_id)

    async def _grant_level_roles_from_rules(
        self,
        *,
        member: discord.Member,
        level: int,
        rules: list[LevelRoleAward],
    ) -> bool:
        # replace: slot ごとに「到達済みの最大 level のロール」1つだけを保持する。
        # stack: 到達済みのロールを削除せず、冪等に追加だけする。
        slot_best: dict[int, LevelRoleAward] = {}
        stack_rules: list[LevelRoleAward] = []
        for rule in rules:
            if rule.level > level:
                continue
            grant_mode = rule.grant_mode or DEFAULT_LEVEL_ROLE_GRANT_MODE
            if grant_mode == LEVEL_ROLE_GRANT_MODE_STACK:
                stack_rules.append(rule)
                continue
            best = slot_best.get(rule.slot)
            if best is None or rule.level > best.level:
                slot_best[rule.slot] = rule

        selected_role_ids = {r.role_id for r in slot_best.values()} | {
            r.role_id for r in stack_rules
        }
        managed_replace_role_ids = {
            r.role_id
            for r in rules
            if (r.grant_mode or DEFAULT_LEVEL_ROLE_GRANT_MODE)
            == LEVEL_ROLE_GRANT_MODE_REPLACE
        }

        to_add: list[discord.Role] = []
        to_remove: list[discord.Role] = []
        for role_id in selected_role_ids:
            role = member.guild.get_role(int(role_id))
            if role is None or role in member.roles:
                continue
            to_add.append(role)

        for role in member.roles:
            role_id = str(role.id)
            if role_id in managed_replace_role_ids and role_id not in selected_role_ids:
                to_remove.append(role)

        if not to_add and not to_remove:
            return False
        try:
            if to_add:
                await member.add_roles(*to_add, reason="Level milestone reached")
            if to_remove:
                await member.remove_roles(
                    *to_remove, reason="Replaced by higher level role in slot"
                )
            return True
        except discord.Forbidden:
            logger.warning(
                "Missing permissions to grant level roles guild=%s user=%s",
                member.guild.id,
                member.id,
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to grant level roles guild=%s user=%s",
                member.guild.id,
                member.id,
            )
        return False

    async def _sync_level_roles_for_guild_members(self, guild: discord.Guild) -> None:
        guild_id = str(guild.id)
        success = 0
        failed = 0
        scan_incomplete = False
        async with async_session() as session:
            settings = await guilds_service.get_guild_settings(session, guild_id)
            if settings is None:
                await guilds_service.mark_level_role_sync_processed(session, guild_id)
                return
            count_bots = settings.count_bots
            rules = await guilds_service.list_level_role_awards_for_grant(
                session, guild_id
            )
            if not rules:
                await guilds_service.mark_level_role_sync_processed(session, guild_id)
                return

            members: list[discord.Member] = []
            try:
                if guild.chunked:
                    members = list(guild.members)
                else:
                    async for member in guild.fetch_members(limit=None):
                        members.append(member)
            except discord.Forbidden:
                scan_incomplete = True
                members = list(guild.members)
                logger.warning(
                    "Cannot fetch all members for level-role sync guild=%s; "
                    "using cache only",
                    guild.id,
                )
            except discord.HTTPException:
                scan_incomplete = True
                members = list(guild.members)
                logger.exception(
                    "Failed to fetch all members for level-role sync guild=%s; "
                    "using cache only",
                    guild.id,
                )

            for member in members:
                if member.bot and not count_bots:
                    continue
                try:
                    levels = await get_user_lifetime_levels(
                        session, guild_id, str(member.id)
                    )
                    level = levels.total.level if levels is not None else 0
                    granted = await self._grant_level_roles_from_rules(
                        member=member,
                        level=level,
                        rules=rules,
                    )
                    if granted:
                        success += 1
                except Exception:
                    failed += 1
                    logger.exception(
                        "Batch level-role sync failed for member guild=%s user=%s",
                        guild.id,
                        member.id,
                    )
            if scan_incomplete or failed > 0:
                logger.warning(
                    "Batch level-role sync incomplete guild=%s success=%d "
                    "failed=%d scan_incomplete=%s",
                    guild.id,
                    success,
                    failed,
                    scan_incomplete,
                )
                return

            await guilds_service.mark_level_role_sync_processed(session, guild_id)
        logger.info(
            "Batch level-role sync done guild=%s success=%d failed=%d",
            guild.id,
            success,
            failed,
        )

    @tasks.loop(seconds=20.0)
    async def _level_role_sync_loop(self) -> None:
        async with async_session() as session:
            guild_ids = await guilds_service.list_guild_ids_requiring_level_role_sync(
                session
            )
        for guild_id in guild_ids:
            try:
                guild = self.bot.get_guild(int(guild_id))
                if guild is None:
                    async with async_session() as session:
                        await guilds_service.mark_level_role_sync_processed(
                            session, guild_id
                        )
                    logger.warning(
                        "Skip batch level-role sync because guild not in cache "
                        "guild=%s",
                        guild_id,
                    )
                    continue
                await self._sync_level_roles_for_guild_members(guild)
            except Exception:
                logger.exception(
                    "Batch level-role sync loop failed for guild=%s",
                    guild_id,
                )

    @_level_role_sync_loop.before_loop
    async def _before_level_role_sync_loop(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=60.0)
    async def _live_voice_level_loop(self) -> None:
        async with async_session() as session:
            sessions = await tracking_service.list_active_voice_sessions(session)
            for voice in sessions:
                try:
                    guild = self.bot.get_guild(int(voice.guild_id))
                    if guild is None:
                        continue
                    member = guild.get_member(int(voice.user_id))
                    if member is None:
                        continue
                    gsettings = await guilds_service.get_guild_settings(
                        session, voice.guild_id
                    )
                    if member.bot and not (gsettings and gsettings.count_bots):
                        continue
                    current_voice = getattr(member, "voice", None)
                    current_channel = getattr(current_voice, "channel", None)
                    if (
                        current_channel is None
                        or str(current_channel.id) != voice.channel_id
                    ):
                        self._live_voice_level_cache.pop(
                            (voice.guild_id, voice.user_id), None
                        )
                        continue

                    if gsettings and not gsettings.tracking_enabled:
                        continue
                    if await guilds_service.is_channel_excluded(
                        session, voice.guild_id, voice.channel_id
                    ):
                        continue

                    (
                        levels_without_live,
                        levels_with_live,
                    ) = await get_user_lifetime_levels_static_and_live(
                        session,
                        voice.guild_id,
                        voice.user_id,
                    )
                    prev_level = (
                        levels_without_live.total.level
                        if levels_without_live is not None
                        else 0
                    )
                    current_level = (
                        levels_with_live.total.level
                        if levels_with_live is not None
                        else 0
                    )

                    cache_key = (voice.guild_id, voice.user_id)
                    prev_level = max(
                        prev_level,
                        self._live_voice_level_cache.get(cache_key, prev_level),
                    )
                    if current_level > prev_level:
                        place = self._get_place_from_channel_id(
                            guild, int(voice.channel_id)
                        )
                        await self._process_level_progress(
                            member=member,
                            prev_level=prev_level,
                            place=place,
                            new_level=current_level,
                        )
                        self._live_voice_level_cache[cache_key] = current_level
                except Exception:
                    logger.exception(
                        "Live voice level check failed guild=%s user=%s",
                        voice.guild_id,
                        voice.user_id,
                    )

    @_live_voice_level_loop.before_loop
    async def _before_live_voice_level_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Bot 接続完了時に同期処理を 1 度だけ実行。

        cog_load で wait_until_ready() を呼ぶと setup_hook 内で deadlock するため
        ここに置いている。失敗時はフラグを下ろし、次回 on_ready で再試行する。
        """
        if self._initialized:
            if not self._level_role_sync_loop.is_running():
                self._level_role_sync_loop.start()
            if not self._live_voice_level_loop.is_running():
                self._live_voice_level_loop.start()
            return
        self._initialized = True
        try:
            await self._sync_guilds()
            await self._restore_voice_sessions()
            await self._backfill_member_meta()
            await self._backfill_channel_meta()
            await self._backfill_role_meta()
            if not self._level_role_sync_loop.is_running():
                self._level_role_sync_loop.start()
            if not self._live_voice_level_loop.is_running():
                self._live_voice_level_loop.start()
        except Exception:
            logger.exception(
                "Failed to initialize TrackingCog; will retry on next ready"
            )
            self._initialized = False

    async def _sync_guilds(self) -> None:
        async with async_session() as session:
            for guild in self.bot.guilds:
                await guilds_service.upsert_guild(
                    session,
                    guild_id=str(guild.id),
                    name=guild.name,
                    icon_url=str(guild.icon.url) if guild.icon else None,
                    member_count=guild.member_count or 0,
                )

    async def _restore_voice_sessions(self) -> None:
        """既存セッションを flush してから現在 VC に居るメンバーで作り直す。

        Bot ダウン中に VC を抜けたユーザーのレコードがリークしないよう
        最終的には「全クリア → 現在状態を再構築」するが、purge の前に
        既存セッションの elapsed を daily_stats に書き出すことで、
        再起動を挟んだユーザーの VC 滞在時間が失われないようにする。
        member / channel の meta も同時に upsert しておくことで、
        「ID 数字だけ表示」になる問題を防ぐ。
        """
        async with async_session() as session:
            # 1. 進行中セッションの elapsed を daily_stats へ書き戻す
            flushed = await tracking_service.flush_active_voice_sessions_to_daily_stats(
                session
            )
            if flushed > 0:
                logger.info(
                    "Flushed %d in-progress voice sessions to daily_stats", flushed
                )
            # 2. 全 session を一旦クリア
            purged = await tracking_service.purge_all_voice_sessions(session)
            if purged > 0:
                logger.info("Purged %d stale voice sessions", purged)

            for guild in self.bot.guilds:
                for vc in guild.voice_channels:
                    for member in vc.members:
                        if member.bot:
                            continue
                        await tracking_service.start_voice_session(
                            session,
                            guild_id=str(guild.id),
                            user_id=str(member.id),
                            channel_id=str(vc.id),
                            self_muted=member.voice.self_mute
                            if member.voice
                            else False,
                            self_deafened=(
                                member.voice.self_deaf if member.voice else False
                            ),
                        )
                        await meta_service.upsert_user_meta(
                            session,
                            user_id=str(member.id),
                            display_name=member.display_name,
                            avatar_url=str(member.display_avatar.url),
                            is_bot=member.bot,
                        )
                        await meta_service.upsert_channel_meta(
                            session,
                            guild_id=str(guild.id),
                            channel_id=str(vc.id),
                            name=vc.name,
                            channel_type=type(vc).__name__,
                        )

    async def _backfill_member_meta(self) -> None:
        """全 guild の全 member の meta を bulk upsert する (起動時 1 回)。

        既存の daily_stats / voice_sessions に対応する user_meta が無い
        ユーザーを救済する目的。bulk INSERT で chunk 送信なので 10k メンバー
        程度でも数秒で完了する。
        """
        total = 0
        for guild in self.bot.guilds:
            payload = [
                {
                    "user_id": str(member.id),
                    "display_name": member.display_name,
                    "avatar_url": str(member.display_avatar.url),
                    "is_bot": member.bot,
                }
                for member in guild.members
            ]
            if not payload:
                continue
            async with async_session() as session:
                count = await meta_service.bulk_upsert_user_meta(session, payload)
            total += count
            logger.info(
                "Backfilled %d member meta records for guild %s",
                count,
                guild.id,
            )
        if total:
            logger.info("Member meta backfill total: %d", total)

    async def _backfill_channel_meta(self) -> None:
        """全 guild の全テキスト/ボイスチャンネルの meta を bulk upsert する。"""
        total = 0
        for guild in self.bot.guilds:
            payload: list[dict[str, object]] = []
            for ch in guild.channels:
                # カテゴリは集計対象外なので skip
                if isinstance(ch, discord.CategoryChannel):
                    continue
                payload.append(
                    {
                        "guild_id": str(guild.id),
                        "channel_id": str(ch.id),
                        "name": ch.name,
                        "channel_type": type(ch).__name__,
                    }
                )
            if not payload:
                continue
            async with async_session() as session:
                count = await meta_service.bulk_upsert_channel_meta(session, payload)
            total += count
            logger.info(
                "Backfilled %d channel meta records for guild %s",
                count,
                guild.id,
            )
        if total:
            logger.info("Channel meta backfill total: %d", total)

    async def _backfill_role_meta(self) -> None:
        total = 0
        for guild in self.bot.guilds:
            payload = [
                {
                    "guild_id": str(guild.id),
                    "role_id": str(role.id),
                    "name": role.name,
                    "position": role.position,
                    "is_managed": role.managed,
                }
                for role in guild.roles
                if role.name != "@everyone"
            ]
            if not payload:
                continue
            async with async_session() as session:
                count = await meta_service.bulk_upsert_role_meta(session, payload)
            total += count
        if total:
            logger.info("Role meta backfill total: %d", total)

    async def _apply_level_roles_if_needed(
        self,
        member: discord.Member,
        *,
        force: bool = False,
        current_level: int | None = None,
    ) -> None:
        guild_id = str(member.guild.id)
        user_id = str(member.id)
        cache_key = (guild_id, user_id)
        now = time.monotonic()
        last_checked = self._level_role_check_cache.get(cache_key, 0.0)
        if not force and now - last_checked < 15.0:
            return
        self._level_role_check_cache[cache_key] = now

        async with async_session() as session:
            rules = await guilds_service.list_level_role_awards_for_grant(
                session, guild_id
            )
            if not rules:
                return
            if current_level is None:
                # 活動履歴がまだ無いユーザーでも level=0 ルールの対象にする。
                levels = await get_user_lifetime_levels(session, guild_id, user_id)
                level = levels.total.level if levels is not None else 0
            else:
                level = current_level

        await self._grant_level_roles_from_rules(
            member=member, level=level, rules=rules
        )

    # ------------------------------------------------------------------
    # Guild lifecycle listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        async with async_session() as session:
            await guilds_service.upsert_guild(
                session,
                guild_id=str(guild.id),
                name=guild.name,
                icon_url=str(guild.icon.url) if guild.icon else None,
                member_count=guild.member_count or 0,
            )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        async with async_session() as session:
            await guilds_service.mark_guild_inactive(session, str(guild.id))

    @commands.Cog.listener()
    async def on_guild_update(
        self, _before: discord.Guild, after: discord.Guild
    ) -> None:
        async with async_session() as session:
            await guilds_service.upsert_guild(
                session,
                guild_id=str(after.id),
                name=after.name,
                icon_url=str(after.icon.url) if after.icon else None,
                member_count=after.member_count or 0,
            )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        async with async_session() as session:
            await meta_service.upsert_role_meta(
                session,
                guild_id=str(role.guild.id),
                role_id=str(role.id),
                name=role.name,
                position=role.position,
                is_managed=role.managed,
            )

    @commands.Cog.listener()
    async def on_guild_role_update(
        self, _before: discord.Role, after: discord.Role
    ) -> None:
        async with async_session() as session:
            await meta_service.upsert_role_meta(
                session,
                guild_id=str(after.guild.id),
                role_id=str(after.id),
                name=after.name,
                position=after.position,
                is_managed=after.managed,
            )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        async with async_session() as session:
            await meta_service.delete_role_meta(
                session, guild_id=str(role.guild.id), role_id=str(role.id)
            )

    # ------------------------------------------------------------------
    # Activity listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        # webhook メッセージは author.bot が True
        if message.author.bot:
            # bot を集計するかは guild_settings.count_bots 次第
            async with async_session() as session:
                gsettings = await guilds_service.get_guild_settings(
                    session, str(message.guild.id)
                )
                if not gsettings or not gsettings.count_bots:
                    return

        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return

        content_len = len(message.content or "")
        if content_len < MIN_MESSAGE_LENGTH and not message.attachments:
            return

        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)
        prev_level = 0

        async with async_session() as session:
            # 設定 / 除外チェック
            gsettings = await guilds_service.get_guild_settings(session, guild_id)
            if gsettings and not gsettings.tracking_enabled:
                return
            if await guilds_service.is_channel_excluded(session, guild_id, channel_id):
                return
            levels_before = await get_user_lifetime_levels(
                session, guild_id, str(message.author.id)
            )
            if levels_before is not None:
                prev_level = levels_before.total.level

            await tracking_service.increment_message_stat(
                session,
                guild_id=guild_id,
                user_id=str(message.author.id),
                channel_id=channel_id,
                stat_date=today_local(),
                char_count=content_len,
                attachment_count=len(message.attachments),
            )

            # メタ情報を更新 (名前変更や新規ユーザーの追跡)
            await meta_service.upsert_user_meta(
                session,
                user_id=str(message.author.id),
                display_name=message.author.display_name,
                avatar_url=str(message.author.display_avatar.url),
                is_bot=message.author.bot,
            )
            await meta_service.upsert_channel_meta(
                session,
                guild_id=guild_id,
                channel_id=channel_id,
                name=getattr(message.channel, "name", str(channel_id))
                or str(channel_id),
                channel_type=type(message.channel).__name__,
            )
        if isinstance(message.author, discord.Member):
            await self._process_level_progress(
                member=message.author,
                prev_level=prev_level,
                place=message.channel,
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """リアクション付与時に reactions_given / reactions_received を加算する。"""
        await self._apply_reaction_delta(payload, sign=+1)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """リアクション解除時に reactions_given / reactions_received を減算する。

        react/un-react ループでの ``reactions_given`` 水増しを防ぐ目的。
        ``payload.member`` は remove イベントでは届かないため bot 判定は
        ``user_meta`` キャッシュ経由で行う。
        """
        await self._apply_reaction_delta(payload, sign=-1)

    async def _apply_reaction_delta(
        self, payload: discord.RawReactionActionEvent, *, sign: int
    ) -> None:
        """on_raw_reaction_add / _remove 共通の判定・加減算ロジック。

        ``sign`` は +1 (add) または -1 (remove)。
        - reactor (リアクションした人)        → reactions_given
        - message author (メッセージ投稿者)   → reactions_received
        どちらの bot 判定も guild_settings.count_bots に従って除外する。
        セルフリアクション (reactor == author) は自己加点防止のため両方スキップ。

        個別リアクションは ``reactions`` 表に常時記録する (監査・逆引き用)。
        ただし daily_stats への加減算は **1 メッセージ × 1 リアクター = 1 回**
        になるよう ``reactions`` 表の状態で重複を弾く。
        """
        if payload.guild_id is None:
            return  # DM
        if payload.message_author_id is None:
            return  # 古いメッセージ等で取得できないケース
        if payload.user_id == payload.message_author_id:
            return  # セルフリアクションは自己加点になるためスキップ

        guild_id = str(payload.guild_id)
        channel_id = str(payload.channel_id)
        message_id = str(payload.message_id)
        reactor_id = str(payload.user_id)
        author_id = str(payload.message_author_id)
        emoji_str = str(payload.emoji)
        prev_reactor_level = 0
        prev_author_level = 0
        reactor_level_changed = False
        author_level_changed = False

        async with async_session() as session:
            gsettings = await guilds_service.get_guild_settings(session, guild_id)
            if gsettings and not gsettings.tracking_enabled:
                return
            count_bots = bool(gsettings and gsettings.count_bots)

            # reactor の bot 判定: add は payload.member.bot、
            # remove は user_meta から引く (remove イベントには member 情報なし)。
            if payload.member is not None:
                reactor_is_bot = payload.member.bot
            else:
                reactor_is_bot = await meta_service.is_user_bot(session, reactor_id)

            # BOT からのリアクションは count_bots=False で完全に除外
            if reactor_is_bot and not count_bots:
                return

            if await guilds_service.is_channel_excluded(session, guild_id, channel_id):
                return

            # author 側。未登録の古い bot メッセージは fetch で補完。
            author_is_bot = False
            if not count_bots:
                author_is_bot = await self._resolve_message_author_is_bot(
                    session,
                    channel_id=int(channel_id),
                    message_id=int(message_id),
                    author_id=author_id,
                )
                if sign > 0 and author_is_bot:
                    return

            # reactions 表に記録/削除し、daily_stats を動かすべきかの判定を受け取る
            if sign > 0:
                should_update_daily = await reactions_service.record_reaction_add(
                    session,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    message_id=message_id,
                    reactor_id=reactor_id,
                    message_author_id=author_id,
                    emoji=emoji_str,
                )
            else:
                should_update_daily = await reactions_service.record_reaction_remove(
                    session,
                    message_id=message_id,
                    reactor_id=reactor_id,
                    emoji=emoji_str,
                )

            if should_update_daily:
                stat_date = today_local()
                if sign > 0:
                    reactor_before = await get_user_lifetime_levels(
                        session, guild_id, reactor_id
                    )
                    if reactor_before is not None:
                        prev_reactor_level = reactor_before.total.level
                    reactor_level_changed = True

                # given: reactor 側
                if sign > 0:
                    await tracking_service.increment_reactions_given(
                        session,
                        guild_id=guild_id,
                        user_id=reactor_id,
                        channel_id=channel_id,
                        stat_date=stat_date,
                    )
                else:
                    await tracking_service.decrement_reactions_given(
                        session,
                        guild_id=guild_id,
                        user_id=reactor_id,
                        channel_id=channel_id,
                        stat_date=stat_date,
                    )

                if not (author_is_bot and not count_bots):
                    if sign > 0:
                        author_before = await get_user_lifetime_levels(
                            session, guild_id, author_id
                        )
                        if author_before is not None:
                            prev_author_level = author_before.total.level
                        author_level_changed = True
                    if sign > 0:
                        await tracking_service.increment_reactions_received(
                            session,
                            guild_id=guild_id,
                            user_id=author_id,
                            channel_id=channel_id,
                            stat_date=stat_date,
                        )
                    else:
                        await tracking_service.decrement_reactions_received(
                            session,
                            guild_id=guild_id,
                            user_id=author_id,
                            channel_id=channel_id,
                            stat_date=stat_date,
                        )
                elif sign < 0:
                    await tracking_service.decrement_reactions_received(
                        session,
                        guild_id=guild_id,
                        user_id=author_id,
                        channel_id=channel_id,
                        stat_date=stat_date,
                    )

            # reactor のメタ情報を更新 (add 時のみ; remove は payload.member 無し)
            if payload.member is not None:
                await meta_service.upsert_user_meta(
                    session,
                    user_id=reactor_id,
                    display_name=payload.member.display_name,
                    avatar_url=str(payload.member.display_avatar.url),
                    is_bot=payload.member.bot,
                )
        if sign > 0 and payload.member is not None:
            place = self._get_place_from_channel_id(
                payload.member.guild, int(channel_id)
            )
            if reactor_level_changed:
                await self._process_level_progress(
                    member=payload.member,
                    prev_level=prev_reactor_level,
                    place=place,
                )
            if author_level_changed:
                author_member = payload.member.guild.get_member(int(author_id))
                if author_member is not None:
                    await self._process_level_progress(
                        member=author_member,
                        prev_level=prev_author_level,
                        place=place,
                    )

    @commands.Cog.listener()
    async def on_raw_reaction_clear(
        self, payload: discord.RawReactionClearEvent
    ) -> None:
        """モデレーター操作で 1 メッセージの全リアクションが消された時の追従。

        ``reactions`` 表の対応行だけ削除し、``daily_stats`` には触らない
        (発生済みの engagement 履歴は保持する方針)。
        """
        if payload.guild_id is None:
            return
        async with async_session() as session:
            await reactions_service.delete_message_reactions(
                session, message_id=str(payload.message_id)
            )

    @commands.Cog.listener()
    async def on_raw_reaction_clear_emoji(
        self, payload: discord.RawReactionClearEmojiEvent
    ) -> None:
        """特定 emoji の全リアクション clear。同上で daily_stats 非更新。"""
        if payload.guild_id is None:
            return
        async with async_session() as session:
            await reactions_service.delete_emoji_reactions(
                session,
                message_id=str(payload.message_id),
                emoji=str(payload.emoji),
            )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            async with async_session() as session:
                gsettings = await guilds_service.get_guild_settings(
                    session, str(member.guild.id)
                )
                if not gsettings or not gsettings.count_bots:
                    return

        async with async_session() as session:
            gsettings = await guilds_service.get_guild_settings(
                session, str(member.guild.id)
            )
            if gsettings and not gsettings.tracking_enabled:
                return

            guild_id = str(member.guild.id)
            user_id = str(member.id)
            live_cache_key = (guild_id, user_id)
            prev_level = 0
            notify_channel_id: str | None = None
            voice_progressed = False

            # 退室 or 移動 → セッション終了 + 集計
            if before.channel is not None and (
                after.channel is None or before.channel.id != after.channel.id
            ):
                voice = await tracking_service.end_voice_session(
                    session, guild_id=guild_id, user_id=user_id
                )
                if voice:
                    elapsed = int((datetime.now(UTC) - voice.joined_at).total_seconds())
                    elapsed = max(0, min(elapsed, MAX_VOICE_SESSION_SECONDS))

                    excluded = await guilds_service.is_channel_excluded(
                        session, guild_id, voice.channel_id
                    )
                    if not excluded and elapsed > 0:
                        levels_before = await get_user_lifetime_levels(
                            session,
                            guild_id,
                            user_id,
                            include_live_voice=False,
                        )
                        if levels_before is not None:
                            prev_level = levels_before.total.level
                        prev_level = max(
                            prev_level,
                            self._live_voice_level_cache.get(
                                live_cache_key, prev_level
                            ),
                        )
                        await tracking_service.add_voice_seconds(
                            session,
                            guild_id=guild_id,
                            user_id=user_id,
                            channel_id=voice.channel_id,
                            stat_date=today_local(),
                            seconds=elapsed,
                        )
                        voice_progressed = True
                        notify_channel_id = voice.channel_id

                # 退室時もメタ更新 (display_name 変更追従 + ID-only 表示防止)
                await meta_service.upsert_user_meta(
                    session,
                    user_id=user_id,
                    display_name=member.display_name,
                    avatar_url=str(member.display_avatar.url),
                    is_bot=member.bot,
                )

            # 入室 or 移動 → 新セッション開始
            if after.channel is not None and (
                before.channel is None or before.channel.id != after.channel.id
            ):
                await tracking_service.start_voice_session(
                    session,
                    guild_id=guild_id,
                    user_id=user_id,
                    channel_id=str(after.channel.id),
                    self_muted=after.self_mute,
                    self_deafened=after.self_deaf,
                )
                # メタ更新
                await meta_service.upsert_user_meta(
                    session,
                    user_id=user_id,
                    display_name=member.display_name,
                    avatar_url=str(member.display_avatar.url),
                    is_bot=member.bot,
                )
                await meta_service.upsert_channel_meta(
                    session,
                    guild_id=guild_id,
                    channel_id=str(after.channel.id),
                    name=after.channel.name,
                    channel_type=type(after.channel).__name__,
                )
                # VC 移動で加算が発生した場合、通知先は「移動後」チャンネルを優先する。
                if voice_progressed:
                    notify_channel_id = str(after.channel.id)
        if voice_progressed:
            place = None
            if notify_channel_id is not None:
                place = self._get_place_from_channel_id(
                    member.guild, int(notify_channel_id)
                )
            await self._process_level_progress(
                member=member,
                prev_level=prev_level,
                place=place,
            )
        if before.channel is not None and (
            after.channel is None or before.channel.id != after.channel.id
        ):
            self._live_voice_level_cache.pop(live_cache_key, None)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackingCog(bot))
