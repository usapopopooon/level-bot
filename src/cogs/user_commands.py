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

from src.config import settings
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
                f"累計 **{total.xp:,} XP**"
                + (f"  ·  次まで {remaining:,} XP" if remaining > 0 else "")
            ),
            color=DEFAULT_EMBED_COLOR,
            timestamp=datetime.now(UTC),
        )
        embed.set_thumbnail(url=str(target.display_avatar.url))

        view: discord.ui.View | None = None
        stats_base_url = settings.user_stats_site_base_url.strip().rstrip("/")
        stats_guild_id = settings.user_stats_site_guild_id.strip()
        guild_id = str(interaction.guild.id)
        if not stats_base_url or not stats_guild_id:
            logger.info(
                "Skip /level stats link: USER_STATS_SITE_GUILD_ID or "
                "USER_STATS_SITE_BASE_URL is unset guild=%s user=%s "
                "has_guild_id=%s has_base_url=%s",
                guild_id,
                target.id,
                bool(stats_guild_id),
                bool(stats_base_url),
            )
        elif guild_id != stats_guild_id:
            logger.info(
                "Skip /level stats link: guild mismatch guild=%s configured_guild=%s "
                "user=%s",
                guild_id,
                stats_guild_id,
                target.id,
            )
        else:
            stats_url = f"{stats_base_url}/{target.id}?days=30"
            logger.info(
                "Add /level stats link guild=%s user=%s url=%s",
                guild_id,
                target.id,
                stats_url,
            )
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="ユーザー統計を開く",
                    url=stats_url,
                )
            )

        if view is None:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UserCommandsCog(bot))
