"""Postgres-backed tests for tracking write-side service.

カバー:
    - increment_message_stat (初回挿入 / 加算 / 日付・チャンネル分離)
    - add_voice_seconds (累積 / クランプ / ゼロ早期 return / メッセージ共存)
    - voice session lifecycle (start/end の置換動作)
    - purge_all_voice_sessions
    - flush_active_voice_sessions_to_daily_stats (除外 / zombie 除外 / セッション保持)
    - split_voice_session_by_local_day (DB 不要のユニットテスト)
    - daily_stat の UNIQUE 制約 smoke check
"""

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy.exc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import MAX_VOICE_SESSION_SECONDS
from src.database.models import DailyStat, VoiceSession
from src.features.guilds.service import add_excluded_channel
from src.features.tracking.service import (
    add_voice_seconds,
    decrement_reactions_given,
    decrement_reactions_received,
    end_voice_session,
    flush_active_voice_sessions_to_daily_stats,
    increment_message_stat,
    increment_reactions_given,
    increment_reactions_received,
    list_active_voice_sessions,
    purge_all_voice_sessions,
    split_voice_session_by_local_day,
    start_voice_session,
)
from src.utils import get_timezone

# =============================================================================
# increment_message_stat
# =============================================================================


async def test_increment_message_stat_creates_first_row(
    db_session: AsyncSession,
) -> None:
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=42,
        attachment_count=1,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.message_count == 1
    assert row.char_count == 42
    assert row.attachment_count == 1


async def test_increment_message_stat_accumulates(db_session: AsyncSession) -> None:
    for char_count in (10, 20, 30):
        await increment_message_stat(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 5, 1),
            char_count=char_count,
            attachment_count=0,
        )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 1
    assert rows[0].message_count == 3
    assert rows[0].char_count == 60


async def test_increment_message_stat_separates_dates(
    db_session: AsyncSession,
) -> None:
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=10,
        attachment_count=0,
    )
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 2),
        char_count=20,
        attachment_count=0,
    )
    rows = (
        (await db_session.execute(select(DailyStat).order_by(DailyStat.stat_date)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert [r.message_count for r in rows] == [1, 1]


async def test_increment_message_stat_separates_channels(
    db_session: AsyncSession,
) -> None:
    """チャンネルが違えば別行になる (channel-level 集計の前提)。"""
    for ch in ("4", "5"):
        await increment_message_stat(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id=ch,
            stat_date=date(2026, 5, 1),
            char_count=5,
            attachment_count=0,
        )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 2


# =============================================================================
# increment_reactions_received / _given
# =============================================================================


async def test_increment_reactions_received_creates_and_accumulates(
    db_session: AsyncSession,
) -> None:
    """初回挿入後、同一 (guild, user, channel, day) なら加算されて 1 行に集約される。"""
    for _ in range(3):
        await increment_reactions_received(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 5, 1),
        )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 1
    assert rows[0].reactions_received == 3
    assert rows[0].reactions_given == 0


async def test_increment_reactions_given_creates_and_accumulates(
    db_session: AsyncSession,
) -> None:
    for _ in range(2):
        await increment_reactions_given(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 5, 1),
        )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.reactions_given == 2
    assert row.reactions_received == 0


async def test_reactions_received_and_given_share_row_when_same_user(
    db_session: AsyncSession,
) -> None:
    """同じ (guild, user, channel, day) なら 1 行に両カラムが入る。"""
    await increment_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    await increment_reactions_given(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.reactions_received == 1
    assert row.reactions_given == 1


async def test_reactions_coexist_with_messages_in_same_row(
    db_session: AsyncSession,
) -> None:
    """同一行のメッセージカウントに加算が来ても、リアクションは独立に増える。"""
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=10,
        attachment_count=0,
    )
    await increment_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.message_count == 1
    assert row.char_count == 10
    assert row.reactions_received == 1
    assert row.reactions_given == 0


# =============================================================================
# decrement_reactions_received / _given
# =============================================================================


async def test_increment_then_decrement_reactions_received_nets_to_zero(
    db_session: AsyncSession,
) -> None:
    """add → remove (同日) で reactions_received が 0 に戻る。"""
    await increment_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    await decrement_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.reactions_received == 0


async def test_decrement_reactions_received_does_not_go_below_zero(
    db_session: AsyncSession,
) -> None:
    """既に 0 の行を decrement しても負にならない (no-op)。"""
    await increment_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    # 1 → 0 → さらに -1 してもクランプ
    await decrement_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    await decrement_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.reactions_received == 0


async def test_decrement_reactions_received_no_row_is_noop(
    db_session: AsyncSession,
) -> None:
    """対応行が存在しない時は何も起きない (新規行も作らない)。"""
    await decrement_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert rows == []


async def test_decrement_reactions_given_clamps_at_zero(
    db_session: AsyncSession,
) -> None:
    """reactions_given も同様に 0 クランプ・no-op。"""
    await increment_reactions_given(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    for _ in range(3):
        await decrement_reactions_given(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 5, 1),
        )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.reactions_given == 0


async def test_decrement_does_not_affect_other_columns(
    db_session: AsyncSession,
) -> None:
    """reactions_received の decrement が他カラムに副作用を出さない。"""
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=10,
        attachment_count=0,
    )
    await increment_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    await increment_reactions_given(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    await decrement_reactions_received(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.reactions_received == 0
    assert row.reactions_given == 1
    assert row.message_count == 1
    assert row.char_count == 10


# =============================================================================
# add_voice_seconds
# =============================================================================


async def test_add_voice_seconds_inserts_first_row(db_session: AsyncSession) -> None:
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=600,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.voice_seconds == 600
    assert row.message_count == 0


async def test_add_voice_seconds_accumulates(db_session: AsyncSession) -> None:
    for s in (60, 120, 180):
        await add_voice_seconds(
            db_session,
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 5, 1),
            seconds=s,
        )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.voice_seconds == 360


async def test_add_voice_seconds_clamps_at_max(db_session: AsyncSession) -> None:
    """単発呼び出しで MAX を超える値を渡しても上限に切り詰められる。"""
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=MAX_VOICE_SESSION_SECONDS * 10,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.voice_seconds == MAX_VOICE_SESSION_SECONDS


async def test_add_voice_seconds_skips_zero_or_negative(
    db_session: AsyncSession,
) -> None:
    """0 や負値は no-op (DB に書き込まない)。"""
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=0,
    )
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=-100,
    )
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert rows == []


