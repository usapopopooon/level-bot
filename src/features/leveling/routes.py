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
    XpWeightLogCreateIn,
    XpWeightLogOut,
    XpWeightMirrorCheckOut,
    XpWeightRollbackIn,
)
from src.features.leveling.service import (
    LevelBreakdown,
    append_xp_weight_log,
    compare_xp_weight_log_mirror,
    get_level_leaderboard,
    get_user_lifetime_levels,
    get_user_window_levels,
    list_xp_weight_logs,
    rollback_xp_weight_log,
)
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
        "\n\n- ``days`` 省略時: lifetime 獲得 XP からカラーロール交換の"
        "消費 XP を差し引いた現在レベル"
        "\n- ``days=N`` 指定時: 直近 N 日の獲得 XP だけで見る期間レベル"
        " (交換消費 XP は差し引かない)"
        "\n\n項目別レベルは各項目の獲得 XP で算出。期間による"
        "アクティブ率減衰は無し。"
        "表示除外ユーザー・脱退済みユーザー・完全に活動ゼロのユーザーは 404。"
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
        levels = await get_user_lifetime_levels(
            db, guild_id, user_id, require_active_member=True
        )
        if levels is None:
            raise HTTPException(status_code=404, detail="User has no stats")
    else:
        levels = await get_user_window_levels(
            db, guild_id, user_id, days=days, require_active_member=True
        )
        if levels is None:
            raise HTTPException(status_code=404, detail="User has no stats")
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
        "指定 ``axis`` のレベル降順でユーザーを返す。``total`` の XP は交換消費"
        "を差し引いた現在値、各項目の XP は lifetime 獲得値 (期間減衰なし)。"
        "表示除外ユーザーと脱退済みユーザーは結果から外れる。"
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


@router.get(
    "/leveling/xp-weight-logs",
    response_model=list[XpWeightLogOut],
    summary="XP重みログ一覧",
)
async def get_xp_weight_logs(
    db: AsyncSession = Depends(get_db),
) -> list[XpWeightLogOut]:
    logs = await list_xp_weight_logs(db)
    return [
        XpWeightLogOut(
            effective_from=log.effective_from,
            message_weight=log.message_weight,
            reaction_received_weight=log.reaction_received_weight,
            reaction_given_weight=log.reaction_given_weight,
        )
        for log in logs
    ]


@router.get(
    "/leveling/xp-weight-logs/mirror-check",
    response_model=XpWeightMirrorCheckOut,
    summary="XP重みmirror整合性チェック",
)
async def get_xp_weight_mirror_check(
    db: AsyncSession = Depends(get_db),
) -> XpWeightMirrorCheckOut:
    result = await compare_xp_weight_log_mirror(db)
    return XpWeightMirrorCheckOut(
        rate_source="level_xp_weight_versions",
        matches=result.matches,
        legacy_only=result.legacy_only,
        version_only=result.version_only,
        mismatched=result.mismatched,
    )


@router.post(
    "/leveling/xp-weight-logs",
    response_model=XpWeightLogOut,
    summary="XP重みログ追加",
)
async def create_xp_weight_log(
    payload: XpWeightLogCreateIn,
    db: AsyncSession = Depends(get_db),
) -> XpWeightLogOut:
    try:
        created = await append_xp_weight_log(
            db,
            effective_from=payload.effective_from,
            message_weight=payload.message_weight,
            reaction_received_weight=payload.reaction_received_weight,
            reaction_given_weight=payload.reaction_given_weight,
            actor_id=payload.actor_id,
            reason=payload.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return XpWeightLogOut(
        effective_from=created.effective_from,
        message_weight=created.message_weight,
        reaction_received_weight=created.reaction_received_weight,
        reaction_given_weight=created.reaction_given_weight,
    )


@router.post(
    "/leveling/xp-weight-logs/rollback",
    response_model=XpWeightLogOut,
    summary="XP重みログロールバック",
)
async def create_xp_weight_log_rollback(
    payload: XpWeightRollbackIn,
    db: AsyncSession = Depends(get_db),
) -> XpWeightLogOut:
    try:
        created = await rollback_xp_weight_log(
            db,
            effective_from=payload.effective_from,
            target_effective_from=payload.target_effective_from,
            actor_id=payload.actor_id,
            reason=payload.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return XpWeightLogOut(
        effective_from=created.effective_from,
        message_weight=created.message_weight,
        reaction_received_weight=created.reaction_received_weight,
        reaction_given_weight=created.reaction_given_weight,
    )
