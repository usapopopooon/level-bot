"""Admin / utility slash commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.guilds import service as guilds_service


class AdminCog(commands.Cog):
    """Bot 管理者向けの軽量コマンド集。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Bot のレイテンシを表示")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! `{latency_ms}ms`", ephemeral=True
        )

    @app_commands.command(name="info", description="このサーバーの登録情報")
    async def info(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        async with async_session() as session:
            settings_row = await guilds_service.get_guild_settings(
                session, str(interaction.guild.id)
            )
            excluded = await guilds_service.list_excluded_channels(
                session, str(interaction.guild.id)
            )

        embed = discord.Embed(
            title="📋 サーバー登録情報",
            color=DEFAULT_EMBED_COLOR,
        )
        embed.add_field(
            name="集計",
            value="有効"
            if (settings_row and settings_row.tracking_enabled)
            else "無効",
            inline=True,
        )
        embed.add_field(
            name="Bot をカウント",
            value="はい" if (settings_row and settings_row.count_bots) else "いいえ",
            inline=True,
        )
        embed.add_field(
            name="ダッシュボード公開",
            value="公開" if (settings_row and settings_row.public) else "非公開",
            inline=True,
        )
        embed.add_field(
            name="除外チャンネル",
            value=f"{len(excluded)} 件" if excluded else "なし",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
