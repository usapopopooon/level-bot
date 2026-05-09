"""Public read-only API routes for guild summary + daily series."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_DASHBOARD_DAYS, MAX_DASHBOARD_DAYS
from src.features.stats import service as stats_service
from src.features.stats.schemas import DailyPointOut, GuildSummaryOut
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/guilds/{guild_id}/summary", response_model=GuildSummaryOut)
async def guild_summary(
    guild_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> GuildSummaryOut:
    summary = await stats_service.get_guild_summary(db, guild_id, days=days)
    if summary is None:
        raise HTTPException(status_code=404, detail="Guild not found")
    return GuildSummaryOut(
        guild_id=summary.guild_id,
        name=summary.name,
        icon_url=summary.icon_url,
        total_messages=summary.total_messages,
        total_voice_seconds=summary.total_voice_seconds,
        active_users=summary.active_users,
        days=days,
    )


@router.get("/guilds/{guild_id}/daily", response_model=list[DailyPointOut])
async def guild_daily(
    guild_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> list[DailyPointOut]:
    points = await stats_service.get_daily_series(db, guild_id, days=days)
    return [
        DailyPointOut(
            date=p.stat_date,
            message_count=p.message_count,
            voice_seconds=p.voice_seconds,
        )
        for p in points
    ]
