"""Public read-only API route for user levels (lifetime-based)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    DEFAULT_LEADERBOARD_LIMIT,
    MAX_DASHBOARD_DAYS,
    MAX_LEADERBOARD_LIMIT,
)
from src.features.leveling.schemas import (
    LevelBreakdownOut,
    LevelLeaderboardEntryOut,
    UserLevelsOut,
)
from src.features.leveling.service import (
    ACTIVITY_RATE_WINDOW_DAYS,
    LevelBreakdown,
    compute_user_levels,
    compute_user_levels_from_counts,
    get_level_leaderboard,
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
    summary="ユーザーレベル",
    description=(
        "総合レベル + 項目別レベル (voice / text / reactions_received / "
        "reactions_given) を返す。"
        "\n\n- ``days`` 省略時: lifetime 累積を集計"
        "\n- ``days=N`` 指定時: 直近 N 日のレベル"
        "\n\nXP に直近 30 日のアクティブ率 (`active_days/30`) を掛け率として"
        "適用するため、長期不在で実効レベルは下がる。表示除外ユーザーや"
        "完全に活動ゼロのユーザーは 404。"
    ),
)
async def user_levels(
    guild_id: str,
    user_id: str,
    days: int | None = Query(None, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> UserLevelsOut:
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


@router.get(
    "/guilds/{guild_id}/levels/leaderboard",
    response_model=list[LevelLeaderboardEntryOut],
    summary="レベルリーダーボード",
    description=(
        "指定 ``axis`` のレベル降順でユーザーを返す。XP は lifetime 累積に直近"
        " 30 日のアクティブ率を掛けた値。表示除外ユーザーは結果から外れる。"
        "\n\n``axis`` は ``total`` / ``voice`` / ``text`` / "
        "``reactions_received`` / ``reactions_given`` のいずれか。"
    ),
)
async def levels_leaderboard(
    guild_id: str,
    axis: str = Query(
        "total",
        pattern="^(total|voice|text|reactions_received|reactions_given)$",
    ),
    limit: int = Query(DEFAULT_LEADERBOARD_LIMIT, ge=1, le=MAX_LEADERBOARD_LIMIT),
    offset: int = Query(0, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db),
) -> list[LevelLeaderboardEntryOut]:
    entries = await get_level_leaderboard(
        db, guild_id, axis=axis, limit=limit, offset=offset
    )
    return [
        LevelLeaderboardEntryOut(
            user_id=e.user_id,
            display_name=e.display_name,
            avatar_url=e.avatar_url,
            level=e.level,
            xp=e.xp,
            activity_rate=e.activity_rate,
        )
        for e in entries
    ]
