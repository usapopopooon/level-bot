"""ユーザーレベル: 総合レベル + 項目別レベルの算出。

設計:
    - 各活動を XP に換算 → 累計 XP からレベルを求める
    - レベル曲線は純粋指数: req(L) = base * ratio^(L-1)
      累計: cum(L) = base * (ratio^L - 1) / (ratio - 1)
    - 総合レベル: 4 指標の XP 合計から計算
    - 項目別レベル (voice / text / reactions_received / reactions_given):
      各指標 XP から **同じ曲線** で個別に計算 (難易度が揃う)

重み (1 単位あたりの XP):
    VC:                 1 XP / 分
    TC:                 30.0 XP / メッセージ
    リアクション (受):  20.0 XP / 個
    リアクション (送):  20.0 XP / 個

レベルは純粋累積。期間によるアクティブ率減衰は行わない (一度上げたら下がらない)。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, ExcludedUser, LevelXpWeightLog
from src.features.meta.service import get_user_meta_map
from src.features.tracking.service import live_voice_deltas
from src.features.user_profile.service import UserLifetimeStats, get_user_lifetime_stats
from src.utils import date_window, today_local

# =============================================================================
# 重み
# =============================================================================

XP_PER_VOICE_MINUTE = 1.0

# 初期実装当時の重み
XP_PER_MESSAGE_LEGACY = 2.0
XP_PER_REACTION_GIVEN_LEGACY = 0.5
XP_PER_REACTION_RECEIVED_LEGACY = 0.5

# 現在運用中の重み (切替日以降に獲得した分にのみ適用)
XP_PER_MESSAGE_CURRENT = 30.0
XP_PER_REACTION_GIVEN_CURRENT = 20.0
XP_PER_REACTION_RECEIVED_CURRENT = 20.0

# =============================================================================
# レベル曲線
# =============================================================================

LEVEL_BASE_XP = 100
LEVEL_GROWTH_RATIO = 1.2


def cumulative_xp_for_level(
    level: int,
    *,
    base: int = LEVEL_BASE_XP,
    ratio: float = LEVEL_GROWTH_RATIO,
) -> int:
    """L レベル到達に必要な累計 XP。L=0 で 0、L=1 で ``base``。"""
    if level <= 0:
        return 0
    return round(base * (ratio**level - 1) / (ratio - 1))


def level_from_xp(
    xp: int,
    *,
    base: int = LEVEL_BASE_XP,
    ratio: float = LEVEL_GROWTH_RATIO,
) -> int:
    """累計 XP に対応するレベル。``xp < base`` は L0。

    解析解で近似してから 1 段だけ前後を確認することで FP 誤差を吸収する。
    """
    if xp < base:
        return 0
    approx = math.log(xp * (ratio - 1) / base + 1) / math.log(ratio)
    level = max(0, int(approx))
    while cumulative_xp_for_level(level + 1, base=base, ratio=ratio) <= xp:
        level += 1
    while level > 0 and cumulative_xp_for_level(level, base=base, ratio=ratio) > xp:
        level -= 1
    return level


# =============================================================================
# Result types
# =============================================================================


@dataclass
class LevelBreakdown:
    """単一指標 (または総合) のレベル状態。"""

    level: int
    xp: int  # この指標の累計 XP
    current_floor: int  # 現レベル到達に必要な累計 XP
    next_floor: int  # 次レベル到達に必要な累計 XP

    @property
    def progress(self) -> float:
        """現レベル → 次レベルへの進捗 (0.0-1.0)。"""
        span = self.next_floor - self.current_floor
        if span <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.xp - self.current_floor) / span))


@dataclass
class UserLevels:
    """総合レベル + 項目別レベルのセット。"""

    total: LevelBreakdown
    voice: LevelBreakdown
    text: LevelBreakdown
    reactions_received: LevelBreakdown
    reactions_given: LevelBreakdown


@dataclass(frozen=True)
class XpWeightLog:
    effective_from: date
    message_weight: float
    reaction_received_weight: float
    reaction_given_weight: float


def _breakdown_from_xp(xp: int) -> LevelBreakdown:
    lvl = level_from_xp(xp)
    return LevelBreakdown(
        level=lvl,
        xp=xp,
        current_floor=cumulative_xp_for_level(lvl),
        next_floor=cumulative_xp_for_level(lvl + 1),
    )


async def list_xp_weight_logs(
    session: AsyncSession, *, use_cache: bool = True
) -> list[XpWeightLog]:
    global _WEIGHT_LOG_CACHE_VALUE, _WEIGHT_LOG_CACHE_AT
    now = time.monotonic()
    if use_cache and (
        _WEIGHT_LOG_CACHE_VALUE is not None
        and now - _WEIGHT_LOG_CACHE_AT <= _WEIGHT_LOG_CACHE_TTL_SECONDS
    ):
        return _WEIGHT_LOG_CACHE_VALUE

    rows = (
        (
            await session.execute(
                select(LevelXpWeightLog).order_by(LevelXpWeightLog.effective_from.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        msg = "level_xp_weight_logs is empty; seed at least one weight log"
        raise RuntimeError(msg)
    logs = [
        XpWeightLog(
            effective_from=row.effective_from,
            message_weight=float(row.message_weight),
            reaction_received_weight=float(row.reaction_received_weight),
            reaction_given_weight=float(row.reaction_given_weight),
        )
        for row in rows
    ]
    _WEIGHT_LOG_CACHE_VALUE = logs
    _WEIGHT_LOG_CACHE_AT = now
    return logs


def _validate_weights(
    message_weight: float,
    recv_weight: float,
    given_weight: float,
) -> None:
    for name, value in (
        ("message_weight", message_weight),
        ("reaction_received_weight", recv_weight),
        ("reaction_given_weight", given_weight),
    ):
        if value <= 0:
            msg = f"{name} must be > 0"
            raise ValueError(msg)


async def append_xp_weight_log(
    session: AsyncSession,
    *,
    effective_from: date,
    message_weight: float,
    reaction_received_weight: float,
    reaction_given_weight: float,
) -> XpWeightLog:
    _validate_weights(message_weight, reaction_received_weight, reaction_given_weight)
    logs = await list_xp_weight_logs(session, use_cache=False)
    latest = logs[-1]
    if effective_from <= latest.effective_from:
        msg = (
            "effective_from must be greater than latest effective_from "
            f"({latest.effective_from.isoformat()})"
        )
        raise ValueError(msg)
    session.add(
        LevelXpWeightLog(
            effective_from=effective_from,
            message_weight=message_weight,
            reaction_received_weight=reaction_received_weight,
            reaction_given_weight=reaction_given_weight,
        )
    )
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        msg = "effective_from already exists"
        raise ValueError(msg) from e
    _invalidate_weight_log_cache()
    return XpWeightLog(
        effective_from=effective_from,
        message_weight=message_weight,
        reaction_received_weight=reaction_received_weight,
        reaction_given_weight=reaction_given_weight,
    )


async def rollback_xp_weight_log(
    session: AsyncSession,
    *,
    effective_from: date,
) -> XpWeightLog:
    logs = await list_xp_weight_logs(session, use_cache=False)
    if len(logs) < 2:
        msg = "rollback requires at least 2 weight logs"
        raise ValueError(msg)
    base = logs[-2]
    return await append_xp_weight_log(
        session,
        effective_from=effective_from,
        message_weight=base.message_weight,
        reaction_received_weight=base.reaction_received_weight,
        reaction_given_weight=base.reaction_given_weight,
    )


_WEIGHT_LOG_CACHE_TTL_SECONDS = 5.0
_WEIGHT_LOG_CACHE_AT = 0.0
_WEIGHT_LOG_CACHE_VALUE: list[XpWeightLog] | None = None


def _invalidate_weight_log_cache() -> None:
    global _WEIGHT_LOG_CACHE_AT, _WEIGHT_LOG_CACHE_VALUE
    _WEIGHT_LOG_CACHE_AT = 0.0
    _WEIGHT_LOG_CACHE_VALUE = None


def _weights_for_day(day: date, logs: list[XpWeightLog]) -> tuple[float, float, float]:
    """指定日の (message, reactions_received, reactions_given) 重みを返す。"""
    active = logs[0]
    for log in logs:
        if day < log.effective_from:
            break
        active = log
    return (
        active.message_weight,
        active.reaction_received_weight,
        active.reaction_given_weight,
    )


def _xp_from_counts(
    *,
    messages: int,
    voice_seconds: int,
    reactions_received: int,
    reactions_given: int,
    message_weight: float,
    reactions_received_weight: float,
    reactions_given_weight: float,
) -> tuple[int, int, int, int]:
    voice_xp = round(voice_seconds / 60.0 * XP_PER_VOICE_MINUTE)
    text_xp = round(messages * message_weight)
    rrx_xp = round(reactions_received * reactions_received_weight)
    rgx_xp = round(reactions_given * reactions_given_weight)
    return voice_xp, text_xp, rrx_xp, rgx_xp


def _levels_from_axis_xp(
    *,
    voice_xp: int,
    text_xp: int,
    reactions_received_xp: int,
    reactions_given_xp: int,
) -> UserLevels:
    total_xp = voice_xp + text_xp + reactions_received_xp + reactions_given_xp
    return UserLevels(
        total=_breakdown_from_xp(total_xp),
        voice=_breakdown_from_xp(voice_xp),
        text=_breakdown_from_xp(text_xp),
        reactions_received=_breakdown_from_xp(reactions_received_xp),
        reactions_given=_breakdown_from_xp(reactions_given_xp),
    )


def _weight_case_expr(logs: list[XpWeightLog], values: list[float]) -> Any:
    if len(logs) == 1:
        return values[0]

    whens: list[tuple[Any, float]] = []
    for idx in range(len(logs) - 1):
        next_start = logs[idx + 1].effective_from
        whens.append((DailyStat.stat_date < next_start, values[idx]))
    return case(*whens, else_=values[-1])


def compute_user_levels_from_counts(
    *,
    messages: int,
    voice_seconds: int,
    reactions_received: int,
    reactions_given: int,
) -> UserLevels:
    """4 指標の生カウントからレベルを算出する。

    各 axis を先に丸めて整数化し、総合 XP はそれら整数の合計とする。
    こうしないと axis 別丸め誤差で ``total.xp != sum(axes.xp)`` が起きる。
    """
    # 互換用途の純関数ヘルパー。DB 履歴は参照せず「現行重み」で算出する。
    msg_w = XP_PER_MESSAGE_CURRENT
    recv_w = XP_PER_REACTION_RECEIVED_CURRENT
    given_w = XP_PER_REACTION_GIVEN_CURRENT
    voice_xp, text_xp, rrx_xp, rgx_xp = _xp_from_counts(
        messages=messages,
        voice_seconds=voice_seconds,
        reactions_received=reactions_received,
        reactions_given=reactions_given,
        message_weight=msg_w,
        reactions_received_weight=recv_w,
        reactions_given_weight=given_w,
    )
    return _levels_from_axis_xp(
        voice_xp=voice_xp,
        text_xp=text_xp,
        reactions_received_xp=rrx_xp,
        reactions_given_xp=rgx_xp,
    )


def compute_user_levels(stats: UserLifetimeStats) -> UserLevels:
    """``UserLifetimeStats`` からレベルを算出する (互換用)。"""
    return compute_user_levels_from_counts(
        messages=stats.total_messages,
        voice_seconds=stats.total_voice_seconds,
        reactions_received=stats.total_reactions_received,
        reactions_given=stats.total_reactions_given,
    )


def _levels_from_daily_rows(
    rows: list[tuple[date, int, int, int, int]],
    *,
    weight_logs: list[XpWeightLog],
    live_voice_by_day: dict[date, int] | None = None,
) -> UserLevels:
    voice_xp = 0
    text_xp = 0
    rrx_xp = 0
    rgx_xp = 0

    by_day = {
        day: (msgs, voice_secs, recv, given)
        for day, msgs, voice_secs, recv, given in rows
    }
    all_days = set(by_day.keys())
    if live_voice_by_day:
        all_days.update(live_voice_by_day.keys())

    for day in sorted(all_days):
        msgs, voice_secs, recv, given = by_day.get(day, (0, 0, 0, 0))
        if live_voice_by_day:
            voice_secs += live_voice_by_day.get(day, 0)
        msg_w, recv_w, given_w = _weights_for_day(day, weight_logs)
        dv, dt, dr, dg = _xp_from_counts(
            messages=msgs,
            voice_seconds=voice_secs,
            reactions_received=recv,
            reactions_given=given,
            message_weight=msg_w,
            reactions_received_weight=recv_w,
            reactions_given_weight=given_w,
        )
        voice_xp += dv
        text_xp += dt
        rrx_xp += dr
        rgx_xp += dg

    return _levels_from_axis_xp(
        voice_xp=voice_xp,
        text_xp=text_xp,
        reactions_received_xp=rrx_xp,
        reactions_given_xp=rgx_xp,
    )


async def _fetch_user_daily_rows(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[tuple[date, int, int, int, int]]:
    stmt = (
        select(
            DailyStat.stat_date,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
            func.coalesce(func.sum(DailyStat.reactions_received), 0),
            func.coalesce(func.sum(DailyStat.reactions_given), 0),
        )
        .where(and_(DailyStat.guild_id == guild_id, DailyStat.user_id == user_id))
        .group_by(DailyStat.stat_date)
        .order_by(DailyStat.stat_date.asc())
    )
    if start is not None:
        stmt = stmt.where(DailyStat.stat_date >= start)
    if end is not None:
        stmt = stmt.where(DailyStat.stat_date <= end)
    return [
        (row[0], int(row[1]), int(row[2]), int(row[3]), int(row[4]))
        for row in (await session.execute(stmt)).all()
    ]


async def _fetch_live_voice_by_day(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[date, int]:
    resolved_end = end or today_local()
    deltas = await live_voice_deltas(
        session,
        guild_id,
        start_date=start,
        end_date=resolved_end,
        user_id=user_id,
    )
    live_voice_by_day: dict[date, int] = {}
    for d in deltas:
        live_voice_by_day[d.day] = live_voice_by_day.get(d.day, 0) + d.seconds
    return live_voice_by_day


async def get_user_lifetime_levels(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    include_live_voice: bool = True,
) -> UserLevels | None:
    stats = await get_user_lifetime_stats(session, guild_id, user_id)
    if stats is None:
        return None
    weight_logs = await list_xp_weight_logs(session)
    rows = await _fetch_user_daily_rows(session, guild_id, user_id)
    live_voice_by_day: dict[date, int] | None = None
    if include_live_voice:
        live_voice_by_day = await _fetch_live_voice_by_day(
            session,
            guild_id,
            user_id,
            start=None,
            end=today_local(),
        )
    return _levels_from_daily_rows(
        rows,
        weight_logs=weight_logs,
        live_voice_by_day=live_voice_by_day,
    )


async def get_user_window_levels(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    days: int,
) -> UserLevels:
    start, end = date_window(days)
    weight_logs = await list_xp_weight_logs(session)
    rows = await _fetch_user_daily_rows(
        session, guild_id, user_id, start=start, end=end
    )
    live_voice_by_day = await _fetch_live_voice_by_day(
        session, guild_id, user_id, start=start, end=end
    )
    return _levels_from_daily_rows(
        rows,
        weight_logs=weight_logs,
        live_voice_by_day=live_voice_by_day,
    )


LEVEL_AXES: tuple[str, ...] = (
    "total",
    "voice",
    "text",
    "reactions_received",
    "reactions_given",
)


@dataclass
class LevelLeaderboardEntry:
    """レベルランキングの 1 行。"""

    user_id: str
    display_name: str
    avatar_url: str | None
    level: int  # ``axis`` で指定された軸のレベル
    xp: int  # 同軸の累計 XP


async def get_level_leaderboard(
    session: AsyncSession,
    guild_id: str,
    *,
    axis: str = "total",
    limit: int = 10,
    offset: int = 0,
) -> list[LevelLeaderboardEntry]:
    """指定 axis のレベルが高い順にユーザーを返す。

    パフォーマンス最適化:
    - 集計・ソート・LIMIT を **SQL 側で実行** し、Python が触るのは ``limit`` 件のみ
    - 除外ユーザーは ``NOT IN`` の subquery でクエリ内で弾く
    - axis に応じた ORDER BY 式: total は重み付き式、それ以外は対応 SUM 単体

    XP は lifetime 累積。live voice delta は計算コスト上スキップする
    (個別プロフィールと若干値が違う可能性があるが、サーバー全体のランキング
    用途では許容)。

    SQL 並び順は近似 XP (連続値) で、Python 側は丸めた整数 XP を返す。
    境界付近の同点ユーザーが入れ替わる可能性はあるが順位 1 位差レベルの揺れ。
    """
    if axis not in LEVEL_AXES:
        msg = f"unknown axis: {axis!r}; expected one of {LEVEL_AXES}"
        raise ValueError(msg)
    weight_logs = await list_xp_weight_logs(session)
    message_weight_case = _weight_case_expr(
        weight_logs, [log.message_weight for log in weight_logs]
    )
    reaction_received_weight_case = _weight_case_expr(
        weight_logs, [log.reaction_received_weight for log in weight_logs]
    )
    reaction_given_weight_case = _weight_case_expr(
        weight_logs, [log.reaction_given_weight for log in weight_logs]
    )

    msg_weighted = func.coalesce(
        func.sum(DailyStat.message_count * message_weight_case),
        0.0,
    )
    voice_xp_weighted = func.coalesce(
        func.sum(DailyStat.voice_seconds / 60.0 * XP_PER_VOICE_MINUTE),
        0.0,
    )
    rrx_weighted = func.coalesce(
        func.sum(DailyStat.reactions_received * reaction_received_weight_case),
        0.0,
    )
    rgx_weighted = func.coalesce(
        func.sum(DailyStat.reactions_given * reaction_given_weight_case),
        0.0,
    )

    # axis 別の ORDER BY 式。total は重み付き合計 (近似 XP)
    order_expr: Any
    if axis == "total":
        order_expr = msg_weighted + voice_xp_weighted + rrx_weighted + rgx_weighted
    elif axis == "voice":
        order_expr = voice_xp_weighted
    elif axis == "text":
        order_expr = msg_weighted
    elif axis == "reactions_received":
        order_expr = rrx_weighted
    else:  # reactions_given
        order_expr = rgx_weighted

    excluded_subq = (
        select(ExcludedUser.user_id)
        .where(ExcludedUser.guild_id == guild_id)
        .scalar_subquery()
    )

    stmt = (
        select(
            DailyStat.user_id,
            msg_weighted,
            voice_xp_weighted,
            rrx_weighted,
            rgx_weighted,
        )
        .where(
            DailyStat.guild_id == guild_id,
            DailyStat.user_id.notin_(excluded_subq),
        )
        .group_by(DailyStat.user_id)
        # 同点時の安定ソート用に user_id を 2nd key (降順) として入れる
        .order_by(order_expr.desc(), DailyStat.user_id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()

    entries: list[tuple[str, LevelLeaderboardEntry]] = []
    for user_id, text_xp_f, voice_xp_f, rrx_xp_f, rgx_xp_f in rows:
        levels = _levels_from_axis_xp(
            voice_xp=round(float(voice_xp_f)),
            text_xp=round(float(text_xp_f)),
            reactions_received_xp=round(float(rrx_xp_f)),
            reactions_given_xp=round(float(rgx_xp_f)),
        )
        breakdown = getattr(levels, axis)
        entries.append(
            (
                user_id,
                LevelLeaderboardEntry(
                    user_id=user_id,
                    display_name=user_id,  # 後で meta で上書き
                    avatar_url=None,
                    level=breakdown.level,
                    xp=breakdown.xp,
                ),
            )
        )

    meta_map = await get_user_meta_map(session, [uid for uid, _ in entries])
    return [
        LevelLeaderboardEntry(
            user_id=entry.user_id,
            display_name=(
                meta_map[uid].display_name if uid in meta_map else entry.user_id
            ),
            avatar_url=meta_map[uid].avatar_url if uid in meta_map else None,
            level=entry.level,
            xp=entry.xp,
        )
        for uid, entry in entries
    ]


async def get_user_window_counts(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    days: int,
) -> tuple[int, int, int, int]:
    """期間内の (messages, voice_seconds, reactions_received, reactions_given)。

    voice には進行中セッションの live delta を含める。
    ``user_id`` のレコードが無くても 0 を返す (None にはしない)。
    """
    start, end = date_window(days)
    stmt = select(
        func.coalesce(func.sum(DailyStat.message_count), 0),
        func.coalesce(func.sum(DailyStat.voice_seconds), 0),
        func.coalesce(func.sum(DailyStat.reactions_received), 0),
        func.coalesce(func.sum(DailyStat.reactions_given), 0),
    ).where(
        and_(
            DailyStat.guild_id == guild_id,
            DailyStat.user_id == user_id,
            DailyStat.stat_date >= start,
            DailyStat.stat_date <= end,
        )
    )
    msgs, voice_static, rrx, rgx = (await session.execute(stmt)).one()
    deltas = await live_voice_deltas(
        session, guild_id, start_date=start, end_date=end, user_id=user_id
    )
    voice_live = sum(d.seconds for d in deltas)
    return int(msgs), int(voice_static) + voice_live, int(rrx), int(rgx)
