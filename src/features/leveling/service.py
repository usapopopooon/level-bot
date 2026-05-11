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
    TC:                 2 XP / メッセージ
    リアクション (受):  0.5 XP / 個
    リアクション (送):  0.5 XP / 個
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat
from src.features.meta.service import get_user_meta_map
from src.features.tracking.service import live_voice_deltas
from src.features.user_profile.service import UserLifetimeStats
from src.utils import date_window

# =============================================================================
# 重み
# =============================================================================

XP_PER_VOICE_MINUTE = 1.0
XP_PER_MESSAGE = 2.0
XP_PER_REACTION_GIVEN = 0.5
XP_PER_REACTION_RECEIVED = 0.5

# =============================================================================
# レベル曲線
# =============================================================================

LEVEL_BASE_XP = 100
LEVEL_GROWTH_RATIO = 1.2

# =============================================================================
# アクティブ率による減衰
# =============================================================================
# 直近 N 日のうち活動があった日の割合 (active_days / N) を XP の掛け率にする。
# rate=1.0 で減衰無し、rate=0.0 で全 XP がゼロ (実質 L0)。サボった古参が
# レベルを維持できないようにする目的。
ACTIVITY_RATE_WINDOW_DAYS = 30


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


def _breakdown_from_xp(xp: int) -> LevelBreakdown:
    lvl = level_from_xp(xp)
    return LevelBreakdown(
        level=lvl,
        xp=xp,
        current_floor=cumulative_xp_for_level(lvl),
        next_floor=cumulative_xp_for_level(lvl + 1),
    )


def compute_user_levels_from_counts(
    *,
    messages: int,
    voice_seconds: int,
    reactions_received: int,
    reactions_given: int,
    activity_rate: float = 1.0,
) -> UserLevels:
    """4 指標の生カウントからレベルを算出する。

    ``activity_rate`` (0.0-1.0) は最近のアクティブ率による掛け率で、サボった
    古参のレベルが下がるように XP 全体に乗じる。

    各 axis を先に丸めて整数化し、総合 XP はそれら整数の合計とする。
    こうしないと axis 別丸め誤差で ``total.xp != sum(axes.xp)`` が起きる。
    """
    rate = min(1.0, max(0.0, activity_rate))
    voice_xp = round(voice_seconds / 60.0 * XP_PER_VOICE_MINUTE * rate)
    text_xp = round(messages * XP_PER_MESSAGE * rate)
    rrx = round(reactions_received * XP_PER_REACTION_RECEIVED * rate)
    rgx = round(reactions_given * XP_PER_REACTION_GIVEN * rate)
    total_xp = voice_xp + text_xp + rrx + rgx
    return UserLevels(
        total=_breakdown_from_xp(total_xp),
        voice=_breakdown_from_xp(voice_xp),
        text=_breakdown_from_xp(text_xp),
        reactions_received=_breakdown_from_xp(rrx),
        reactions_given=_breakdown_from_xp(rgx),
    )


def compute_user_levels(
    stats: UserLifetimeStats, *, activity_rate: float = 1.0
) -> UserLevels:
    """``UserLifetimeStats`` (lifetime 累積) からレベルを算出する。"""
    return compute_user_levels_from_counts(
        messages=stats.total_messages,
        voice_seconds=stats.total_voice_seconds,
        reactions_received=stats.total_reactions_received,
        reactions_given=stats.total_reactions_given,
        activity_rate=activity_rate,
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
    xp: int  # 同軸の (減衰後) XP
    activity_rate: float


async def get_level_leaderboard(
    session: AsyncSession,
    guild_id: str,
    *,
    axis: str = "total",
    limit: int = 10,
    offset: int = 0,
) -> list[LevelLeaderboardEntry]:
    """指定 axis のレベルが高い順にユーザーを返す。

    XP は lifetime 累積を直近 ``ACTIVITY_RATE_WINDOW_DAYS`` 日のアクティブ率で
    減衰した値。live voice delta は計算コスト上スキップする (個別プロフィールと
    若干値が違う可能性があるが、サーバー全体のランキング用途では許容)。
    """
    if axis not in LEVEL_AXES:
        msg = f"unknown axis: {axis!r}; expected one of {LEVEL_AXES}"
        raise ValueError(msg)

    rate_start, _ = date_window(ACTIVITY_RATE_WINDOW_DAYS)
    recent_date = case(
        (DailyStat.stat_date >= rate_start, DailyStat.stat_date),
        else_=None,
    )
    stmt = (
        select(
            DailyStat.user_id,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
            func.coalesce(func.sum(DailyStat.reactions_received), 0),
            func.coalesce(func.sum(DailyStat.reactions_given), 0),
            func.count(func.distinct(recent_date)),
        )
        .where(DailyStat.guild_id == guild_id)
        .group_by(DailyStat.user_id)
    )
    rows = (await session.execute(stmt)).all()

    scored: list[tuple[str, LevelLeaderboardEntry]] = []
    for (
        user_id,
        msgs,
        voice_secs,
        rrx,
        rgx,
        active_days_recent,
    ) in rows:
        rate = min(1.0, int(active_days_recent) / ACTIVITY_RATE_WINDOW_DAYS)
        levels = compute_user_levels_from_counts(
            messages=int(msgs),
            voice_seconds=int(voice_secs),
            reactions_received=int(rrx),
            reactions_given=int(rgx),
            activity_rate=rate,
        )
        breakdown = getattr(levels, axis)
        scored.append(
            (
                user_id,
                LevelLeaderboardEntry(
                    user_id=user_id,
                    display_name=user_id,  # 後で meta で上書き
                    avatar_url=None,
                    level=breakdown.level,
                    xp=breakdown.xp,
                    activity_rate=rate,
                ),
            )
        )

    # level 降順、同点は xp 降順、さらに user_id で安定ソート
    scored.sort(key=lambda kv: (kv[1].level, kv[1].xp, kv[0]), reverse=True)
    page = scored[offset : offset + limit]
    meta_map = await get_user_meta_map(session, [uid for uid, _ in page])
    return [
        LevelLeaderboardEntry(
            user_id=entry.user_id,
            display_name=(
                meta_map[uid].display_name if uid in meta_map else entry.user_id
            ),
            avatar_url=meta_map[uid].avatar_url if uid in meta_map else None,
            level=entry.level,
            xp=entry.xp,
            activity_rate=entry.activity_rate,
        )
        for uid, entry in page
    ]


async def get_recent_activity_rate(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    window_days: int = ACTIVITY_RATE_WINDOW_DAYS,
) -> float:
    """最近 ``window_days`` 日のうち活動が記録された日の割合 (0.0-1.0)。

    レベル算出時に XP の掛け率として使う。記録が無いユーザーは 0.0。
    """
    start, end = date_window(window_days)
    stmt = select(func.count(func.distinct(DailyStat.stat_date))).where(
        and_(
            DailyStat.guild_id == guild_id,
            DailyStat.user_id == user_id,
            DailyStat.stat_date >= start,
            DailyStat.stat_date <= end,
        )
    )
    active_days = int((await session.execute(stmt)).scalar_one() or 0)
    return min(1.0, active_days / window_days)


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
