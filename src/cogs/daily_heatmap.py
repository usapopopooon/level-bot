"""Daily scheduled VC heatmap posts."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import cast

import discord
from discord.ext import commands, tasks

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.guilds import service as guilds_service
from src.features.guilds.service import DailyHeatmapTarget
from src.features.stats import service as stats_service
from src.features.stats.heatmap_image import render_hourly_activity_heatmap_table_png
from src.features.stats.heatmap_schedule import daily_heatmap_target_date
from src.features.stats.heatmap_text import format_hourly_activity_heatmap_title

logger = logging.getLogger(__name__)

DAILY_HEATMAP_CHECK_SECONDS = 60.0


class DailyHeatmapCog(commands.Cog):
    """Posts configured VC heatmaps once per day during the local midnight hour."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self._daily_heatmap_loop.start()

    async def cog_unload(self) -> None:
        self._daily_heatmap_loop.cancel()

    @tasks.loop(seconds=DAILY_HEATMAP_CHECK_SECONDS)
    async def _daily_heatmap_loop(self) -> None:
        now = datetime.now(UTC)
        async with async_session() as session:
            targets = await guilds_service.list_daily_heatmap_targets(session)

        for target in targets:
            target_date = daily_heatmap_target_date(
                now,
                post_time=target.post_time,
                timezone_name=target.timezone,
            )
            if target_date is None:
                continue
            if target.last_posted_on == target_date:
                continue
            try:
                should_mark = await self._post_daily_heatmap(target, target_date)
                if should_mark:
                    async with async_session() as session:
                        await guilds_service.mark_daily_heatmap_posted(
                            session, target.guild_id, target_date
                        )
            except Exception:
                logger.exception(
                    "Daily heatmap post failed guild=%s channel=%s date=%s",
                    target.guild_id,
                    target.channel_id,
                    target_date,
                )

    @_daily_heatmap_loop.before_loop
    async def _before_daily_heatmap_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _resolve_post_channel(
        self, guild: discord.Guild, channel_id: str
    ) -> discord.abc.Messageable | None:
        channel: object | None = guild.get_channel_or_thread(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logger.warning(
                    "Cannot resolve daily heatmap channel guild=%s channel=%s",
                    guild.id,
                    channel_id,
                )
                return None

        send = getattr(channel, "send", None)
        if not callable(send):
            logger.warning(
                "Daily heatmap channel is not messageable guild=%s channel=%s",
                guild.id,
                channel_id,
            )
            return None
        return cast(discord.abc.Messageable, channel)

    async def _post_daily_heatmap(
        self, target: DailyHeatmapTarget, target_date: date
    ) -> bool:
        guild = self.bot.get_guild(int(target.guild_id))
        if guild is None:
            logger.warning(
                "Skip daily heatmap because guild is not in cache guild=%s",
                target.guild_id,
            )
            return False

        channel = await self._resolve_post_channel(guild, target.channel_id)
        if channel is None:
            return False

        async with async_session() as session:
            cells = await stats_service.get_hourly_activity_heatmap(
                session,
                target.guild_id,
                days=target.days,
                end_date=target_date,
            )

        if all(cell.voice_seconds <= 0 for cell in cells):
            logger.info(
                "Skip daily heatmap because no VC data guild=%s date=%s",
                target.guild_id,
                target_date,
            )
            return True

        title = format_hourly_activity_heatmap_title(
            days=target.days,
            end_date=target_date,
        )
        try:
            image = render_hourly_activity_heatmap_table_png(cells=cells)
        except RuntimeError:
            logger.exception("Pillow is unavailable for daily heatmap rendering")
            return False

        file = discord.File(
            image,
            filename=f"vc-active-heatmap-{target_date.isoformat()}.png",
        )
        embed = discord.Embed(title=title, color=DEFAULT_EMBED_COLOR)
        embed.set_image(url=f"attachment://{file.filename}")
        embed.set_footer(text="濃い赤ほどVCが集中している時間帯です")
        await channel.send(embed=embed, file=file)
        logger.info(
            "Posted daily heatmap guild=%s channel=%s date=%s days=%d",
            target.guild_id,
            target.channel_id,
            target_date,
            target.days,
        )
        return True


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DailyHeatmapCog(bot))
