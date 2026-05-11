"""Public read-only API route for user levels (lifetime-based)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import MAX_DASHBOARD_DAYS
from src.features.leveling.schemas import LevelBreakdownOut, UserLevelsOut
from src.features.leveling.service import (
    ACTIVITY_RATE_WINDOW_DAYS,
    LevelBreakdown,
    compute_user_levels,
    compute_user_levels_from_counts,
    get_recent_activity_rate,
    get_user_window_counts,
)
from src.features.user_profile.service import get_user_lifetime_stats
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["leveling"])


def _breakdown_to_out(b: LevelBreakdown) -> LevelBreakdownOut:
    return LevelBreakdownOut(
        level=b.level,
        xp=b.xp,
        current_floor=b.current_floor,
        next_floor=b.next_floor,
        progress=b.progress,
    )


@router.get(
    "/guilds/{guild_id}/users/{user_id}/levels",
    response_model=UserLevelsOut,
)
async def user_levels(
    guild_id: str,
    user_id: str,
    days: int | None = Query(None, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> UserLevelsOut:
    """ユーザーのレベルを返す。

    ``days`` を指定すると直近 N 日のレベル (期間限定)、省略時は lifetime 累積。
    """
    activity_rate = await get_recent_activity_rate(db, guild_id, user_id)
    if days is None:
        stats = await get_user_lifetime_stats(db, guild_id, user_id)
        if stats is None:
            raise HTTPException(status_code=404, detail="User has no stats")
        levels = compute_user_levels(stats, activity_rate=activity_rate)
    else:
        msgs, voice_secs, rrx, rgx = await get_user_window_counts(
            db, guild_id, user_id, days=days
        )
        levels = compute_user_levels_from_counts(
            messages=msgs,
            voice_seconds=voice_secs,
            reactions_received=rrx,
            reactions_given=rgx,
            activity_rate=activity_rate,
        )
    return UserLevelsOut(
        total=_breakdown_to_out(levels.total),
        voice=_breakdown_to_out(levels.voice),
        text=_breakdown_to_out(levels.text),
        reactions_received=_breakdown_to_out(levels.reactions_received),
        reactions_given=_breakdown_to_out(levels.reactions_given),
        activity_rate=activity_rate,
        activity_rate_window_days=ACTIVITY_RATE_WINDOW_DAYS,
    )