async def test_add_voice_seconds_coexists_with_message_count(
    db_session: AsyncSession,
) -> None:
    """同一行にメッセージカウントが既にあっても、ボイス秒だけ加算される。"""
    await increment_message_stat(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        char_count=10,
        attachment_count=0,
    )
    await add_voice_seconds(
        db_session,
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=date(2026, 5, 1),
        seconds=300,
    )
    row = (await db_session.execute(select(DailyStat))).scalar_one()
    assert row.message_count == 1
    assert row.char_count == 10
    assert row.voice_seconds == 300


# =============================================================================
# Voice session lifecycle (start / end / purge)
# =============================================================================


async def test_start_voice_session_replaces_existing(db_session: AsyncSession) -> None:
    """同一ユーザーが新チャンネルへ移動した場合、旧セッションは置き換わる。"""
    await start_voice_session(db_session, guild_id="1", user_id="2", channel_id="100")
    await start_voice_session(db_session, guild_id="1", user_id="2", channel_id="200")

    sessions = await list_active_voice_sessions(db_session)
    assert len(sessions) == 1
    assert sessions[0].channel_id == "200"


async def test_end_voice_session_returns_record_then_deletes(
    db_session: AsyncSession,
) -> None:
    await start_voice_session(db_session, guild_id="1", user_id="2", channel_id="100")
    voice = await end_voice_session(db_session, guild_id="1", user_id="2")
    assert voice is not None
    assert voice.channel_id == "100"
    assert await list_active_voice_sessions(db_session) == []


async def test_end_voice_session_returns_none_when_no_session(
    db_session: AsyncSession,
) -> None:
    voice = await end_voice_session(db_session, guild_id="1", user_id="2")
    assert voice is None


async def test_purge_all_voice_sessions_removes_everything(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            VoiceSession(guild_id="1", user_id="2", channel_id="3"),
            VoiceSession(guild_id="1", user_id="4", channel_id="5"),
            VoiceSession(guild_id="9", user_id="10", channel_id="11"),
        ]
    )
    await db_session.commit()

    deleted = await purge_all_voice_sessions(db_session)
    assert deleted == 3
    assert await list_active_voice_sessions(db_session) == []


async def test_purge_all_voice_sessions_returns_zero_when_empty(
    db_session: AsyncSession,
) -> None:
    deleted = await purge_all_voice_sessions(db_session)
    assert deleted == 0


# =============================================================================
# flush_active_voice_sessions_to_daily_stats (Bot 再起動時のフラッシュ)
# =============================================================================


async def test_flush_writes_elapsed_to_daily_stats(
    db_session: AsyncSession,
) -> None:
    """進行中セッションが daily_stats に保存され、再起動を挟んでも時間が消えない。"""
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=30),
        )
    )
    await db_session.commit()

    flushed = await flush_active_voice_sessions_to_daily_stats(db_session)
    assert flushed == 1

    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 1
    # ~30 分 = 1800 秒。多少のずれを許容
    assert 1700 <= rows[0].voice_seconds <= 1900


async def test_flush_returns_zero_when_no_active_sessions(
    db_session: AsyncSession,
) -> None:
    assert await flush_active_voice_sessions_to_daily_stats(db_session) == 0


