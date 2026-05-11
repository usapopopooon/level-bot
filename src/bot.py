"""Discord bot class definition."""

import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class LevelBot(commands.Bot):
    """サーバー統計トラッキング Bot 本体。

    必要な Privileged Intents:
        - members: ギルドメンバー情報取得
        - message_content: メッセージ長カウント (省略可。長さを集計しない場合は不要)

    Voice tracking には voice_states intent が必要 (デフォルトで有効)。
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True  # privileged
        intents.voice_states = True
        intents.message_content = True  # privileged: 文字数カウント用

        activity = discord.Game(name="サーバー統計を集計中…")

        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=activity,
        )

    async def setup_hook(self) -> None:
        extensions = [
            "src.cogs.tracking",
            "src.cogs.slash_stats",
            "src.cogs.user_commands",
            "src.cogs.health",
            "src.cogs.admin",
        ]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                logger.info("Loaded extension: %s", ext)
            except commands.ExtensionError:
                logger.exception("Failed to load extension: %s", ext)
                raise

        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except discord.HTTPException:
            logger.exception("Failed to sync slash commands")
            raise

    async def on_ready(self) -> None:
        if self.user:
            logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        logger.info("Connected to %d guilds", len(self.guilds))
