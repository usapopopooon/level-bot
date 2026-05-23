"""Server-level read-side aggregations: summary + daily series.

書き込み (``tracking``) → 読み出し (この feature / ``ranking`` / ``user_profile``) の
分離。``daily_stats`` の合計と進行中ボイス live delta をマージしたものを返す。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.database.models import (
    DailyStat,
    ExcludedUser,
    Guild,
    SocialEdgeDaily,
    UserMeta,
)
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


@dataclass
class SocialGraphNode:
    user_id: str
    display_name: str
    avatar_url: str | None
    weight: float
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


@dataclass
class SocialGraphEdge:
    source_user_id: str
    target_user_id: str
    weight: float
    voice_seconds: int
    voice_sessions: int
    replies: int
    reactions: int
    co_activity: float


@dataclass
class SocialGraph:
    guild_id: str
    nodes: list[SocialGraphNode]
    edges: list[SocialGraphEdge]


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


def _edge_weight(
    *,
    voice_seconds: int,
    voice_sessions: int,
    replies: int,
    reactions: int,
    co_activity: float = 0.0,
) -> float:
    return (
        voice_seconds / 600.0
        + voice_sessions * 1.5
        + replies * 3.0
        + reactions * 1.0
        + co_activity * 0.8
    )


def _activity_weight(
    *,
    message_count: int,
    voice_seconds: int,
    reactions_received: int,
    reactions_given: int,
) -> float:
    return (
        message_count * 0.45
        + voice_seconds / 1200.0
        + reactions_received * 1.4
        + reactions_given * 0.9
    )


def _display_pair(user_a: str, user_b: str) -> tuple[str, str]:
    return (user_a, user_b) if user_a < user_b else (user_b, user_a)


async def get_social_graph(
    session: AsyncSession,
    guild_id: str,
    *,
    days: int = 30,
    limit: int = 80,
) -> SocialGraph:
    """直近 N 日のユーザー間交流 graph を返す。"""
    start, end = date_window(days)
    excluded = (
        select(ExcludedUser.user_id)
        .where(ExcludedUser.guild_id == guild_id)
        .scalar_subquery()
    )

    edge_stmt = (
        select(
            SocialEdgeDaily.source_user_id,
            SocialEdgeDaily.target_user_id,
            func.coalesce(func.sum(SocialEdgeDaily.voice_seconds), 0).label(
                "voice_seconds"
            ),
            func.coalesce(func.sum(SocialEdgeDaily.voice_sessions), 0).label(
                "voice_sessions"
            ),
            func.coalesce(func.sum(SocialEdgeDaily.replies), 0).label("replies"),
            func.coalesce(func.sum(SocialEdgeDaily.reactions), 0).label("reactions"),
        )
        .where(
            and_(
                SocialEdgeDaily.guild_id == guild_id,
                SocialEdgeDaily.stat_date >= start,
                SocialEdgeDaily.stat_date <= end,
                SocialEdgeDaily.source_user_id.not_in(excluded),
                SocialEdgeDaily.target_user_id.not_in(excluded),
            )
        )
        .group_by(SocialEdgeDaily.source_user_id, SocialEdgeDaily.target_user_id)
    )
    edge_metrics: dict[tuple[str, str], dict[str, float]] = {}
    for edge_row in (await session.execute(edge_stmt)).all():
        source_user_id, target_user_id = _display_pair(
            edge_row.source_user_id,
            edge_row.target_user_id,
        )
        metrics = edge_metrics.setdefault(
            (source_user_id, target_user_id),
            {
                "voice_seconds": 0.0,
                "voice_sessions": 0.0,
                "replies": 0.0,
                "reactions": 0.0,
                "co_activity": 0.0,
            },
        )
        metrics["voice_seconds"] += int(edge_row.voice_seconds or 0)
        metrics["voice_sessions"] += int(edge_row.voice_sessions or 0)
        metrics["replies"] += int(edge_row.replies or 0)
        metrics["reactions"] += int(edge_row.reactions or 0)

    co_activity_stmt = (
        select(
            DailyStat.stat_date,
            DailyStat.channel_id,
            DailyStat.user_id,
            func.coalesce(func.sum(DailyStat.message_count), 0).label("message_count"),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0).label("voice_seconds"),
            func.coalesce(func.sum(DailyStat.reactions_received), 0).label(
                "reactions_received"
            ),
            func.coalesce(func.sum(DailyStat.reactions_given), 0).label(
                "reactions_given"
            ),
        )
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
                DailyStat.user_id.not_in(excluded),
            )
        )
        .group_by(DailyStat.stat_date, DailyStat.channel_id, DailyStat.user_id)
    )
    users_by_bucket: dict[tuple[date, str], list[tuple[str, float]]] = {}
    for row in (await session.execute(co_activity_stmt)).all():
        local_weight = _activity_weight(
            message_count=int(row.message_count or 0),
            voice_seconds=int(row.voice_seconds or 0),
            reactions_received=int(row.reactions_received or 0),
            reactions_given=int(row.reactions_given or 0),
        )
        if local_weight <= 0:
            continue
        users_by_bucket.setdefault((row.stat_date, row.channel_id), []).append(
            (row.user_id, local_weight)
        )

    for users in users_by_bucket.values():
        active = sorted(users, key=lambda item: item[1], reverse=True)[:24]
        for idx, (user_a, weight_a) in enumerate(active):
            for user_b, weight_b in active[idx + 1 :]:
                source_user_id, target_user_id = _display_pair(user_a, user_b)
                metrics = edge_metrics.setdefault(
                    (source_user_id, target_user_id),
                    {
                        "voice_seconds": 0.0,
                        "voice_sessions": 0.0,
                        "replies": 0.0,
                        "reactions": 0.0,
                        "co_activity": 0.0,
                    },
                )
                metrics["co_activity"] += min(weight_a, weight_b)

    edge_rows = []
    for (source_user_id, target_user_id), metrics in edge_metrics.items():
        voice_seconds = int(metrics["voice_seconds"])
        voice_sessions = int(metrics["voice_sessions"])
        replies = int(metrics["replies"])
        reactions = int(metrics["reactions"])
        co_activity = float(metrics["co_activity"])
        weight = _edge_weight(
            voice_seconds=voice_seconds,
            voice_sessions=voice_sessions,
            replies=replies,
            reactions=reactions,
            co_activity=co_activity,
        )
        if weight <= 0:
            continue
        edge_rows.append(
            SocialGraphEdge(
                source_user_id=source_user_id,
                target_user_id=target_user_id,
                weight=weight,
                voice_seconds=voice_seconds,
                voice_sessions=voice_sessions,
                replies=replies,
                reactions=reactions,
                co_activity=co_activity,
            )
        )

    edges = sorted(edge_rows, key=lambda edge: edge.weight, reverse=True)[:limit]
    user_ids = {edge.source_user_id for edge in edges} | {
        edge.target_user_id for edge in edges
    }

    activity_stmt = (
        select(
            DailyStat.user_id,
            func.coalesce(func.sum(DailyStat.message_count), 0).label("message_count"),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0).label("voice_seconds"),
            func.coalesce(func.sum(DailyStat.reactions_received), 0).label(
                "reactions_received"
            ),
            func.coalesce(func.sum(DailyStat.reactions_given), 0).label(
                "reactions_given"
            ),
        )
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
                DailyStat.user_id.not_in(excluded),
            )
        )
        .group_by(DailyStat.user_id)
    )
    activity_rows = {}
    for activity_row in (await session.execute(activity_stmt)).all():
        message_count = int(activity_row.message_count or 0)
        voice_seconds = int(activity_row.voice_seconds or 0)
        reactions_received = int(activity_row.reactions_received or 0)
        reactions_given = int(activity_row.reactions_given or 0)
        weight = _activity_weight(
            message_count=message_count,
            voice_seconds=voice_seconds,
            reactions_received=reactions_received,
            reactions_given=reactions_given,
        )
        activity_rows[activity_row.user_id] = {
            "message_count": message_count,
            "voice_seconds": voice_seconds,
            "reactions_received": reactions_received,
            "reactions_given": reactions_given,
            "weight": weight,
        }

    top_active_ids = [
        user_id
        for user_id, _metrics in sorted(
            activity_rows.items(),
            key=lambda item: item[1]["weight"],
            reverse=True,
        )[:limit]
    ]
    user_ids.update(top_active_ids)
    if not user_ids:
        return SocialGraph(guild_id=guild_id, nodes=[], edges=[])

    source_meta = aliased(UserMeta)
    meta_stmt = select(source_meta).where(source_meta.user_id.in_(user_ids))
    meta_by_user = {
        row.user_id: row for row in (await session.execute(meta_stmt)).scalars().all()
    }

    node_weights = {
        user_id: float(activity_rows.get(user_id, {}).get("weight", 0.0))
        for user_id in user_ids
    }
    for edge in edges:
        node_weights[edge.source_user_id] += edge.weight
        node_weights[edge.target_user_id] += edge.weight

    nodes = [
        SocialGraphNode(
            user_id=user_id,
            display_name=(
                meta_by_user[user_id].display_name
                if user_id in meta_by_user and meta_by_user[user_id].display_name
                else user_id
            ),
            avatar_url=meta_by_user[user_id].avatar_url
            if user_id in meta_by_user
            else None,
            weight=weight,
            message_count=int(activity_rows.get(user_id, {}).get("message_count", 0)),
            voice_seconds=int(activity_rows.get(user_id, {}).get("voice_seconds", 0)),
            reactions_received=int(
                activity_rows.get(user_id, {}).get("reactions_received", 0)
            ),
            reactions_given=int(
                activity_rows.get(user_id, {}).get("reactions_given", 0)
            ),
        )
        for user_id, weight in sorted(
            node_weights.items(), key=lambda item: item[1], reverse=True
        )[:limit]
    ]
    kept_user_ids = {node.user_id for node in nodes}
    edges = [
        edge
        for edge in edges
        if edge.source_user_id in kept_user_ids and edge.target_user_id in kept_user_ids
    ]

    return SocialGraph(guild_id=guild_id, nodes=nodes, edges=edges)
