"""Stats tracking cog.

メッセージ・ボイスのアクティビティを集計する。

集計対象:
    - メッセージ送信 (count, char count, attachment count)
    - ボイス参加時間 (秒)

スラッシュコマンド:
    - /stats — サーバー全体の直近 30 日サマリ
    - /profile [user] — 自分または指定ユーザーのプロフィール
    - /leaderboard [type] — ユーザーのリーダーボード (messages | voice)
    - /channelstats — チャンネル別リーダーボード
    - /stats exclude / include / list — チャンネル除外管理
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from src.constants import (
    DEFAULT_EMBED_COLOR,
    DEFAULT_LEADERBOARD_LIMIT,
    MAX_LEADERBOARD_LIMIT,
    MAX_VOICE_SESSION_SECONDS,
    MIN_MESSAGE_LENGTH,
)
from src.database.engine import async_session
from src.services import stats_service as ss
from src.utils import format_seconds, today_local

logger = logging.getLogger(__name__)


def _is_recordable_text_channel(channel: discord.abc.GuildChannel) -> bool:
    """テキスト系チャンネルなら True (DM やカテゴリは除外)。"""
    return isinstance(
        channel, discord.TextChannel | discord.Thread | discord.VoiceChannel
    )


class StatsCog(commands.Cog):
    """メッセージとボイスの集計を担当する Cog。"""

    stats_group = app_commands.Group(
        name="stats",
        description="サーバー統計の表示・設定",
    )
    stats_admin = app_commands.Group(
        name="exclude",
        description="集計対象チャンネルの管理",
        parent=stats_group,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # on_ready は再接続でも発火するため、初回のみ初期化する
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Bot 接続完了時にギルドメタ同期 + ボイスセッション復元を1度だけ実行。

        cog_load で wait_until_ready() を呼ぶと setup_hook 内で deadlock するため、
        ここに置いている。失敗時はフラグを下ろし、次回 on_ready で再試行する。
        """
        if self._initialized:
            return
        self._initialized = True
        try:
            await self._sync_guilds()
            await self._restore_voice_sessions()
        except Exception:
            logger.exception("Failed to initialize StatsCog; will retry on next ready")
            self._initialized = False

    async def _sync_guilds(self) -> None:
        async with async_session() as session:
            for guild in self.bot.guilds:
                await ss.upsert_guild(
                    session,
                    guild_id=str(guild.id),
                    name=guild.name,
                    icon_url=str(guild.icon.url) if guild.icon else None,
                    member_count=guild.member_count or 0,
                )

    async def _restore_voice_sessions(self) -> None:
        """全ボイスセッションを破棄してから、現在 VC に居るメンバーで作り直す。

        Bot ダウン中に VC を抜けたユーザーのレコードがリークしないよう、
        単純に「全クリア → 現在状態を再構築」する。
        """
        async with async_session() as session:
            purged = await ss.purge_all_voice_sessions(session)
            if purged > 0:
                logger.info("Purged %d stale voice sessions", purged)

            for guild in self.bot.guilds:
                for vc in guild.voice_channels:
                    for member in vc.members:
                        if member.bot:
                            continue
                        await ss.start_voice_session(
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

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        async with async_session() as session:
            await ss.upsert_guild(
                session,
                guild_id=str(guild.id),
                name=guild.name,
                icon_url=str(guild.icon.url) if guild.icon else None,
                member_count=guild.member_count or 0,
            )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        async with async_session() as session:
            await ss.mark_guild_inactive(session, str(guild.id))

    @commands.Cog.listener()
    async def on_guild_update(
        self, _before: discord.Guild, after: discord.Guild
    ) -> None:
        async with async_session() as session:
            await ss.upsert_guild(
                session,
                guild_id=str(after.id),
                name=after.name,
                icon_url=str(after.icon.url) if after.icon else None,
                member_count=after.member_count or 0,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        # webhook メッセージは author.bot が True
        if message.author.bot:
            # bot を集計するかは guild_settings.count_bots 次第
            async with async_session() as session:
                gsettings = await ss.get_guild_settings(session, str(message.guild.id))
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
            gsettings = await ss.get_guild_settings(session, guild_id)
            if gsettings and not gsettings.tracking_enabled:
                return
            if await ss.is_channel_excluded(session, guild_id, channel_id):
                return

            await ss.increment_message_stat(
                session,
                guild_id=guild_id,
                user_id=str(message.author.id),
                channel_id=channel_id,
                stat_date=today_local(),
                char_count=content_len,
                attachment_count=len(message.attachments),
            )

            # メタ情報を更新 (名前変更や新規ユーザーの追跡)
            await ss.upsert_user_meta(
                session,
                user_id=str(message.author.id),
                display_name=message.author.display_name,
                avatar_url=str(message.author.display_avatar.url),
                is_bot=message.author.bot,
            )
            await ss.upsert_channel_meta(
                session,
                guild_id=guild_id,
                channel_id=channel_id,
                name=getattr(message.channel, "name", str(channel_id))
                or str(channel_id),
                channel_type=type(message.channel).__name__,
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
                gsettings = await ss.get_guild_settings(session, str(member.guild.id))
                if not gsettings or not gsettings.count_bots:
                    return

        async with async_session() as session:
            gsettings = await ss.get_guild_settings(session, str(member.guild.id))
            if gsettings and not gsettings.tracking_enabled:
                return

            guild_id = str(member.guild.id)
            user_id = str(member.id)

            # 退室 or 移動 → セッション終了 + 集計
            if before.channel is not None and (
                after.channel is None or before.channel.id != after.channel.id
            ):
                voice = await ss.end_voice_session(
                    session, guild_id=guild_id, user_id=user_id
                )
                if voice:
                    elapsed = int((datetime.now(UTC) - voice.joined_at).total_seconds())
                    elapsed = max(0, min(elapsed, MAX_VOICE_SESSION_SECONDS))

                    excluded = await ss.is_channel_excluded(
                        session, guild_id, voice.channel_id
                    )
                    if not excluded and elapsed > 0:
                        await ss.add_voice_seconds(
                            session,
                            guild_id=guild_id,
                            user_id=user_id,
                            channel_id=voice.channel_id,
                            stat_date=today_local(),
                            seconds=elapsed,
                        )

            # 入室 or 移動 → 新セッション開始
            if after.channel is not None and (
                before.channel is None or before.channel.id != after.channel.id
            ):
                await ss.start_voice_session(
                    session,
                    guild_id=guild_id,
                    user_id=user_id,
                    channel_id=str(after.channel.id),
                    self_muted=after.self_mute,
                    self_deafened=after.self_deaf,
                )
                # メタ更新
                await ss.upsert_user_meta(
                    session,
                    user_id=user_id,
                    display_name=member.display_name,
                    avatar_url=str(member.display_avatar.url),
                    is_bot=member.bot,
                )
                await ss.upsert_channel_meta(
                    session,
                    guild_id=guild_id,
                    channel_id=str(after.channel.id),
                    name=after.channel.name,
                    channel_type=type(after.channel).__name__,
                )

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @stats_group.command(name="server", description="このサーバーの直近 30 日の統計")
    @app_commands.describe(days="集計対象日数 (1-365)")
    async def stats_server(
        self, interaction: discord.Interaction, days: int = 30
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        days = max(1, min(days, 365))
        await interaction.response.defer()

        async with async_session() as session:
            summary = await ss.get_guild_summary(
                session, str(interaction.guild.id), days=days
            )
        if summary is None:
            await interaction.followup.send("まだデータがありません。")
            return

        embed = discord.Embed(
            title=f"📊 {summary.name} の統計 (直近 {days} 日)",
            color=DEFAULT_EMBED_COLOR,
            timestamp=datetime.now(UTC),
        )
        if summary.icon_url:
            embed.set_thumbnail(url=summary.icon_url)
        embed.add_field(
            name="メッセージ数", value=f"{summary.total_messages:,}", inline=True
        )
        embed.add_field(
            name="ボイス時間",
            value=format_seconds(summary.total_voice_seconds),
            inline=True,
        )
        embed.add_field(
            name="アクティブユーザー",
            value=f"{summary.active_users:,} 人",
            inline=True,
        )
        embed.set_footer(text=f"ダッシュボード → /g/{summary.guild_id}")
        await interaction.followup.send(embed=embed)

    @stats_group.command(name="profile", description="ユーザーの統計プロフィール")
    @app_commands.describe(user="対象ユーザー (省略時は自分)")
    async def stats_profile(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
        days: int = 30,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        days = max(1, min(days, 365))
        target = user or cast(discord.Member, interaction.user)
        await interaction.response.defer()

        async with async_session() as session:
            profile = await ss.get_user_profile(
                session,
                str(interaction.guild.id),
                str(target.id),
                days=days,
            )
        if profile is None:
            await interaction.followup.send("まだデータがありません。")
            return

        embed = discord.Embed(
            title=f"👤 {profile.display_name} のプロフィール",
            color=DEFAULT_EMBED_COLOR,
            timestamp=datetime.now(UTC),
        )
        if profile.avatar_url:
            embed.set_thumbnail(url=profile.avatar_url)
        embed.add_field(
            name=f"メッセージ ({days}日)",
            value=f"{profile.total_messages:,}\nrank: #{profile.rank_messages or '—'}",
            inline=True,
        )
        embed.add_field(
            name=f"ボイス ({days}日)",
            value=(
                f"{format_seconds(profile.total_voice_seconds)}\n"
                f"rank: #{profile.rank_voice or '—'}"
            ),
            inline=True,
        )
        if profile.top_channels:
            top_lines = [
                f"{i + 1}. <#{c.channel_id}> — {c.message_count:,} msg"
                for i, c in enumerate(profile.top_channels[:5])
            ]
            embed.add_field(
                name="主な発言チャンネル",
                value="\n".join(top_lines),
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @stats_group.command(name="leaderboard", description="ユーザーのランキング")
    @app_commands.choices(
        metric=[
            app_commands.Choice(name="メッセージ数", value="messages"),
            app_commands.Choice(name="ボイス時間", value="voice"),
        ]
    )
    async def stats_leaderboard(
        self,
        interaction: discord.Interaction,
        metric: app_commands.Choice[str] | None = None,
        days: int = 30,
        limit: int = DEFAULT_LEADERBOARD_LIMIT,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        days = max(1, min(days, 365))
        limit = max(1, min(limit, MAX_LEADERBOARD_LIMIT))
        m_value = metric.value if metric else "messages"
        await interaction.response.defer()

        async with async_session() as session:
            entries = await ss.get_user_leaderboard(
                session,
                str(interaction.guild.id),
                days=days,
                limit=limit,
                metric=m_value,
            )
        if not entries:
            await interaction.followup.send("まだデータがありません。")
            return

        title = (
            f"🏆 ボイス時間ランキング (直近 {days} 日)"
            if m_value == "voice"
            else f"🏆 メッセージランキング (直近 {days} 日)"
        )
        embed = discord.Embed(title=title, color=DEFAULT_EMBED_COLOR)
        lines: list[str] = []
        for i, e in enumerate(entries, start=1):
            value = (
                format_seconds(e.voice_seconds)
                if m_value == "voice"
                else f"{e.message_count:,}"
            )
            lines.append(f"`#{i:>2}` <@{e.user_id}> — **{value}**")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    @stats_group.command(name="channels", description="チャンネル別ランキング")
    @app_commands.choices(
        metric=[
            app_commands.Choice(name="メッセージ数", value="messages"),
            app_commands.Choice(name="ボイス時間", value="voice"),
        ]
    )
    async def stats_channels(
        self,
        interaction: discord.Interaction,
        metric: app_commands.Choice[str] | None = None,
        days: int = 30,
        limit: int = DEFAULT_LEADERBOARD_LIMIT,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        days = max(1, min(days, 365))
        limit = max(1, min(limit, MAX_LEADERBOARD_LIMIT))
        m_value = metric.value if metric else "messages"
        await interaction.response.defer()

        async with async_session() as session:
            entries = await ss.get_channel_leaderboard(
                session,
                str(interaction.guild.id),
                days=days,
                limit=limit,
                metric=m_value,
            )
        if not entries:
            await interaction.followup.send("まだデータがありません。")
            return

        title = (
            f"📈 ボイス時間 (チャンネル別, 直近 {days} 日)"
            if m_value == "voice"
            else f"📈 メッセージ数 (チャンネル別, 直近 {days} 日)"
        )
        embed = discord.Embed(title=title, color=DEFAULT_EMBED_COLOR)
        lines: list[str] = []
        for i, e in enumerate(entries, start=1):
            value = (
                format_seconds(e.voice_seconds)
                if m_value == "voice"
                else f"{e.message_count:,}"
            )
            lines.append(f"`#{i:>2}` <#{e.channel_id}> — **{value}**")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # Admin: exclude / include channels
    # ------------------------------------------------------------------

    @stats_admin.command(name="add", description="チャンネルを集計対象から除外")
    async def exclude_add(
        self,
        interaction: discord.Interaction,
        channel: discord.abc.GuildChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        if not _is_recordable_text_channel(channel):
            await interaction.response.send_message(
                "テキスト/ボイスチャンネルを指定してください。", ephemeral=True
            )
            return

        async with async_session() as session:
            added = await ss.add_excluded_channel(
                session, str(interaction.guild.id), str(channel.id)
            )
        if added:
            await interaction.response.send_message(
                f"{channel.mention} を集計対象から除外しました。", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{channel.mention} は既に除外されています。", ephemeral=True
            )

    @stats_admin.command(name="remove", description="除外を解除する")
    async def exclude_remove(
        self,
        interaction: discord.Interaction,
        channel: discord.abc.GuildChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return

        async with async_session() as session:
            removed = await ss.remove_excluded_channel(
                session, str(interaction.guild.id), str(channel.id)
            )
        if removed:
            await interaction.response.send_message(
                f"{channel.mention} の除外を解除しました。", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{channel.mention} は除外されていません。", ephemeral=True
            )

    @stats_admin.command(name="list", description="除外チャンネル一覧")
    async def exclude_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        async with async_session() as session:
            ids = await ss.list_excluded_channels(session, str(interaction.guild.id))
        if not ids:
            await interaction.response.send_message(
                "除外チャンネルはありません。", ephemeral=True
            )
            return
        body = "\n".join(f"- <#{cid}>" for cid in ids)
        await interaction.response.send_message(
            f"**除外中のチャンネル**\n{body}", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
