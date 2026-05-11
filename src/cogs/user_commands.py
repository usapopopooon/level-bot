"""一般ユーザー向け slash 命令 (admin 権限不要)。

``/stats *`` は admin 限定なので、ここに **本人** だけが叩く軽量コマンドを集める。
表示はすべて ephemeral にして他人には見えないようにする。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.leveling.service import LevelBreakdown, compute_user_levels
from src.features.user_profile import service as profile_service


class UserCommandsCog(commands.Cog):
    """ユーザー自身が叩く非管理者向けコマンド。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="level",
        description="自分のレベル・累計 XP・進捗を確認する (本人にしか見えません)",
    )
    async def my_level(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        target = cast(discord.Member, interaction.user)
        await interaction.response.defer(ephemeral=True)

        async with async_session() as session:
            stats = await profile_service.get_user_lifetime_stats(
                session, str(interaction.guild.id), str(target.id)
            )
        if stats is None:
            await interaction.followup.send(
                "まだ集計データがありません。",
                ephemeral=True,
            )
            return

        levels = compute_user_levels(stats)
        total = levels.total

        # 総合進捗バー (20 マス)。progress は 0.0-1.0
        bar_len = 20
        filled = int(bar_len * total.progress)
        bar = "█" * filled + "░" * (bar_len - filled)
        remaining = max(0, total.next_floor - total.xp)

        embed = discord.Embed(
            title=f"⭐ {target.display_name} のレベル",
            description=(
                f"**Lv {total.level}** (総合)\n"
                f"`{bar}` {int(total.progress * 100)}%\n"
                f"累計 **{total.xp:,} XP**"
                + (f"  ·  次まで {remaining:,} XP" if remaining > 0 else "")
            ),
            color=DEFAULT_EMBED_COLOR,
            timestamp=datetime.now(UTC),
        )
        embed.set_thumbnail(url=str(target.display_avatar.url))

        def _line(b: LevelBreakdown) -> str:
            pct = int(b.progress * 100)
            return f"Lv {b.level}\n`{b.xp:,} XP` ({pct}%)"

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
        embed.set_footer(
            text="XP 重み: VC 1/分 · TC 2/件 · リアクション 0.5/個 (期間減衰なし)"
        )

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UserCommandsCog(bot))
