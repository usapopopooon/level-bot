"""Lightweight heartbeat / health logging cog."""

from __future__ import annotations

import logging
import time

from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

_HEARTBEAT_MINUTES = 10


class HealthCog(commands.Cog):
    """10 分ごとに死活ログを stdout に出す簡易ヘルスチェック。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._start_time = time.monotonic()

    async def cog_load(self) -> None:
        self._heartbeat.start()

    async def cog_unload(self) -> None:
        self._heartbeat.cancel()

    @tasks.loop(minutes=_HEARTBEAT_MINUTES)
    async def _heartbeat(self) -> None:
        uptime_sec = int(time.monotonic() - self._start_time)
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, _ = divmod(remainder, 60)
        latency_ms = round(self.bot.latency * 1000)
        guild_count = len(self.bot.guilds)
        logger.info(
            "[Heartbeat] uptime=%dh%dm latency=%dms guilds=%d",
            hours,
            minutes,
            latency_ms,
            guild_count,
        )

    @_heartbeat.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HealthCog(bot))
