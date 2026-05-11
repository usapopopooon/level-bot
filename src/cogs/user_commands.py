"""一般ユーザー向け slash 命令 (admin 権限不要)。

``/stats *`` は admin 限定なので、ここにユーザーが自由に叩ける軽量コマンドを置く。
レスポンスはパブリック (channel 全員に見える) で投げる。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.leveling.service import compute_user_levels
from src.features.user_profile import service as profile_service


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
            stats = await profile_service.get_user_lifetime_stats(
                session, str(interaction.guild.id), str(target.id)
            )
        if stats is None:
            await interaction.followup.send("まだ集計データがありません。")
            return

        total = compute_user_levels(stats).total

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

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UserCommandsCog(bot))
