"""``/stats *`` slash command group.

Discord の slash group ``/stats`` は単一 cog が group 全体を所有するのが
シンプルなため、複数 feature にまたがる表示コマンドを 1 ファイルにまとめている。
コマンドハンドラ自体は features/* のサービスに委譲するだけ。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from src.constants import (
    DEFAULT_EMBED_COLOR,
    DEFAULT_LEADERBOARD_LIMIT,
    MAX_LEADERBOARD_LIMIT,
)
from src.database.engine import async_session
from src.features.guilds import service as guilds_service
from src.features.leveling.service import (
    LevelBreakdown,
    get_user_lifetime_levels,
)
from src.features.ranking import service as ranking_service
from src.features.ranking.service import (
    ChannelLeaderboardEntry,
    LeaderboardEntry,
)
from src.features.stats import service as stats_service
from src.features.user_profile import service as profile_service
from src.utils import format_seconds


def _is_recordable_text_channel(channel: discord.abc.GuildChannel) -> bool:
    """テキスト系チャンネルなら True (DM やカテゴリは除外)。"""
    return isinstance(
        channel, discord.TextChannel | discord.Thread | discord.VoiceChannel
    )


def _format_leaderboard_value_user(entry: LeaderboardEntry, metric: str) -> str:
    """ユーザーランキング行の右側に出す値を metric ごとに整形する。"""
    if metric == "voice":
        return format_seconds(entry.voice_seconds)
    if metric == "reactions_received":
        return f"{entry.reactions_received:,}"
    if metric == "reactions_given":
        return f"{entry.reactions_given:,}"
    return f"{entry.message_count:,}"


def _format_leaderboard_value_channel(
    entry: ChannelLeaderboardEntry, metric: str
) -> str:
    """チャンネルランキング行の右側に出す値を metric ごとに整形する。"""
    if metric == "voice":
        return format_seconds(entry.voice_seconds)
    if metric == "reactions_received":
        return f"{entry.reactions_received:,}"
    if metric == "reactions_given":
        return f"{entry.reactions_given:,}"
    return f"{entry.message_count:,}"


class SlashStatsCog(commands.Cog):
    """``/stats *`` を提供する。"""

    stats_group = app_commands.Group(
        name="stats",
        description="サーバー統計の表示・設定",
        # 一旦すべての /stats * を管理者専用に制限する。サブコマンド/サブグループに
        # 継承されるので個別の default_permissions は不要。
        default_permissions=discord.Permissions(administrator=True),
    )
    stats_admin = app_commands.Group(
        name="exclude",
        description="集計対象チャンネルの管理",
        parent=stats_group,
    )
    stats_user_admin = app_commands.Group(
        name="exclude-user",
        description="表示から除外するユーザーの管理 (集計データは保持)",
        parent=stats_group,
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # /stats server
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
            summary = await stats_service.get_guild_summary(
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
        embed.add_field(
            name="リアクション (受)",
            value=f"{summary.total_reactions_received:,}",
            inline=True,
        )
        embed.add_field(
            name="リアクション (送)",
            value=f"{summary.total_reactions_given:,}",
            inline=True,
        )
        embed.set_footer(text=f"ダッシュボード → /g/{summary.guild_id}")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /stats profile
    # ------------------------------------------------------------------

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
            profile = await profile_service.get_user_profile(
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
        embed.add_field(
            name=f"リアクション受 ({days}日)",
            value=(
                f"{profile.total_reactions_received:,}\n"
                f"rank: #{profile.rank_reactions_received or '—'}"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"リアクション送 ({days}日)",
            value=(
                f"{profile.total_reactions_given:,}\n"
                f"rank: #{profile.rank_reactions_given or '—'}"
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

    # ------------------------------------------------------------------
    # /stats level
    # ------------------------------------------------------------------

    @stats_group.command(name="level", description="ユーザーのレベル (総合 + 項目別)")
    @app_commands.describe(user="対象ユーザー (省略時は自分)")
    async def stats_level(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        target = user or cast(discord.Member, interaction.user)
        await interaction.response.defer()

        async with async_session() as session:
            levels = await get_user_lifetime_levels(
                session, str(interaction.guild.id), str(target.id)
            )
            if levels is None:
                await interaction.followup.send("まだデータがありません。")
                return

        embed = discord.Embed(
            title=f"⭐ {target.display_name} のレベル",
            description=(
                f"**Lv {levels.total.level}** (総合)\n"
                f"`{levels.total.xp:,} XP`"
                + (
                    f"  /  次まで {levels.total.next_floor - levels.total.xp:,}"
                    if levels.total.next_floor > levels.total.xp
                    else ""
                )
            ),
            color=DEFAULT_EMBED_COLOR,
            timestamp=datetime.now(UTC),
        )
        embed.set_thumbnail(url=str(target.display_avatar.url))

        def _line(b: LevelBreakdown) -> str:
            return f"Lv {b.level}\n`{b.xp:,} XP`"

        embed.add_field(name="🎙️ ボイス", value=_line(levels.voice), inline=True)
        embed.add_field(name="💬 テキスト", value=_line(levels.text), inline=True)
        embed.add_field(
            name="💖 リアクション (受)",
            value=_line(levels.reactions_received),
            inline=True,
        )
        embed.add_field(
            name="👍 リアクション (送)",
            value=_line(levels.reactions_given),
            inline=True,
        )
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /stats leaderboard
    # ------------------------------------------------------------------

    @stats_group.command(name="leaderboard", description="ユーザーのランキング")
    @app_commands.choices(
        metric=[
            app_commands.Choice(name="メッセージ数", value="messages"),
            app_commands.Choice(name="ボイス時間", value="voice"),
            app_commands.Choice(name="リアクション (受)", value="reactions_received"),
            app_commands.Choice(name="リアクション (送)", value="reactions_given"),
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
            entries = await ranking_service.get_user_leaderboard(
                session,
                str(interaction.guild.id),
                days=days,
                limit=limit,
                metric=m_value,
            )
        if not entries:
            await interaction.followup.send("まだデータがありません。")
            return

        title_map = {
            "voice": f"🏆 ボイス時間ランキング (直近 {days} 日)",
            "messages": f"🏆 メッセージランキング (直近 {days} 日)",
            "reactions_received": (f"🏆 リアクション (受) ランキング (直近 {days} 日)"),
            "reactions_given": (f"🏆 リアクション (送) ランキング (直近 {days} 日)"),
        }
        embed = discord.Embed(
            title=title_map.get(m_value, title_map["messages"]),
            color=DEFAULT_EMBED_COLOR,
        )
        lines: list[str] = []
        for i, e in enumerate(entries, start=1):
            value = _format_leaderboard_value_user(e, m_value)
            lines.append(f"`#{i:>2}` <@{e.user_id}> — **{value}**")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /stats channels
    # ------------------------------------------------------------------

    @stats_group.command(name="channels", description="チャンネル別ランキング")
    @app_commands.choices(
        metric=[
            app_commands.Choice(name="メッセージ数", value="messages"),
            app_commands.Choice(name="ボイス時間", value="voice"),
            app_commands.Choice(name="リアクション (受)", value="reactions_received"),
            app_commands.Choice(name="リアクション (送)", value="reactions_given"),
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
            entries = await ranking_service.get_channel_leaderboard(
                session,
                str(interaction.guild.id),
                days=days,
                limit=limit,
                metric=m_value,
            )
        if not entries:
            await interaction.followup.send("まだデータがありません。")
            return

        title_map = {
            "voice": f"📈 ボイス時間 (チャンネル別, 直近 {days} 日)",
            "messages": f"📈 メッセージ数 (チャンネル別, 直近 {days} 日)",
            "reactions_received": (
                f"📈 リアクション (受) (チャンネル別, 直近 {days} 日)"
            ),
            "reactions_given": (f"📈 リアクション (送) (チャンネル別, 直近 {days} 日)"),
        }
        embed = discord.Embed(
            title=title_map.get(m_value, title_map["messages"]),
            color=DEFAULT_EMBED_COLOR,
        )
        lines: list[str] = []
        for i, e in enumerate(entries, start=1):
            value = _format_leaderboard_value_channel(e, m_value)
            lines.append(f"`#{i:>2}` <#{e.channel_id}> — **{value}**")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /stats exclude *
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
            added = await guilds_service.add_excluded_channel(
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
            removed = await guilds_service.remove_excluded_channel(
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
            ids = await guilds_service.list_excluded_channels(
                session, str(interaction.guild.id)
            )
        if not ids:
            await interaction.response.send_message(
                "除外チャンネルはありません。", ephemeral=True
            )
            return
        body = "\n".join(f"- <#{cid}>" for cid in ids)
        await interaction.response.send_message(
            f"**除外中のチャンネル**\n{body}", ephemeral=True
        )

    # ------------------------------------------------------------------
    # /stats exclude-user *
    # ------------------------------------------------------------------

    @stats_user_admin.command(
        name="add",
        description="ユーザーを表示から除外する (集計データは保持)",
    )
    async def exclude_user_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        async with async_session() as session:
            added = await guilds_service.add_excluded_user(
                session, str(interaction.guild.id), str(user.id)
            )
        if added:
            await interaction.response.send_message(
                f"{user.mention} を表示から除外しました。", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} は既に除外されています。", ephemeral=True
            )

    @stats_user_admin.command(name="remove", description="ユーザーの除外を解除")
    async def exclude_user_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        async with async_session() as session:
            removed = await guilds_service.remove_excluded_user(
                session, str(interaction.guild.id), str(user.id)
            )
        if removed:
            await interaction.response.send_message(
                f"{user.mention} の除外を解除しました。", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} は除外されていません。", ephemeral=True
            )

    @stats_user_admin.command(name="list", description="除外ユーザー一覧")
    async def exclude_user_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        async with async_session() as session:
            ids = await guilds_service.list_excluded_users(
                session, str(interaction.guild.id)
            )
        if not ids:
            await interaction.response.send_message(
                "除外ユーザーはいません。", ephemeral=True
            )
            return
        body = "\n".join(f"- <@{uid}>" for uid in ids)
        await interaction.response.send_message(
            f"**除外中のユーザー**\n{body}", ephemeral=True
        )

    @stats_group.command(
        name="include-all",
        description="除外ユーザー/除外チャンネルを全解除して全員を表示対象に戻す",
    )
    async def include_all(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        guild_id = str(interaction.guild.id)
        async with async_session() as session:
            cleared_channels = await guilds_service.clear_excluded_channels(
                session, guild_id
            )
            cleared_users = await guilds_service.clear_excluded_users(session, guild_id)
        await interaction.response.send_message(
            (
                "全員を表示対象に戻しました。"
                f" (チャンネル除外解除: {cleared_channels} 件 / "
                f"ユーザー除外解除: {cleared_users} 件)"
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SlashStatsCog(bot))
