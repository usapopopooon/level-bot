"""Discord listeners for activity tracking + guild lifecycle.

Discord のイベントを受けて ``features/tracking`` ``features/guilds``
``features/meta`` のサービス関数に委譲する。スラッシュコマンドは持たない。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import discord
from discord.ext import commands

from src.constants import MAX_VOICE_SESSION_SECONDS, MIN_MESSAGE_LENGTH
from src.database.engine import async_session
from src.features.guilds import service as guilds_service
from src.features.meta import service as meta_service
from src.features.tracking import service as tracking_service
from src.utils import today_local

logger = logging.getLogger(__name__)


class TrackingCog(commands.Cog):
    """メッセージ・ボイスのアクティビティを ``daily_stats`` に集計する。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # on_ready は再接続でも発火するため、初回のみ初期化する
        self._initialized = False

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
            return
        self._initialized = True
        try:
            await self._sync_guilds()
            await self._restore_voice_sessions()
            await self._backfill_member_meta()
            await self._backfill_channel_meta()
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

        async with async_session() as session:
            # 設定 / 除外チェック
            gsettings = await guilds_service.get_guild_settings(session, guild_id)
            if gsettings and not gsettings.tracking_enabled:
                return
            if await guilds_service.is_channel_excluded(session, guild_id, channel_id):
                return

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
        ``payload.message_author_id`` は members intent が必要 (有効済み)。
        """
        if payload.guild_id is None:
            return  # DM
        if payload.message_author_id is None:
            return  # 古いメッセージ等で取得できないケース
        if payload.user_id == payload.message_author_id:
            return  # セルフリアクションは自己加点になるためスキップ

        guild_id = str(payload.guild_id)
        channel_id = str(payload.channel_id)
        reactor_id = str(payload.user_id)
        author_id = str(payload.message_author_id)

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

            stat_date = today_local()

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

            # received: author 側。author が bot かは user_meta キャッシュで判定
            # (キャッシュに無ければ False=人扱い)。count_bots=False の bot は除外。
            author_is_bot = await meta_service.is_user_bot(session, author_id)
            if not (author_is_bot and not count_bots):
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

            # reactor のメタ情報を更新 (add 時のみ; remove は payload.member 無し)
            if payload.member is not None:
                await meta_service.upsert_user_meta(
                    session,
                    user_id=reactor_id,
                    display_name=payload.member.display_name,
                    avatar_url=str(payload.member.display_avatar.url),
                    is_bot=payload.member.bot,
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
                        await tracking_service.add_voice_seconds(
                            session,
                            guild_id=guild_id,
                            user_id=user_id,
                            channel_id=voice.channel_id,
                            stat_date=today_local(),
                            seconds=elapsed,
                        )

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackingCog(bot))
