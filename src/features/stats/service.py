"""Server-level read-side aggregations: summary + daily series.

書き込み (``tracking``) → 読み出し (この feature / ``ranking`` / ``user_profile``) の
分離。``daily_stats`` の合計と進行中ボイス live delta をマージしたものを返す。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, Guild
from src.features.tracking.service import live_voice_deltas
from src.utils import date_window

# =============================================================================
# Public dataclasses
# =============================================================================


@dataclass
class GuildSummary:
    guild_id: str
    name: str
    icon_url: str | None
    total_messages: int
    total_voice_seconds: int
    total_reactions_received: int
    total_reactions_given: int
    active_users: int


@dataclass
class DailyPoint:
    stat_date: date
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


# =============================================================================
# Aggregations
# =============================================================================


async def get_guild_summary(
    session: AsyncSession, guild_id: str, *, days: int = 30
) -> GuildSummary | None:
    """ギルドの直近 N 日サマリ (合計メッセージ数・ボイス時間・ユニークユーザー)。

    進行中ボイスセッションも live delta として集計に含む。
    """
    guild_stmt = select(Guild).where(Guild.guild_id == guild_id)
    guild_result = await session.execute(guild_stmt)
    guild = guild_result.scalar_one_or_none()
    if guild is None:
        return None

    start, end = date_window(days)

    # static (daily_stats)
    agg_stmt = select(
        func.coalesce(func.sum(DailyStat.message_count), 0),
        func.coalesce(func.sum(DailyStat.voice_seconds), 0),
        func.coalesce(func.sum(DailyStat.reactions_received), 0),
        func.coalesce(func.sum(DailyStat.reactions_given), 0),
    ).where(
        and_(
            DailyStat.guild_id == guild_id,
            DailyStat.stat_date >= start,
            DailyStat.stat_date <= end,
        )
    )
    msgs, voice_static, reacts_recv, reacts_given = (
        await session.execute(agg_stmt)
    ).one()

    users_stmt = select(func.distinct(DailyStat.user_id)).where(
        and_(
            DailyStat.guild_id == guild_id,
            DailyStat.stat_date >= start,
            DailyStat.stat_date <= end,
        )
    )
    users_static = {row[0] for row in (await session.execute(users_stmt)).all()}

    # live deltas
    deltas = await live_voice_deltas(session, guild_id, start_date=start, end_date=end)
    voice_live = sum(d.seconds for d in deltas)
    users_live = {d.user_id for d in deltas}

    return GuildSummary(
        guild_id=guild.guild_id,
        name=guild.name,
        icon_url=guild.icon_url,
        total_messages=int(msgs),
        total_voice_seconds=int(voice_static) + voice_live,
        total_reactions_received=int(reacts_recv),
        total_reactions_given=int(reacts_given),
        active_users=len(users_static | users_live),
    )


async def get_daily_series(
    session: AsyncSession, guild_id: str, *, days: int = 30
) -> list[DailyPoint]:
    """日別集計 (チャート表示用)。データの無い日は 0 で埋めて返す。

    進行中ボイスセッションは JST 日付境界で分割した上で、該当日に加算する。
    """
    start, end = date_window(days)
    stmt = (
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
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.stat_date)
        .order_by(DailyStat.stat_date)
    )
    result = await session.execute(stmt)
    rows = {
        row[0]: (int(row[1]), int(row[2]), int(row[3]), int(row[4]))
        for row in result.all()
    }

    deltas = await live_voice_deltas(session, guild_id, start_date=start, end_date=end)
    live_by_day: dict[date, int] = {}
    for d in deltas:
        live_by_day[d.day] = live_by_day.get(d.day, 0) + d.seconds

    points: list[DailyPoint] = []
    cur = start
    while cur <= end:
        msgs, voice, recv, given = rows.get(cur, (0, 0, 0, 0))
        voice += live_by_day.get(cur, 0)
        points.append(
            DailyPoint(
                stat_date=cur,
                message_count=msgs,
                voice_seconds=voice,
                reactions_received=recv,
                reactions_given=given,
            )
        )
        cur += timedelta(days=1)
    return points
