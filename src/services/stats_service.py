"""Stats service: CRUD + aggregation helpers for level-bot.

このモジュールは Bot からの集計書き込みと、Web ダッシュボードからの
読み出しの両方を提供する。書き込みは PostgreSQL の ON CONFLICT を使った
upsert で衝突に強い構造にしている。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.constants import MAX_VOICE_SESSION_SECONDS
from src.database.models import (
    ChannelMeta,
    DailyStat,
    ExcludedChannel,
    Guild,
    GuildSettings,
    UserMeta,
    VoiceSession,
)
from src.utils import today_local

# =============================================================================
# Guild / Settings
# =============================================================================


async def upsert_guild(
    session: AsyncSession,
    *,
    guild_id: str,
    name: str,
    icon_url: str | None,
    member_count: int,
) -> Guild:
    """Guild レコードを upsert する。Bot 起動時 / guild_join / guild_update で呼ぶ。"""
    stmt = select(Guild).where(Guild.guild_id == guild_id)
    result = await session.execute(stmt)
    guild = result.scalar_one_or_none()

    if guild is None:
        guild = Guild(
            guild_id=guild_id,
            name=name,
            icon_url=icon_url,
            member_count=member_count,
            is_active=True,
        )
        session.add(guild)
        await session.flush()
        # デフォルト設定も作成
        session.add(GuildSettings(guild_pk=guild.id))
    else:
        guild.name = name
        guild.icon_url = icon_url
        guild.member_count = member_count
        guild.is_active = True

    await session.commit()
    return guild


async def mark_guild_inactive(session: AsyncSession, guild_id: str) -> None:
    """Bot が kick された / guild_remove イベント時に呼ぶ。"""
    stmt = select(Guild).where(Guild.guild_id == guild_id)
    result = await session.execute(stmt)
    guild = result.scalar_one_or_none()
    if guild:
        guild.is_active = False
        await session.commit()


async def get_guild_settings(
    session: AsyncSession, guild_id: str
) -> GuildSettings | None:
    """ギルド設定を取得する (Guild の上書きされたデフォルト)。"""
    stmt = (
        select(GuildSettings)
        .join(Guild, GuildSettings.guild_pk == Guild.id)
        .where(Guild.guild_id == guild_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_active_guilds(session: AsyncSession) -> list[Guild]:
    """アクティブなギルド一覧 (Web トップページ用)。

    ``settings`` を eager-load しておかないと、async session で
    relationship アクセス時に MissingGreenlet エラーになる。
    """
    stmt = (
        select(Guild)
        .where(Guild.is_active.is_(True))
        .options(selectinload(Guild.settings))
        .order_by(Guild.name)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# =============================================================================
# Excluded channels
# =============================================================================


async def is_channel_excluded(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    stmt = select(ExcludedChannel.id).where(
        and_(
            ExcludedChannel.guild_id == guild_id,
            ExcludedChannel.channel_id == channel_id,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def add_excluded_channel(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    """除外リストに追加する。既に存在すれば False。"""
    if await is_channel_excluded(session, guild_id, channel_id):
        return False
    session.add(ExcludedChannel(guild_id=guild_id, channel_id=channel_id))
    await session.commit()
    return True


async def remove_excluded_channel(
    session: AsyncSession, guild_id: str, channel_id: str
) -> bool:
    stmt = delete(ExcludedChannel).where(
        and_(
            ExcludedChannel.guild_id == guild_id,
            ExcludedChannel.channel_id == channel_id,
        )
    )
    # DML の execute は CursorResult を返すが、typed stub では Result[Any] のため明示
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return (result.rowcount or 0) > 0


async def list_excluded_channels(session: AsyncSession, guild_id: str) -> list[str]:
    stmt = select(ExcludedChannel.channel_id).where(
        ExcludedChannel.guild_id == guild_id
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


# =============================================================================
# Daily stats writes (upsert)
# =============================================================================


async def increment_message_stat(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    channel_id: str,
    stat_date: date,
    char_count: int,
    attachment_count: int,
) -> None:
    """メッセージイベントを 1 件 daily_stats に加算する。"""
    stmt = pg_insert(DailyStat).values(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        message_count=1,
        char_count=char_count,
        attachment_count=attachment_count,
        voice_seconds=0,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_stat",
        set_={
            "message_count": DailyStat.message_count + 1,
            "char_count": DailyStat.char_count + char_count,
            "attachment_count": DailyStat.attachment_count + attachment_count,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def add_voice_seconds(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    channel_id: str,
    stat_date: date,
    seconds: int,
) -> None:
    """ボイス時間を daily_stats に加算する (秒)。"""
    if seconds <= 0:
        return
    seconds = min(seconds, MAX_VOICE_SESSION_SECONDS)

    stmt = pg_insert(DailyStat).values(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        message_count=0,
        char_count=0,
        attachment_count=0,
        voice_seconds=seconds,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_stat",
        set_={
            "voice_seconds": DailyStat.voice_seconds + seconds,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


# =============================================================================
# Voice sessions (active)
# =============================================================================


async def start_voice_session(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    channel_id: str,
    self_muted: bool = False,
    self_deafened: bool = False,
) -> VoiceSession:
    """新しいボイスセッションを開始する。既存があれば置き換える。"""
    await session.execute(
        delete(VoiceSession).where(
            and_(
                VoiceSession.guild_id == guild_id,
                VoiceSession.user_id == user_id,
            )
        )
    )
    voice = VoiceSession(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        self_muted=self_muted,
        self_deafened=self_deafened,
    )
    session.add(voice)
    await session.commit()
    return voice


async def end_voice_session(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> VoiceSession | None:
    """進行中セッションを取り出して削除する。退室時集計用。"""
    stmt = select(VoiceSession).where(
        and_(
            VoiceSession.guild_id == guild_id,
            VoiceSession.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    voice = result.scalar_one_or_none()
    if voice is None:
        return None
    await session.delete(voice)
    await session.commit()
    return voice


async def list_active_voice_sessions(
    session: AsyncSession,
) -> list[VoiceSession]:
    """全進行中セッションを返す。Bot 再起動時の引き継ぎに使う。"""
    result = await session.execute(select(VoiceSession))
    return list(result.scalars().all())


async def purge_all_voice_sessions(session: AsyncSession) -> int:
    """全ボイスセッションを削除する (Bot 再起動時のリセット用)。

    Returns:
        削除件数。
    """
    result = cast("CursorResult[Any]", await session.execute(delete(VoiceSession)))
    await session.commit()
    return result.rowcount or 0


# =============================================================================
# Meta caches
# =============================================================================


async def upsert_user_meta(
    session: AsyncSession,
    *,
    user_id: str,
    display_name: str,
    avatar_url: str | None,
    is_bot: bool,
) -> None:
    stmt = pg_insert(UserMeta).values(
        user_id=user_id,
        display_name=display_name,
        avatar_url=avatar_url,
        is_bot=is_bot,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserMeta.user_id],
        set_={
            "display_name": display_name,
            "avatar_url": avatar_url,
            "is_bot": is_bot,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def upsert_channel_meta(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    name: str,
    channel_type: str,
) -> None:
    stmt = pg_insert(ChannelMeta).values(
        guild_id=guild_id,
        channel_id=channel_id,
        name=name,
        channel_type=channel_type,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_channel_meta",
        set_={
            "name": name,
            "channel_type": channel_type,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def get_user_meta_map(
    session: AsyncSession, user_ids: Iterable[str]
) -> dict[str, UserMeta]:
    ids = list(set(user_ids))
    if not ids:
        return {}
    stmt = select(UserMeta).where(UserMeta.user_id.in_(ids))
    result = await session.execute(stmt)
    return {meta.user_id: meta for meta in result.scalars().all()}


async def get_channel_meta_map(
    session: AsyncSession, guild_id: str, channel_ids: Iterable[str]
) -> dict[str, ChannelMeta]:
    ids = list(set(channel_ids))
    if not ids:
        return {}
    stmt = select(ChannelMeta).where(
        and_(
            ChannelMeta.guild_id == guild_id,
            ChannelMeta.channel_id.in_(ids),
        )
    )
    result = await session.execute(stmt)
    return {meta.channel_id: meta for meta in result.scalars().all()}


# =============================================================================
# Aggregations (read-side, Web 用)
# =============================================================================


@dataclass
class GuildSummary:
    guild_id: str
    name: str
    icon_url: str | None
    total_messages: int
    total_voice_seconds: int
    active_users: int


@dataclass
class DailyPoint:
    stat_date: date
    message_count: int
    voice_seconds: int


@dataclass
class LeaderboardEntry:
    user_id: str
    display_name: str
    avatar_url: str | None
    message_count: int
    voice_seconds: int


@dataclass
class ChannelLeaderboardEntry:
    channel_id: str
    name: str
    message_count: int
    voice_seconds: int


def _date_window(days: int) -> tuple[date, date]:
    """``[today - (days-1), today]`` の閉区間を返す (Bot 設定 TZ 基準)。

    書き込み側 (cogs/stats.py の ``today_local()``) と一致させるため、
    UTC ではなく ``settings.timezone_offset`` を反映した日付を使う。
    """
    today = today_local()
    start = today - timedelta(days=max(days - 1, 0))
    return start, today


async def get_guild_summary(
    session: AsyncSession, guild_id: str, *, days: int = 30
) -> GuildSummary | None:
    """ギルドの直近 N 日サマリ (合計メッセージ数・ボイス時間・ユニークユーザー)。"""
    guild_stmt = select(Guild).where(Guild.guild_id == guild_id)
    guild_result = await session.execute(guild_stmt)
    guild = guild_result.scalar_one_or_none()
    if guild is None:
        return None

    start, end = _date_window(days)
    agg_stmt = select(
        func.coalesce(func.sum(DailyStat.message_count), 0),
        func.coalesce(func.sum(DailyStat.voice_seconds), 0),
        func.count(func.distinct(DailyStat.user_id)),
    ).where(
        and_(
            DailyStat.guild_id == guild_id,
            DailyStat.stat_date >= start,
            DailyStat.stat_date <= end,
        )
    )
    msgs, voice, users = (await session.execute(agg_stmt)).one()

    return GuildSummary(
        guild_id=guild.guild_id,
        name=guild.name,
        icon_url=guild.icon_url,
        total_messages=int(msgs),
        total_voice_seconds=int(voice),
        active_users=int(users),
    )


async def get_daily_series(
    session: AsyncSession, guild_id: str, *, days: int = 30
) -> list[DailyPoint]:
    """日別集計 (チャート表示用)。データの無い日は 0 で埋めて返す。"""
    start, end = _date_window(days)
    stmt = (
        select(
            DailyStat.stat_date,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
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
    rows = {row[0]: (int(row[1]), int(row[2])) for row in result.all()}

    points: list[DailyPoint] = []
    cur = start
    while cur <= end:
        msgs, voice = rows.get(cur, (0, 0))
        points.append(
            DailyPoint(stat_date=cur, message_count=msgs, voice_seconds=voice)
        )
        cur += timedelta(days=1)
    return points


async def get_user_leaderboard(
    session: AsyncSession,
    guild_id: str,
    *,
    days: int = 30,
    limit: int = 10,
    metric: str = "messages",
) -> list[LeaderboardEntry]:
    """ユーザーのリーダーボード。``metric`` は messages | voice。"""
    start, end = _date_window(days)
    order_col = (
        func.sum(DailyStat.voice_seconds)
        if metric == "voice"
        else func.sum(DailyStat.message_count)
    )
    stmt = (
        select(
            DailyStat.user_id,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
        )
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.user_id)
        .order_by(order_col.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()

    user_ids = [r[0] for r in rows]
    meta_map = await get_user_meta_map(session, user_ids)

    entries: list[LeaderboardEntry] = []
    for user_id, msgs, voice in rows:
        meta = meta_map.get(user_id)
        entries.append(
            LeaderboardEntry(
                user_id=user_id,
                display_name=meta.display_name if meta else user_id,
                avatar_url=meta.avatar_url if meta else None,
                message_count=int(msgs),
                voice_seconds=int(voice),
            )
        )
    return entries


async def get_channel_leaderboard(
    session: AsyncSession,
    guild_id: str,
    *,
    days: int = 30,
    limit: int = 10,
    metric: str = "messages",
) -> list[ChannelLeaderboardEntry]:
    """チャンネル別リーダーボード。"""
    start, end = _date_window(days)
    order_col = (
        func.sum(DailyStat.voice_seconds)
        if metric == "voice"
        else func.sum(DailyStat.message_count)
    )
    stmt = (
        select(
            DailyStat.channel_id,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
        )
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.channel_id)
        .order_by(order_col.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()

    channel_ids = [r[0] for r in rows]
    meta_map = await get_channel_meta_map(session, guild_id, channel_ids)

    entries: list[ChannelLeaderboardEntry] = []
    for channel_id, msgs, voice in rows:
        meta = meta_map.get(channel_id)
        entries.append(
            ChannelLeaderboardEntry(
                channel_id=channel_id,
                name=meta.name if meta else f"#{channel_id}",
                message_count=int(msgs),
                voice_seconds=int(voice),
            )
        )
    return entries


@dataclass
class UserProfile:
    user_id: str
    display_name: str
    avatar_url: str | None
    total_messages: int
    total_voice_seconds: int
    rank_messages: int | None
    rank_voice: int | None
    daily: list[DailyPoint]
    top_channels: list[ChannelLeaderboardEntry]


async def get_user_profile(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    *,
    days: int = 30,
) -> UserProfile | None:
    """ユーザープロフィール用の総合データ。存在しない場合は None。"""
    start, end = _date_window(days)

    # 合計
    sum_stmt = select(
        func.coalesce(func.sum(DailyStat.message_count), 0),
        func.coalesce(func.sum(DailyStat.voice_seconds), 0),
    ).where(
        and_(
            DailyStat.guild_id == guild_id,
            DailyStat.user_id == user_id,
            DailyStat.stat_date >= start,
            DailyStat.stat_date <= end,
        )
    )
    msgs, voice = (await session.execute(sum_stmt)).one()
    total_messages = int(msgs)
    total_voice = int(voice)

    if total_messages == 0 and total_voice == 0:
        # 集計が無いユーザーは None
        meta_map = await get_user_meta_map(session, [user_id])
        meta = meta_map.get(user_id)
        if meta is None:
            return None

    # 日別シリーズ (このユーザーのみ)
    daily_stmt = (
        select(
            DailyStat.stat_date,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
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
        row[0]: (int(row[1]), int(row[2]))
        for row in (await session.execute(daily_stmt)).all()
    }
    daily: list[DailyPoint] = []
    cur = start
    while cur <= end:
        m, v = daily_rows.get(cur, (0, 0))
        daily.append(DailyPoint(stat_date=cur, message_count=m, voice_seconds=v))
        cur += timedelta(days=1)

    # ランク (メッセージ数で何位か)
    rank_stmt = (
        select(DailyStat.user_id, func.sum(DailyStat.message_count).label("m"))
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.user_id)
        .order_by(func.sum(DailyStat.message_count).desc())
    )
    rows = list((await session.execute(rank_stmt)).all())
    rank_messages: int | None = None
    for idx, row in enumerate(rows, start=1):
        if row[0] == user_id:
            rank_messages = idx
            break

    rank_v_stmt = (
        select(DailyStat.user_id, func.sum(DailyStat.voice_seconds).label("v"))
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.stat_date >= start,
                DailyStat.stat_date <= end,
            )
        )
        .group_by(DailyStat.user_id)
        .order_by(func.sum(DailyStat.voice_seconds).desc())
    )
    rows_v = list((await session.execute(rank_v_stmt)).all())
    rank_voice: int | None = None
    for idx, row in enumerate(rows_v, start=1):
        if row[0] == user_id:
            rank_voice = idx
            break

    # トップチャンネル (このユーザーのみ)
    top_ch_stmt = (
        select(
            DailyStat.channel_id,
            func.coalesce(func.sum(DailyStat.message_count), 0),
            func.coalesce(func.sum(DailyStat.voice_seconds), 0),
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
        .order_by(func.sum(DailyStat.message_count).desc())
        .limit(5)
    )
    ch_rows = list((await session.execute(top_ch_stmt)).all())
    ch_meta_map = await get_channel_meta_map(session, guild_id, [r[0] for r in ch_rows])
    top_channels = [
        ChannelLeaderboardEntry(
            channel_id=cid,
            name=ch_meta_map[cid].name if cid in ch_meta_map else f"#{cid}",
            message_count=int(m),
            voice_seconds=int(v),
        )
        for cid, m, v in ch_rows
    ]

    meta_map = await get_user_meta_map(session, [user_id])
    meta = meta_map.get(user_id)

    return UserProfile(
        user_id=user_id,
        display_name=meta.display_name if meta else user_id,
        avatar_url=meta.avatar_url if meta else None,
        total_messages=total_messages,
        total_voice_seconds=total_voice,
        rank_messages=rank_messages,
        rank_voice=rank_voice,
        daily=daily,
        top_channels=top_channels,
    )
