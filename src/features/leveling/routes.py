"""Public read-only API route for user levels (lifetime-based)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
    LevelBreakdown,
    compute_user_levels,
    compute_user_levels_from_counts,
    get_level_leaderboard,
    get_user_window_counts,
)
from src.features.user_profile.service import get_user_lifetime_stats
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["leveling"])

# レベル系は per-user な情報も含むため "private" にして共有キャッシュを禁止し、
# ブラウザ / クライアント側でのみ短時間 (30 秒) キャッシュを許容する。
_LEVEL_CACHE_CONTROL = "private, max-age=30"


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
        "\n\nレベルは純粋累積 XP で算出 (期間によるアクティブ率減衰は無し)。"
        "表示除外ユーザーや完全に活動ゼロのユーザーは 404。"
    ),
)
async def user_levels(
    guild_id: str,
    user_id: str,
    response: Response,
    days: int | None = Query(None, ge=1, le=MAX_DASHBOARD_DAYS),
    db: AsyncSession = Depends(get_db),
) -> UserLevelsOut:
    response.headers["Cache-Control"] = _LEVEL_CACHE_CONTROL
    if days is None:
        stats = await get_user_lifetime_stats(db, guild_id, user_id)
        if stats is None:
            raise HTTPException(status_code=404, detail="User has no stats")
        levels = compute_user_levels(stats)
    else:
        msgs, voice_secs, rrx, rgx = await get_user_window_counts(
            db, guild_id, user_id, days=days
        )
        levels = compute_user_levels_from_counts(
            messages=msgs,
            voice_seconds=voice_secs,
            reactions_received=rrx,
            reactions_given=rgx,
        )
    return UserLevelsOut(
        total=_breakdown_to_out(levels.total),
        voice=_breakdown_to_out(levels.voice),
        text=_breakdown_to_out(levels.text),
        reactions_received=_breakdown_to_out(levels.reactions_received),
        reactions_given=_breakdown_to_out(levels.reactions_given),
    )


@router.get(
    "/guilds/{guild_id}/levels/leaderboard",
    response_model=list[LevelLeaderboardEntryOut],
    summary="レベルリーダーボード",
    description=(
        "指定 ``axis`` のレベル降順でユーザーを返す。XP は lifetime 累積 (期間"
        "減衰なし)。表示除外ユーザーは結果から外れる。"
        "\n\n``axis`` は ``total`` / ``voice`` / ``text`` / "
        "``reactions_received`` / ``reactions_given`` のいずれか。"
    ),
)
async def levels_leaderboard(
    guild_id: str,
    response: Response,
    axis: str = Query(
        "total",
        pattern="^(total|voice|text|reactions_received|reactions_given)$",
    ),
    limit: int = Query(DEFAULT_LEADERBOARD_LIMIT, ge=1, le=MAX_LEADERBOARD_LIMIT),
    offset: int = Query(0, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db),
) -> list[LevelLeaderboardEntryOut]:
    response.headers["Cache-Control"] = _LEVEL_CACHE_CONTROL
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
        )
        for e in entries
    ]
