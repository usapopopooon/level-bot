"""User / channel leaderboard aggregations.

書き込み (``tracking``) と display meta (``meta``) を取りまとめて、
metric 別 (messages | voice) のランキングを返す。``offset`` でページング可。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat
from src.features.meta.service import get_channel_meta_map, get_user_meta_map
from src.features.tracking.service import live_voice_deltas
from src.utils import date_window

# =============================================================================
# Public dataclasses
# =============================================================================


@dataclass
class LeaderboardEntry:
    user_id: str
    display_name: str
    avatar_url: str | None
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


@dataclass
class ChannelLeaderboardEntry:
    channel_id: str
    name: str
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


# metric -> ソートに使う user_totals / ch_totals のインデックス
# [0]=messages, [1]=voice, [2]=reactions_received, [3]=reactions_given
_METRIC_INDEX: dict[str, int] = {
    "messages": 0,
    "voice": 1,
    "reactions_received": 2,
    "reactions_given": 3,
}


# =============================================================================
# Leaderboards
# =============================================================================


async def get_user_leaderboard(
    session: AsyncSession,
    guild_id: str,
    *,
    days: int = 30,
    limit: int = 10,
    offset: int = 0,
    metric: str = "messages",
) -> list[LeaderboardEntry]:
    """ユーザーのリーダーボード。

    ``metric`` は ``messages`` | ``voice`` | ``reactions_received`` |
    ``reactions_given``。進行中ボイスセッション分も voice_seconds に加算した上で
    並び替える (live delta だけしかないユーザーも順位に乗る)。
    """
    start, end = date_window(days)

    # static — LIMIT は live delta merge 後に Python 側で適用するためここでは外す
    static_stmt = (
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
    static_rows = (await session.execute(static_stmt)).all()
    user_totals: dict[str, list[int]] = {
        row[0]: [int(row[1]), int(row[2]), int(row[3]), int(row[4])]
        for row in static_rows
    }

    # live deltas (voice のみ。他カラムは event handler で daily_stats に入っている)
    deltas = await live_voice_deltas(session, guild_id, start_date=start, end_date=end)
    for d in deltas:
        if d.user_id not in user_totals:
            user_totals[d.user_id] = [0, 0, 0, 0]
        user_totals[d.user_id][1] += d.seconds

    # sort + offset/limit
    key_idx = _METRIC_INDEX.get(metric, 0)
    sorted_users = sorted(
        user_totals.items(), key=lambda kv: kv[1][key_idx], reverse=True
    )[offset : offset + limit]

    user_ids = [uid for uid, _ in sorted_users]
    meta_map = await get_user_meta_map(session, user_ids)

    entries: list[LeaderboardEntry] = []
    for user_id, (msgs, voice, recv, given) in sorted_users:
        meta = meta_map.get(user_id)
        entries.append(
            LeaderboardEntry(
                user_id=user_id,
                display_name=meta.display_name if meta else user_id,
                avatar_url=meta.avatar_url if meta else None,
                message_count=msgs,
                voice_seconds=voice,
                reactions_received=recv,
                reactions_given=given,
            )
        )
    return entries


async def get_channel_leaderboard(
    session: AsyncSession,
    guild_id: str,
    *,
    days: int = 30,
    limit: int = 10,
    offset: int = 0,
    metric: str = "messages",
) -> list[ChannelLeaderboardEntry]:
    """チャンネル別リーダーボード。

    ``metric`` は ``messages`` | ``voice`` | ``reactions_received`` |
    ``reactions_given``。進行中ボイスも voice_seconds に加算する。
    """
    start, end = date_window(days)

    static_stmt = (
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
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.channel_id)
    )
    static_rows = (await session.execute(static_stmt)).all()
    ch_totals: dict[str, list[int]] = {
        row[0]: [int(row[1]), int(row[2]), int(row[3]), int(row[4])]
        for row in static_rows
    }

    deltas = await live_voice_deltas(session, guild_id, start_date=start, end_date=end)
    for d in deltas:
        if d.channel_id not in ch_totals:
            ch_totals[d.channel_id] = [0, 0, 0, 0]
        ch_totals[d.channel_id][1] += d.seconds

    key_idx = _METRIC_INDEX.get(metric, 0)
    sorted_channels = sorted(
        ch_totals.items(), key=lambda kv: kv[1][key_idx], reverse=True
    )[offset : offset + limit]

    channel_ids = [cid for cid, _ in sorted_channels]
    meta_map = await get_channel_meta_map(session, guild_id, channel_ids)

    entries: list[ChannelLeaderboardEntry] = []
    for channel_id, (msgs, voice, recv, given) in sorted_channels:
        meta = meta_map.get(channel_id)
        entries.append(
            ChannelLeaderboardEntry(
                channel_id=channel_id,
                name=meta.name if meta else f"#{channel_id}",
                message_count=msgs,
                voice_seconds=voice,
                reactions_received=recv,
                reactions_given=given,
            )
        )
    return entries
