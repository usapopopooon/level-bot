"""Public read-only API routes for individual user profiles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_DASHBOARD_DAYS, MAX_DASHBOARD_DAYS
from src.features.stats.schemas import DailyPointOut
from src.features.user_profile import service as profile_service
from src.features.user_profile.schemas import TopChannelEntryOut, UserProfileOut
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["user_profile"])


@router.get("/guilds/{guild_id}/users/{user_id}", response_model=UserProfileOut)
async def user_profile(
    guild_id: str,
    user_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> UserProfileOut:
    profile = await profile_service.get_user_profile(db, guild_id, user_id, days=days)
    if profile is None:
        raise HTTPException(status_code=404, detail="User has no stats")
    return UserProfileOut(
        user_id=profile.user_id,
        display_name=profile.display_name,
        avatar_url=profile.avatar_url,
        total_messages=profile.total_messages,
        total_voice_seconds=profile.total_voice_seconds,
        rank_messages=profile.rank_messages,
        rank_voice=profile.rank_voice,
        daily=[
            DailyPointOut(
                date=p.stat_date,
                message_count=p.message_count,
                voice_seconds=p.voice_seconds,
            )
            for p in profile.daily
        ],
        top_channels=[
            TopChannelEntryOut(
                channel_id=c.channel_id,
                name=c.name,
                message_count=c.message_count,
                voice_seconds=c.voice_seconds,
            )
            for c in profile.top_channels
        ],
    )
