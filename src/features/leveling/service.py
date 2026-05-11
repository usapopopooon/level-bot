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

レベルは純粋累積。期間によるアクティブ率減衰は行わない (一度上げたら下がらない)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, ExcludedUser
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
) -> UserLevels:
    """4 指標の生カウントからレベルを算出する。

    各 axis を先に丸めて整数化し、総合 XP はそれら整数の合計とする。
    こうしないと axis 別丸め誤差で ``total.xp != sum(axes.xp)`` が起きる。
    """
    voice_xp = round(voice_seconds / 60.0 * XP_PER_VOICE_MINUTE)
    text_xp = round(messages * XP_PER_MESSAGE)
    rrx = round(reactions_received * XP_PER_REACTION_RECEIVED)
    rgx = round(reactions_given * XP_PER_REACTION_GIVEN)
    total_xp = voice_xp + text_xp + rrx + rgx
    return UserLevels(
        total=_breakdown_from_xp(total_xp),
        voice=_breakdown_from_xp(voice_xp),
        text=_breakdown_from_xp(text_xp),
        reactions_received=_breakdown_from_xp(rrx),
        reactions_given=_breakdown_from_xp(rgx),
    )


def compute_user_levels(stats: UserLifetimeStats) -> UserLevels:
    """``UserLifetimeStats`` (lifetime 累積) からレベルを算出する。"""
    return compute_user_levels_from_counts(
        messages=stats.total_messages,
        voice_seconds=stats.total_voice_seconds,
        reactions_received=stats.total_reactions_received,
        reactions_given=stats.total_reactions_given,
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

    msg_sum = func.coalesce(func.sum(DailyStat.message_count), 0)
    voice_sum = func.coalesce(func.sum(DailyStat.voice_seconds), 0)
    rrx_sum = func.coalesce(func.sum(DailyStat.reactions_received), 0)
    rgx_sum = func.coalesce(func.sum(DailyStat.reactions_given), 0)

    # axis 別の ORDER BY 式。total は重み付き合計 (近似 XP)
    order_expr: Any
    if axis == "total":
        order_expr = (
            msg_sum * XP_PER_MESSAGE
            + voice_sum / 60.0 * XP_PER_VOICE_MINUTE
            + rrx_sum * XP_PER_REACTION_RECEIVED
            + rgx_sum * XP_PER_REACTION_GIVEN
        )
    elif axis == "voice":
        order_expr = voice_sum
    elif axis == "text":
        order_expr = msg_sum
    elif axis == "reactions_received":
        order_expr = rrx_sum
    else:  # reactions_given
        order_expr = rgx_sum

    excluded_subq = (
        select(ExcludedUser.user_id)
        .where(ExcludedUser.guild_id == guild_id)
        .scalar_subquery()
    )

    stmt = (
        select(
            DailyStat.user_id,
            msg_sum,
            voice_sum,
            rrx_sum,
            rgx_sum,
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
    for user_id, msgs, voice_secs, rrx, rgx in rows:
        levels = compute_user_levels_from_counts(
            messages=int(msgs),
            voice_seconds=int(voice_secs),
            reactions_received=int(rrx),
            reactions_given=int(rgx),
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