async def test_flush_skips_zombie_session_over_24h(
    db_session: AsyncSession,
) -> None:
    """24h を超える zombie session は不正値防止のためスキップされる。"""
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(hours=48),
        )
    )
    await db_session.commit()

    flushed = await flush_active_voice_sessions_to_daily_stats(db_session)
    assert flushed == 0
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert rows == []


async def test_flush_skips_excluded_channel(db_session: AsyncSession) -> None:
    """除外チャンネルのセッションは flush で daily_stats に書かれない。"""
    await add_excluded_channel(db_session, "1001", "3001")
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    flushed = await flush_active_voice_sessions_to_daily_stats(db_session)
    assert flushed == 0
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert rows == []


async def test_flush_does_not_remove_sessions(db_session: AsyncSession) -> None:
    """flush 自体は session を残す (purge は別関数の責務)。"""
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    await flush_active_voice_sessions_to_daily_stats(db_session)
    sessions = await list_active_voice_sessions(db_session)
    assert len(sessions) == 1


# =============================================================================
# split_voice_session_by_local_day (DB 不要のユニットテスト)
# =============================================================================


def _vs(joined_at: datetime) -> VoiceSession:
    """Test 用に in-memory で VoiceSession を作る (DB に save しない)。"""
    return VoiceSession(
        guild_id="1001",
        user_id="2001",
        channel_id="3001",
        joined_at=joined_at,
    )


def test_split_single_day_session() -> None:
    """同一日内のセッションはそのまま 1 件で返る。"""
    tz = get_timezone()  # JST
    now = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)  # 2026-05-07 00:30 JST
    joined = datetime(2026, 5, 6, 15, 0, 0, tzinfo=UTC)  # 2026-05-07 00:00 JST
    splits = split_voice_session_by_local_day(_vs(joined), now=now, tz=tz)
    assert splits == [(date(2026, 5, 7), 1800)]


def test_split_session_crossing_midnight_jst() -> None:
    """JST 23:50 入室 → 翌 00:30 で分割される。"""
    tz = get_timezone()  # JST
    # 2026-05-06 14:50 UTC = 2026-05-06 23:50 JST
    joined = datetime(2026, 5, 6, 14, 50, 0, tzinfo=UTC)
    # 2026-05-06 15:30 UTC = 2026-05-07 00:30 JST
    now = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
    splits = split_voice_session_by_local_day(_vs(joined), now=now, tz=tz)
    # 23:50 → 24:00 (JST) = 10 分 = 600 秒、24:00 → 00:30 = 30 分 = 1800 秒
    assert splits == [(date(2026, 5, 6), 600), (date(2026, 5, 7), 1800)]


def test_split_session_spanning_multiple_days() -> None:
    """3 日にまたがるセッションは中日が 86400 秒、両端が部分日。"""
    tz = get_timezone()
    # 開始: 2026-05-04 23:50 JST
    joined = datetime(2026, 5, 4, 14, 50, 0, tzinfo=UTC)
    # 現在: 2026-05-07 00:30 JST
    now = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
    splits = split_voice_session_by_local_day(_vs(joined), now=now, tz=tz)
    assert splits == [
        (date(2026, 5, 4), 600),  # 23:50 → 24:00
        (date(2026, 5, 5), 86400),  # 丸 1 日
        (date(2026, 5, 6), 86400),  # 丸 1 日
        (date(2026, 5, 7), 1800),  # 00:00 → 00:30
    ]


def test_split_skips_future_joined_at() -> None:
    """now <= joined_at は防御的に空 list。"""
    tz = get_timezone()
    now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    joined = datetime(2026, 5, 6, 13, 0, 0, tzinfo=UTC)
    assert split_voice_session_by_local_day(_vs(joined), now=now, tz=tz) == []


def test_split_handles_naive_datetime_as_utc() -> None:
    """tzinfo=None でも UTC として扱う (DB ドライバ次第のフォールバック)。"""
    tz = get_timezone()
    naive_joined = datetime(2026, 5, 6, 15, 0, 0)  # naive
    now = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
    splits = split_voice_session_by_local_day(_vs(naive_joined), now=now, tz=tz)
    assert splits == [(date(2026, 5, 7), 1800)]


# =============================================================================
# Daily stats schema (composite UNIQUE constraint smoke check)
# =============================================================================


async def test_daily_stat_unique_constraint(db_session: AsyncSession) -> None:
    """同一 (guild, user, channel, date) の重複挿入は IntegrityError。

    upsert は本番 (Postgres) でしか使えないが、UNIQUE 制約自体は sqlite でも効く。
    """
    db_session.add(
        DailyStat(
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 1, 1),
            message_count=1,
        )
    )
    await db_session.commit()

    db_session.add(
        DailyStat(
            guild_id="1",
            user_id="2",
            channel_id="3",
            stat_date=date(2026, 1, 1),
            message_count=1,
        )
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        await db_session.commit()
