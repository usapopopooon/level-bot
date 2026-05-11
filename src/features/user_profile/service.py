"""User-level read aggregations: profile + lifetime stats.

``UserProfile`` は Web のユーザーページ用、``UserLifetimeStats`` はレベル
算出のための累積データ。両方とも進行中ボイスを live delta としてマージする。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat
from src.features.guilds.service import is_user_excluded
from src.features.meta.service import get_channel_meta_map, get_user_meta_map
from src.features.stats.service import DailyPoint
from src.features.tracking.service import live_voice_deltas
from src.utils import date_window, today_local

# =============================================================================
# Public dataclasses
# =============================================================================


@dataclass
class TopChannelEntry:
    """プロフィール内の「主な発言チャンネル」エントリ。

    ``ranking.ChannelLeaderboardEntry`` と同型だが、ranking feature に依存
    しないようプロフィール側で独自に定義する (ranking を捨てても user_profile
    が壊れないようにするため)。
    """

    channel_id: str
    name: str
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


@dataclass
class UserProfile:
    user_id: str
    display_name: str
    avatar_url: str | None
    total_messages: int
    total_voice_seconds: int
    total_reactions_received: int
    total_reactions_given: int
    rank_messages: int | None
    rank_voice: int | None
    rank_reactions_received: int | None
    rank_reactions_given: int | None
    daily: list[DailyPoint]
    top_channels: list[TopChannelEntry]


@dataclass
class UserLifetimeStats:
    """ユーザーの生涯累積。レベル/アクティブ率の素になる。"""

    user_id: str
    display_name: str
    avatar_url: str | None
    total_messages: int
    total_char_count: int
    total_voice_seconds: int
    total_reactions_received: int
    total_reactions_given: int
    first_active_date: date | None
    last_active_date: date | None
    active_days: int  # distinct stat_date 数


# =============================================================================
# get_user_profile
# =============================================================================


async def get_user_profile(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    days: int = 30,
) -> UserProfile | None:
    """ユーザープロフィール用の総合データ。存在しない場合は None。

    表示除外ユーザーは None を返す (画面上は 404 扱い)。
    進行中ボイスセッションは:
    - 当該ユーザーの total_voice / daily / top_channels に加算
    - rank_voice の計算では他ユーザーの live delta も考慮 (順位が公平になる)
    """
    if await is_user_excluded(session, guild_id, user_id):
        return None
    start, end = date_window(days)

    # --- 当該ユーザーの static 合計 ---
    sum_stmt = select(
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
    msgs, voice_static, reacts_recv, reacts_given = (
        await session.execute(sum_stmt)
    ).one()
    total_messages = int(msgs)
    total_voice_static = int(voice_static)
    total_reactions_received = int(reacts_recv)
    total_reactions_given = int(reacts_given)

    # --- 当該ユーザーの live delta ---
    user_deltas = await live_voice_deltas(
        session, guild_id, start_date=start, end_date=end, user_id=user_id
    )
    user_live_voice = sum(d.seconds for d in user_deltas)
    total_voice = total_voice_static + user_live_voice

    if (
        total_messages == 0
        and total_voice == 0
        and total_reactions_received == 0
        and total_reactions_given == 0
    ):
        # static も live delta も無いユーザーは meta が無ければ None
        meta_map = await get_user_meta_map(session, [user_id])
        meta = meta_map.get(user_id)
        if meta is None:
            return None

    # --- 日別シリーズ (static + live by day) ---
    daily_stmt = (
        select(
            DailyStat.stat_date,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
            func.coalesce(func.sum(DailyStat.reactions_received), 0),
            func.coalesce(func.sum(DailyStat.reactions_given), 0),
        )
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.user_id == user_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.stat_date)
        .order_by(DailyStat.stat_date)
    )
    daily_rows = {
        row[0]: (int(row[1]), int(row[2]), int(row[3]), int(row[4]))
        for row in (await session.execute(daily_stmt)).all()
    }
    user_live_by_day: dict[date, int] = {}
    for d in user_deltas:
        user_live_by_day[d.day] = user_live_by_day.get(d.day, 0) + d.seconds
    daily: list[DailyPoint] = []
    cur = start
    while cur <= end:
        m, v, rr, rg = daily_rows.get(cur, (0, 0, 0, 0))
        v += user_live_by_day.get(cur, 0)
        daily.append(
            DailyPoint(
                stat_date=cur,
                message_count=m,
                voice_seconds=v,
                reactions_received=rr,
                reactions_given=rg,
            )
        )
        cur += timedelta(days=1)

    # --- ランク (全ユーザーの static 合計 + live delta マージ) ---
    user_totals_stmt = (
        select(
            DailyStat.user_id,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
            func.coalesce(func.sum(DailyStat.reactions_received), 0),
            func.coalesce(func.sum(DailyStat.reactions_given), 0),
        )
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.user_id)
    )
    user_totals: dict[str, list[int]] = {
        row[0]: [int(row[1]), int(row[2]), int(row[3]), int(row[4])]
        for row in (await session.execute(user_totals_stmt)).all()
    }
    all_deltas = await live_voice_deltas(
        session, guild_id, start_date=start, end_date=end
    )
    for d in all_deltas:
        if d.user_id not in user_totals:
            user_totals[d.user_id] = [0, 0, 0, 0]
        user_totals[d.user_id][1] += d.seconds

    def _rank_for(metric_idx: int) -> int | None:
        return next(
            (
                i + 1
                for i, (uid, totals) in enumerate(
                    sorted(
                        user_totals.items(),
                        key=lambda kv: kv[1][metric_idx],
                        reverse=True,
                    )
                )
                if uid == user_id and totals[metric_idx] > 0
            ),
            None,
        )

    rank_messages = _rank_for(0)
    rank_voice = _rank_for(1)
    rank_reactions_received = _rank_for(2)
    rank_reactions_given = _rank_for(3)

    # --- トップチャンネル (static + live by channel for this user) ---
    top_ch_stmt = (
        select(
            DailyStat.channel_id,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
            func.coalesce(func.sum(DailyStat.reactions_received), 0),
            func.coalesce(func.sum(DailyStat.reactions_given), 0),
        )
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.user_id == user_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.channel_id)
    )
    ch_totals: dict[str, list[int]] = {
        row[0]: [int(row[1]), int(row[2]), int(row[3]), int(row[4])]
        for row in (await session.execute(top_ch_stmt)).all()
    }
    for d in user_deltas:
        if d.channel_id not in ch_totals:
            ch_totals[d.channel_id] = [0, 0, 0, 0]
        ch_totals[d.channel_id][1] += d.seconds
    sorted_channels = sorted(ch_totals.items(), key=lambda kv: kv[1][0], reverse=True)[
        :5
    ]
    ch_meta_map = await get_channel_meta_map(
        session, guild_id, [cid for cid, _ in sorted_channels]
    )
    top_channels = [
        TopChannelEntry(
            channel_id=cid,
            name=ch_meta_map[cid].name if cid in ch_meta_map else f"#{cid}",
            message_count=m,
            voice_seconds=v,
            reactions_received=rr,
            reactions_given=rg,
        )
        for cid, (m, v, rr, rg) in sorted_channels
    ]

    meta_map = await get_user_meta_map(session, [user_id])
    meta = meta_map.get(user_id)

    return UserProfile(
        user_id=user_id,
        display_name=meta.display_name if meta else user_id,
        avatar_url=meta.avatar_url if meta else None,
        total_messages=total_messages,
        total_voice_seconds=total_voice,
        total_reactions_received=total_reactions_received,
        total_reactions_given=total_reactions_given,
        rank_messages=rank_messages,
        rank_voice=rank_voice,
        rank_reactions_received=rank_reactions_received,
        rank_reactions_given=rank_reactions_given,
        daily=daily,
        top_channels=top_channels,
    )


# =============================================================================
# get_user_lifetime_stats (ユーザーレベル算出の素データ)
# =============================================================================


async def get_user_lifetime_stats(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
) -> UserLifetimeStats | None:
    """ユーザーのギルド内累積活動を返す (進行中ボイスも含む)。

    表示除外ユーザーは None を返す (レベル/プロフィール双方で隠す)。

    レベル算出例 (呼び出し側で実装):
        xp = total_messages + total_voice_seconds // 60
        # アクティブ日基準のレート (例: 加入後 N 日 / 実アクティブ N 日)
        msg_per_active_day = total_messages / max(active_days, 1)
        # レベル式は自由 (sqrt(xp / 100) など)
    """
    if await is_user_excluded(session, guild_id, user_id):
        return None
    stmt = select(
        func.coalesce(func.sum(DailyStat.message_count), 0),
        func.coalesce(func.sum(DailyStat.char_count), 0),
        func.coalesce(func.sum(DailyStat.voice_seconds), 0),
        func.coalesce(func.sum(DailyStat.reactions_received), 0),
        func.coalesce(func.sum(DailyStat.reactions_given), 0),
        func.min(DailyStat.stat_date),
        func.max(DailyStat.stat_date),
        func.count(func.distinct(DailyStat.stat_date)),
    ).where(
        and_(
            DailyStat.guild_id == guild_id,
            DailyStat.user_id == user_id,
        )
    )
    (
        msgs,
        chars,
        voice_static,
        reacts_recv,
        reacts_given,
        first,
        last,
        active_days,
    ) = (await session.execute(stmt)).one()

    # 進行中ボイスも累積に含める
    deltas = await live_voice_deltas(
        session,
        guild_id,
        start_date=None,
        end_date=today_local(),
        user_id=user_id,
    )
    voice_live = sum(d.seconds for d in deltas)
    total_voice = int(voice_static) + voice_live

    # 完全に活動が無いユーザーは None (meta も無ければ存在しないユーザー扱い)
    meta_map = await get_user_meta_map(session, [user_id])
    meta = meta_map.get(user_id)
    if (
        int(msgs) == 0
        and total_voice == 0
        and int(reacts_recv) == 0
        and int(reacts_given) == 0
        and meta is None
    ):
        return None

    # live delta があり static には無い場合、first/last_active_date は live 日に伸ばす
    if deltas and active_days == 0:
        live_days = sorted({d.day for d in deltas})
        first = first or live_days[0]
        last = last or live_days[-1]
        active_days = len(live_days)

    return UserLifetimeStats(
        user_id=user_id,
        display_name=meta.display_name if meta else user_id,
        avatar_url=meta.avatar_url if meta else None,
        total_messages=int(msgs),
        total_char_count=int(chars),
        total_voice_seconds=total_voice,
        total_reactions_received=int(reacts_recv),
        total_reactions_given=int(reacts_given),
        first_active_date=first,
        last_active_date=last,
        active_days=int(active_days),
    )
