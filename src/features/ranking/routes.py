"""Public read-only API routes for user / channel leaderboards."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    DEFAULT_DASHBOARD_DAYS,
    DEFAULT_LEADERBOARD_LIMIT,
    MAX_DASHBOARD_DAYS,
    MAX_LEADERBOARD_LIMIT,
)
from src.features.ranking import service as ranking_service
from src.features.ranking.schemas import (
    ChannelLeaderboardEntryOut,
    LeaderboardEntryOut,
)
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["ranking"])


@router.get(
    "/guilds/{guild_id}/leaderboard/users",
    response_model=list[LeaderboardEntryOut],
)
async def user_leaderboard(
    guild_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    limit: int = Query(DEFAULT_LEADERBOARD_LIMIT, ge=1, le=MAX_LEADERBOARD_LIMIT),
    offset: int = Query(0, ge=0, le=100_000),
    metric: str = Query(
        "messages",
        pattern="^(messages|voice|reactions_received|reactions_given)$",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[LeaderboardEntryOut]:
    entries = await ranking_service.get_user_leaderboard(
        db, guild_id, days=days, limit=limit, offset=offset, metric=metric
    )
    return [
        LeaderboardEntryOut(
            user_id=e.user_id,
            display_name=e.display_name,
            avatar_url=e.avatar_url,
            message_count=e.message_count,
            voice_seconds=e.voice_seconds,
            reactions_received=e.reactions_received,
            reactions_given=e.reactions_given,
        )
        for e in entries
    ]


@router.get(
    "/guilds/{guild_id}/leaderboard/channels",
    response_model=list[ChannelLeaderboardEntryOut],
)
async def channel_leaderboard(
    guild_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    limit: int = Query(DEFAULT_LEADERBOARD_LIMIT, ge=1, le=MAX_LEADERBOARD_LIMIT),
    offset: int = Query(0, ge=0, le=100_000),
    metric: str = Query(
        "messages",
        pattern="^(messages|voice|reactions_received|reactions_given)$",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[ChannelLeaderboardEntryOut]:
    entries = await ranking_service.get_channel_leaderboard(
        db, guild_id, days=days, limit=limit, offset=offset, metric=metric
    )
    return [
        ChannelLeaderboardEntryOut(
            channel_id=e.channel_id,
            name=e.name,
            message_count=e.message_count,
            voice_seconds=e.voice_seconds,
            reactions_received=e.reactions_received,
            reactions_given=e.reactions_given,
        )
        for e in entries
    ]
