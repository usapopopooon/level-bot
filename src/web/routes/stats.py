"""Public stats API routes (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    DEFAULT_DASHBOARD_DAYS,
    DEFAULT_LEADERBOARD_LIMIT,
    MAX_DASHBOARD_DAYS,
    MAX_LEADERBOARD_LIMIT,
)
from src.services import stats_service as ss
from src.web.deps import get_db
from src.web.schemas import (
    ChannelLeaderboardEntryOut,
    DailyPointOut,
    GuildOut,
    GuildSummaryOut,
    LeaderboardEntryOut,
    UserProfileOut,
)

router = APIRouter(prefix="/api/v1", tags=["stats"])


@router.get("/guilds", response_model=list[GuildOut])
async def list_guilds(db: AsyncSession = Depends(get_db)) -> list[GuildOut]:
    """公開設定のあるアクティブギルドの一覧を返す。"""
    guilds = await ss.list_active_guilds(db)
    return [
        GuildOut(
            guild_id=g.guild_id,
            name=g.name,
            icon_url=g.icon_url,
            member_count=g.member_count,
        )
        for g in guilds
        if (g.settings is None or g.settings.public)
    ]


@router.get("/guilds/{guild_id}/summary", response_model=GuildSummaryOut)
async def guild_summary(
    guild_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> GuildSummaryOut:
    summary = await ss.get_guild_summary(db, guild_id, days=days)
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
    points = await ss.get_daily_series(db, guild_id, days=days)
    return [
        DailyPointOut(
            date=p.stat_date,
            message_count=p.message_count,
            voice_seconds=p.voice_seconds,
        )
        for p in points
    ]


@router.get(
    "/guilds/{guild_id}/leaderboard/users",
    response_model=list[LeaderboardEntryOut],
)
async def user_leaderboard(
    guild_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    limit: int = Query(DEFAULT_LEADERBOARD_LIMIT, ge=1, le=MAX_LEADERBOARD_LIMIT),
    offset: int = Query(0, ge=0, le=100_000),
    metric: str = Query("messages", pattern="^(messages|voice)$"),
    db: AsyncSession = Depends(get_db),
) -> list[LeaderboardEntryOut]:
    entries = await ss.get_user_leaderboard(
        db, guild_id, days=days, limit=limit, offset=offset, metric=metric
    )
    return [
        LeaderboardEntryOut(
            user_id=e.user_id,
            display_name=e.display_name,
            avatar_url=e.avatar_url,
            message_count=e.message_count,
            voice_seconds=e.voice_seconds,
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
    metric: str = Query("messages", pattern="^(messages|voice)$"),
    db: AsyncSession = Depends(get_db),
) -> list[ChannelLeaderboardEntryOut]:
    entries = await ss.get_channel_leaderboard(
        db, guild_id, days=days, limit=limit, offset=offset, metric=metric
    )
    return [
        ChannelLeaderboardEntryOut(
            channel_id=e.channel_id,
            name=e.name,
            message_count=e.message_count,
            voice_seconds=e.voice_seconds,
        )
        for e in entries
    ]


@router.get("/guilds/{guild_id}/users/{user_id}", response_model=UserProfileOut)
async def user_profile(
    guild_id: str,
    user_id: str,
    days: int = Query(DEFAULT_DASHBOARD_DAYS, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> UserProfileOut:
    profile = await ss.get_user_profile(db, guild_id, user_id, days=days)
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
            ChannelLeaderboardEntryOut(
                channel_id=c.channel_id,
                name=c.name,
                message_count=c.message_count,
                voice_seconds=c.voice_seconds,
            )
            for c in profile.top_channels
        ],
    )
