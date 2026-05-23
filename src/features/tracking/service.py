"""Activity tracking write-side: daily_stats upsert + voice session lifecycle.

書き込み中心。読み出し系は ``stats`` / ``ranking`` / ``user_profile`` feature。

進行中ボイスセッションの「ローカル日ごとの秒数分割」ヘルパーもここに置く
(同じセッションを ``daily_stats`` flush と読み出し側 live delta の両方で
使うため)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any, cast

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import MAX_VOICE_SESSION_SECONDS
from src.database.models import DailyStat, SocialEdgeDaily, VoiceSession
from src.features.guilds.service import is_channel_excluded
from src.utils import get_timezone

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
        reactions_received=0,
        reactions_given=0,
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


async def increment_reactions_received(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    channel_id: str,
    stat_date: date,
) -> None:
    """``user_id`` のメッセージに付いたリアクション 1 件を加算する。

    ``user_id`` は **メッセージの投稿者** であって、リアクションをした人ではない。
    """
    stmt = pg_insert(DailyStat).values(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        message_count=0,
        char_count=0,
        attachment_count=0,
        reactions_received=1,
        reactions_given=0,
        voice_seconds=0,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_stat",
        set_={
            "reactions_received": DailyStat.reactions_received + 1,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def increment_reactions_given(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    channel_id: str,
    stat_date: date,
) -> None:
    """``user_id`` が他人のメッセージに付けたリアクション 1 件を加算する。

    ``user_id`` は **リアクションした人** であって、メッセージ投稿者ではない。
    """
    stmt = pg_insert(DailyStat).values(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        message_count=0,
        char_count=0,
        attachment_count=0,
        reactions_received=0,
        reactions_given=1,
        voice_seconds=0,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_stat",
        set_={
            "reactions_given": DailyStat.reactions_given + 1,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.execute(stmt)
    await session.commit()


async def decrement_reactions_received(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    channel_id: str,
    stat_date: date,
) -> None:
    """``user_id`` のメッセージから取り消された (外された) リアクション 1 件を減算する。

    対応する行が無い / 既に 0 の場合は何もしない (clamp at 0)。
    react→unreact ループでの水増しを防ぐために on_raw_reaction_remove から呼ばれる。
    ``stat_date`` は通常イベント受信日 (today) を渡す。日跨ぎで付けたものを外すと
    付与日が +1 のまま残るが、過去日の集計を改変しない方が無難という判断。
    """
    stmt = (
        update(DailyStat)
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.user_id == user_id,
                DailyStat.channel_id == channel_id,
                DailyStat.stat_date == stat_date,
                DailyStat.reactions_received > 0,
            )
        )
        .values(
            reactions_received=func.greatest(DailyStat.reactions_received - 1, 0),
            updated_at=datetime.now(UTC),
        )
    )
    await session.execute(stmt)
    await session.commit()


async def decrement_reactions_given(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    channel_id: str,
    stat_date: date,
) -> None:
    """``user_id`` が外したリアクション 1 件を ``reactions_given`` から減算する。

    対応する行が無い / 既に 0 の場合は何もしない (clamp at 0)。
    """
    stmt = (
        update(DailyStat)
        .where(
            and_(
                DailyStat.guild_id == guild_id,
                DailyStat.user_id == user_id,
                DailyStat.channel_id == channel_id,
                DailyStat.stat_date == stat_date,
                DailyStat.reactions_given > 0,
            )
        )
        .values(
            reactions_given=func.greatest(DailyStat.reactions_given - 1, 0),
            updated_at=datetime.now(UTC),
        )
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
        reactions_received=0,
        reactions_given=0,
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
# Social edge writes (for node-garden style relationship graphs)
# =============================================================================


def normalize_undirected_user_pair(user_a: str, user_b: str) -> tuple[str, str]:
    """無向 edge を安定した順序に正規化する。"""
    return (user_a, user_b) if user_a < user_b else (user_b, user_a)


async def increment_reply_edge(
    session: AsyncSession,
    *,
    guild_id: str,
    source_user_id: str,
    target_user_id: str,
    channel_id: str,
    stat_date: date,
) -> None:
    """reply した人 -> reply された人 の有向 edge を 1 加算する。"""
    if source_user_id == target_user_id:
        return
    await _upsert_social_edge_delta(
        session,
        guild_id=guild_id,
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        replies_delta=1,
    )


async def increment_reaction_edge(
    session: AsyncSession,
    *,
    guild_id: str,
    source_user_id: str,
    target_user_id: str,
    channel_id: str,
    stat_date: date,
) -> None:
    """reaction した人 -> 投稿者 の有向 edge を 1 加算する。"""
    if source_user_id == target_user_id:
        return
    await _upsert_social_edge_delta(
        session,
        guild_id=guild_id,
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        reactions_delta=1,
    )


async def decrement_reaction_edge(
    session: AsyncSession,
    *,
    guild_id: str,
    source_user_id: str,
    target_user_id: str,
    channel_id: str,
    stat_date: date,
) -> None:
    """reaction edge を 1 減算する。既に 0 の場合は 0 に丸める。"""
    if source_user_id == target_user_id:
        return
    await _upsert_social_edge_delta(
        session,
        guild_id=guild_id,
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        reactions_delta=-1,
    )


async def add_voice_copresence_seconds(
    session: AsyncSession,
    *,
    guild_id: str,
    user_a_id: str,
    user_b_id: str,
    channel_id: str,
    stat_date: date,
    seconds: int,
    sessions: int = 0,
) -> None:
    """同じ VC に同席した無向 edge へ秒数とセッション数を加算する。"""
    if seconds <= 0 or user_a_id == user_b_id:
        return
    seconds = min(seconds, MAX_VOICE_SESSION_SECONDS)
    source_user_id, target_user_id = normalize_undirected_user_pair(
        user_a_id, user_b_id
    )
    await _upsert_social_edge_delta(
        session,
        guild_id=guild_id,
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        voice_seconds_delta=seconds,
        voice_sessions_delta=sessions,
    )


async def add_voice_copresence_for_session_end(
    session: AsyncSession,
    *,
    ended_session: VoiceSession,
    ended_at: datetime,
) -> None:
    """終了した VC セッションと、同じチャンネルに残っている人の同席時間を集計する。"""
    active_peers = (
        (
            await session.execute(
                select(VoiceSession).where(
                    and_(
                        VoiceSession.guild_id == ended_session.guild_id,
                        VoiceSession.channel_id == ended_session.channel_id,
                        VoiceSession.user_id != ended_session.user_id,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    if not active_peers:
        return

    tz = get_timezone()
    for peer in active_peers:
        overlap_start = max(ended_session.joined_at, peer.joined_at)
        if overlap_start >= ended_at:
            continue
        session_counted = False
        for day, sec in split_interval_by_local_day(overlap_start, ended_at, tz=tz):
            await add_voice_copresence_seconds(
                session,
                guild_id=ended_session.guild_id,
                user_a_id=ended_session.user_id,
                user_b_id=peer.user_id,
                channel_id=ended_session.channel_id,
                stat_date=day,
                seconds=sec,
                sessions=0 if session_counted else 1,
            )
            session_counted = True


async def _upsert_social_edge_delta(
    session: AsyncSession,
    *,
    guild_id: str,
    source_user_id: str,
    target_user_id: str,
    channel_id: str,
    stat_date: date,
    voice_seconds_delta: int = 0,
    voice_sessions_delta: int = 0,
    replies_delta: int = 0,
    reactions_delta: int = 0,
) -> None:
    stmt = pg_insert(SocialEdgeDaily).values(
        guild_id=guild_id,
        source_user_id=source_user_id,
        target_user_id=target_user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        voice_seconds=max(voice_seconds_delta, 0),
        voice_sessions=max(voice_sessions_delta, 0),
        replies=max(replies_delta, 0),
        reactions=max(reactions_delta, 0),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_social_edge_daily",
        set_={
            "voice_seconds": func.greatest(
                SocialEdgeDaily.voice_seconds + voice_seconds_delta, 0
            ),
            "voice_sessions": func.greatest(
                SocialEdgeDaily.voice_sessions + voice_sessions_delta, 0
            ),
            "replies": func.greatest(SocialEdgeDaily.replies + replies_delta, 0),
            "reactions": func.greatest(SocialEdgeDaily.reactions + reactions_delta, 0),
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


async def flush_active_voice_sessions_to_daily_stats(
    session: AsyncSession,
) -> int:
    """進行中セッションの elapsed を ``daily_stats`` に反映する。

    Bot 再起動時にユーザーの「VC 滞在中の時間」が失われないようにするためのフラッシュ。
    JST 日付境界で正しく分割して各日の voice_seconds に加算する。
    Bot が長期間ダウンしていた zombie session (24h 超) はスキップする。

    呼び出し後は ``purge_all_voice_sessions`` で全 session を削除し、
    現在 VC に居るメンバーで作り直すのが想定フロー。

    Returns:
        反映できたセッション数。
    """
    sessions = await list_active_voice_sessions(session)
    if not sessions:
        return 0

    now = datetime.now(UTC)
    tz = get_timezone()
    persisted = 0
    for old in sessions:
        elapsed_total = int((now - old.joined_at).total_seconds())
        if elapsed_total <= 0:
            continue
        if elapsed_total > MAX_VOICE_SESSION_SECONDS:
            # Bot 長期 down 等の zombie。不正値を入れないよう捨てる。
            continue
        if await is_channel_excluded(session, old.guild_id, old.channel_id):
            continue
        for day, sec in split_voice_session_by_local_day(old, now=now, tz=tz):
            if sec > 0:
                await add_voice_seconds(
                    session,
                    guild_id=old.guild_id,
                    user_id=old.user_id,
                    channel_id=old.channel_id,
                    stat_date=day,
                    seconds=sec,
                )
        persisted += 1
    return persisted


# =============================================================================
# Live voice delta — 読み出し側 (stats / ranking / profile) に渡すための
# 「進行中セッションを (user, channel, day, seconds) に分解した行」。
# =============================================================================


@dataclass
class VoiceDelta:
    """進行中ボイスセッションを「ローカル日 × 秒数」に分割した1レコード。"""

    user_id: str
    channel_id: str
    day: date
    seconds: int


def split_voice_session_by_local_day(
    voice_session: VoiceSession,
    *,
    now: datetime,
    tz: timezone,
) -> list[tuple[date, int]]:
    """進行中セッションをローカル日ごとに ``(日, 秒)`` に分割する。

    日付境界をまたぐ場合は複数日に分かれる。例:
        TZ=JST, joined_at=2026-05-06 23:50, now=2026-05-07 00:30
        → [(2026-05-06, 600), (2026-05-07, 1800)]

    Args:
        voice_session: ``voice_sessions`` の 1 行 (``joined_at`` は UTC tz-aware)。
        now: 評価時刻 (UTC tz-aware)。テスト容易性のため引数化。
        tz: 日付境界を判定するタイムゾーン (Bot 設定の TZ)。

    Returns:
        ``[(local_date, seconds), ...]``。0 秒や未来日は含まれない。
    """
    joined_at = voice_session.joined_at
    if joined_at.tzinfo is None:
        joined_at = joined_at.replace(tzinfo=UTC)
    if joined_at >= now:
        return []  # 未来 / 同時刻 — 防御

    joined_local = joined_at.astimezone(tz)
    now_local = now.astimezone(tz)
    start_date = joined_local.date()
    end_date = now_local.date()

    if start_date == end_date:
        return [(start_date, int((now - joined_at).total_seconds()))]

    splits: list[tuple[date, int]] = []
    cursor_local = joined_local
    cursor_date = start_date
    while cursor_date < end_date:
        # 翌日 00:00 (ローカル) までの秒数
        next_midnight_local = datetime.combine(
            cursor_date + timedelta(days=1),
            time(0, 0, 0),
            tzinfo=tz,
        )
        seconds = int((next_midnight_local - cursor_local).total_seconds())
        if seconds > 0:
            splits.append((cursor_date, seconds))
        cursor_local = next_midnight_local
        cursor_date += timedelta(days=1)

    last_seconds = int((now_local - cursor_local).total_seconds())
    if last_seconds > 0:
        splits.append((end_date, last_seconds))
    return splits


def split_interval_by_local_day(
    start: datetime, end: datetime, *, tz: timezone
) -> list[tuple[date, int]]:
    """任意の interval をローカル日ごとの ``(日, 秒)`` に分割する。"""
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= start:
        return []

    start_local = start.astimezone(tz)
    end_local = end.astimezone(tz)
    if start_local.date() == end_local.date():
        return [(start_local.date(), int((end - start).total_seconds()))]

    splits: list[tuple[date, int]] = []
    cursor_local = start_local
    cursor_date = start_local.date()
    end_date = end_local.date()
    while cursor_date < end_date:
        next_midnight_local = datetime.combine(
            cursor_date + timedelta(days=1),
            time(0, 0, 0),
            tzinfo=tz,
        )
        seconds = int((next_midnight_local - cursor_local).total_seconds())
        if seconds > 0:
            splits.append((cursor_date, seconds))
        cursor_local = next_midnight_local
        cursor_date += timedelta(days=1)

    last_seconds = int((end_local - cursor_local).total_seconds())
    if last_seconds > 0:
        splits.append((end_date, last_seconds))
    return splits


async def live_voice_deltas(
    session: AsyncSession,
    guild_id: str,
    *,
    start_date: date | None,
    end_date: date,
    user_id: str | None = None,
) -> list[VoiceDelta]:
    """``voice_sessions`` から、窓 ``[start_date, end_date]`` 内の delta を返す。

    ``start_date=None`` で下限なし (lifetime 集計用)。
    ``user_id`` 指定で特定ユーザー分のみ取得 (プロフィール用)。
    """
    stmt = select(VoiceSession).where(VoiceSession.guild_id == guild_id)
    if user_id is not None:
        stmt = stmt.where(VoiceSession.user_id == user_id)
    result = await session.execute(stmt)
    active = list(result.scalars().all())

    now = datetime.now(UTC)
    tz = get_timezone()
    deltas: list[VoiceDelta] = []
    for vs in active:
        for day, sec in split_voice_session_by_local_day(vs, now=now, tz=tz):
            if start_date is not None and day < start_date:
                continue
            if day > end_date:
                continue
            deltas.append(
                VoiceDelta(
                    user_id=vs.user_id,
                    channel_id=vs.channel_id,
                    day=day,
                    seconds=sec,
                )
            )
    return deltas
