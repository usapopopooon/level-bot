"""一般ユーザー向け slash 命令 (admin 権限不要)。

``/stats *`` は admin 限定なので、ここにユーザーが自由に叩ける軽量コマンドを置く。
レスポンスはパブリック (channel 全員に見える) で投げる。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from src.cogs.level_actions import build_level_action_view, build_user_stats_url
from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.leveling.service import get_user_lifetime_levels

logger = logging.getLogger(__name__)


class UserCommandsCog(commands.Cog):
    """ユーザー自身が叩く非管理者向けコマンド。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="level",
        description="自分のレベルと進捗を表示する",
    )
    async def my_level(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        target = cast(discord.Member, interaction.user)
        await interaction.response.defer()

        async with async_session() as session:
            levels = await get_user_lifetime_levels(
                session, str(interaction.guild.id), str(target.id)
            )
        if levels is None:
            await interaction.followup.send("まだ集計データがありません。")
            return

        total = levels.total

        # 進捗バー (20 マス)。progress は 0.0-1.0
        bar_len = 20
        filled = int(bar_len * total.progress)
        bar = "█" * filled + "░" * (bar_len - filled)
        remaining = max(0, total.next_floor - total.xp)

        embed = discord.Embed(
            title=f"⭐ {target.display_name} のレベル",
            description=(
                f"**Lv {total.level}**\n"
                f"`{bar}` {int(total.progress * 100)}%\n"
                f"現在 **{total.xp:,} XP**"
                + (f"  ·  次まで {remaining:,} XP" if remaining > 0 else "")
            ),
            color=DEFAULT_EMBED_COLOR,
            timestamp=datetime.now(UTC),
        )
        embed.set_thumbnail(url=str(target.display_avatar.url))

        guild_id = str(interaction.guild.id)
        stats_url = build_user_stats_url(guild_id, target.id)
        view = build_level_action_view(guild_id, target.id, stats_url)

        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UserCommandsCog(bot))
