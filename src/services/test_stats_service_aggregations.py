"""Postgres-backed tests for read-side aggregation queries.

カバー:
    - ``get_guild_summary``: 指定ウィンドウ内の合計・ユニーク数
    - ``get_daily_series``: 欠損日をゼロで埋める
    - ``get_user_leaderboard`` / ``get_channel_leaderboard``: 並び順 / メトリック
    - ``get_user_profile``: ランクの正確性 / トップチャンネル
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, VoiceSession
from src.services.stats_service import (
    _split_voice_session_by_local_day,
    get_channel_leaderboard,
    get_daily_series,
    get_guild_summary,
    get_user_leaderboard,
    get_user_lifetime_stats,
    get_user_profile,
    upsert_channel_meta,
    upsert_guild,
    upsert_user_meta,
)
from src.utils import get_timezone, today_local

# =============================================================================
# Helpers
# =============================================================================


def _stat(
    *,
    guild: str = "1001",
    user: str = "2001",
    channel: str = "3001",
    day: date | None = None,
    msgs: int = 0,
    voice: int = 0,
    chars: int = 0,
) -> DailyStat:
    return DailyStat(
        guild_id=guild,
        user_id=user,
        channel_id=channel,
        stat_date=day or today_local(),
        message_count=msgs,
        char_count=chars,
        voice_seconds=voice,
    )


async def _seed_guild(session: AsyncSession, guild_id: str, name: str = "g") -> None:
    """Guild レコードがないと get_guild_summary が None を返すので登録する。"""
    await upsert_guild(
        session,
        guild_id=guild_id,
        name=name,
        icon_url=None,
        member_count=0,
    )


# =============================================================================
# get_guild_summary
# =============================================================================


async def test_guild_summary_aggregates_within_window(
    db_session: AsyncSession,
) -> None:
    await _seed_guild(db_session, "1001", "TestGuild")
    today = today_local()
    db_session.add_all(
        [
            _stat(user="2001", channel="3001", day=today, msgs=10, voice=300),
            _stat(user="2002", channel="3002", day=today, msgs=5, voice=600),
            _stat(user="2001", channel="3002", day=today - timedelta(days=1), msgs=3),
        ]
    )
    await db_session.commit()

    summary = await get_guild_summary(db_session, "1001", days=30)
    assert summary is not None
    assert summary.name == "TestGuild"
    assert summary.total_messages == 18
    assert summary.total_voice_seconds == 900
    assert summary.active_users == 2  # u1, u2


async def test_guild_summary_excludes_data_outside_window(
    db_session: AsyncSession,
) -> None:
    await _seed_guild(db_session, "1001")
    today = today_local()
    db_session.add_all(
        [
            _stat(user="2001", day=today, msgs=10),
            _stat(user="2001", day=today - timedelta(days=40), msgs=999),
        ]
    )
    await db_session.commit()

    summary = await get_guild_summary(db_session, "1001", days=30)
    assert summary is not None
    assert summary.total_messages == 10  # 40 日前は対象外


async def test_guild_summary_returns_none_for_unknown_guild(
    db_session: AsyncSession,
) -> None:
    summary = await get_guild_summary(db_session, "nonexistent", days=30)
    assert summary is None


async def test_guild_summary_zero_when_no_data(db_session: AsyncSession) -> None:
    await _seed_guild(db_session, "1001")
    summary = await get_guild_summary(db_session, "1001", days=30)
    assert summary is not None
    assert summary.total_messages == 0
    assert summary.total_voice_seconds == 0
    assert summary.active_users == 0


# =============================================================================
# get_daily_series
# =============================================================================


async def test_daily_series_zero_fills_missing_days(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(day=today, msgs=5),
            _stat(day=today - timedelta(days=4), msgs=3),
        ]
    )
    await db_session.commit()

    points = await get_daily_series(db_session, "1001", days=5)
    assert len(points) == 5
    # 連続した 5 日分すべて含まれる
    expected_dates = [today - timedelta(days=4 - i) for i in range(5)]
    assert [p.stat_date for p in points] == expected_dates
    # 5 日前と今日にだけ値が入る
    assert points[0].message_count == 3  # 4 日前
    assert points[-1].message_count == 5  # 今日
    # 中間日は 0
    assert all(p.message_count == 0 for p in points[1:-1])


async def test_daily_series_includes_today(db_session: AsyncSession) -> None:
    points = await get_daily_series(db_session, "1001", days=7)
    assert points[-1].stat_date == today_local()
    assert len(points) == 7


async def test_daily_series_aggregates_across_users_and_channels(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="2001", channel="3001", day=today, msgs=2, voice=60),
            _stat(user="2002", channel="3001", day=today, msgs=3, voice=120),
            _stat(user="2001", channel="3002", day=today, msgs=4, voice=180),
        ]
    )
    await db_session.commit()

    points = await get_daily_series(db_session, "1001", days=1)
    assert len(points) == 1
    assert points[0].message_count == 9
    assert points[0].voice_seconds == 360


# =============================================================================
# get_user_leaderboard
# =============================================================================


async def test_user_leaderboard_orders_by_messages_desc(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="100", day=today, msgs=10),
            _stat(user="200", day=today, msgs=30),
            _stat(user="300", day=today, msgs=20),
        ]
    )
    await db_session.commit()

    entries = await get_user_leaderboard(db_session, "1001", days=1, metric="messages")
    assert [e.user_id for e in entries] == ["200", "300", "100"]
    assert [e.message_count for e in entries] == [30, 20, 10]


async def test_user_leaderboard_orders_by_voice_when_metric_voice(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="100", day=today, msgs=100, voice=60),
            _stat(user="200", day=today, msgs=1, voice=999),
        ]
    )
    await db_session.commit()

    entries = await get_user_leaderboard(db_session, "1001", days=1, metric="voice")
    assert [e.user_id for e in entries] == ["200", "100"]


async def test_user_leaderboard_respects_limit(db_session: AsyncSession) -> None:
    today = today_local()
    for i in range(20):
        db_session.add(_stat(user=f"700{i}", day=today, msgs=i + 1))
    await db_session.commit()

    entries = await get_user_leaderboard(db_session, "1001", days=1, limit=5)
    assert len(entries) == 5


async def test_user_leaderboard_includes_meta_display_name(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(user="123", day=today, msgs=5))
    await db_session.commit()
    await upsert_user_meta(
        db_session,
        user_id="123",
        display_name="Alice",
        avatar_url=None,
        is_bot=False,
    )

    entries = await get_user_leaderboard(db_session, "1001", days=1)
    assert entries[0].display_name == "Alice"


async def test_user_leaderboard_falls_back_to_id_when_no_meta(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(user="999", day=today, msgs=1))
    await db_session.commit()

    entries = await get_user_leaderboard(db_session, "1001", days=1)
    assert entries[0].display_name == "999"
    assert entries[0].avatar_url is None


# =============================================================================
# get_channel_leaderboard
# =============================================================================


async def test_channel_leaderboard_orders_by_messages_desc(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(channel="100", day=today, msgs=5),
            _stat(channel="200", day=today, msgs=15),
            _stat(channel="300", day=today, msgs=10),
        ]
    )
    await db_session.commit()

    entries = await get_channel_leaderboard(db_session, "1001", days=1)
    assert [e.channel_id for e in entries] == ["200", "300", "100"]


async def test_channel_leaderboard_resolves_meta_name(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(channel="500", day=today, msgs=1))
    await db_session.commit()
    await upsert_channel_meta(
        db_session,
        guild_id="1001",
        channel_id="500",
        name="general",
        channel_type="TextChannel",
    )

    entries = await get_channel_leaderboard(db_session, "1001", days=1)
    assert entries[0].name == "general"


# =============================================================================
# get_user_profile
# =============================================================================


async def test_user_profile_includes_correct_rank_messages(
    db_session: AsyncSession,
) -> None:
    """目的のユーザーがメッセージ数で何位かを正確に返す。"""
    today = today_local()
    db_session.add_all(
        [
            _stat(user="100", day=today, msgs=100),
            _stat(user="200", day=today, msgs=50),
            _stat(user="9999", day=today, msgs=30),
            _stat(user="400", day=today, msgs=10),
        ]
    )
    await db_session.commit()

    profile = await get_user_profile(db_session, "1001", "9999", days=1)
    assert profile is not None
    assert profile.rank_messages == 3
    assert profile.total_messages == 30


async def test_user_profile_separate_rank_for_messages_and_voice(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="100", day=today, msgs=100, voice=60),
            _stat(user="9999", day=today, msgs=10, voice=500),
        ]
    )
    await db_session.commit()

    profile = await get_user_profile(db_session, "1001", "9999", days=1)
    assert profile is not None
    assert profile.rank_messages == 2
    assert profile.rank_voice == 1


async def test_user_profile_returns_none_when_no_data_no_meta(
    db_session: AsyncSession,
) -> None:
    profile = await get_user_profile(db_session, "1001", "8888", days=30)
    assert profile is None


async def test_user_profile_returns_blank_profile_when_only_meta(
    db_session: AsyncSession,
) -> None:
    """活動ゼロでも user_meta が登録されていれば 0 のプロフィールを返す。"""
    await upsert_user_meta(
        db_session,
        user_id="500",
        display_name="Ghost",
        avatar_url=None,
        is_bot=False,
    )
    profile = await get_user_profile(db_session, "1001", "500", days=30)
    assert profile is not None
    assert profile.display_name == "Ghost"
    assert profile.total_messages == 0
    assert profile.total_voice_seconds == 0


async def test_user_profile_top_channels_limited_to_5(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    for i in range(10):
        db_session.add(_stat(user="9999", channel=f"800{i}", day=today, msgs=i + 1))
    await db_session.commit()

    profile = await get_user_profile(db_session, "1001", "9999", days=1)
    assert profile is not None
    assert len(profile.top_channels) == 5
    # メッセージ数の多い順
    assert [c.message_count for c in profile.top_channels] == [10, 9, 8, 7, 6]


async def test_user_profile_daily_series_zero_fills(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(user="9999", day=today, msgs=5))
    db_session.add(_stat(user="9999", day=today - timedelta(days=2), msgs=3))
    await db_session.commit()

    profile = await get_user_profile(db_session, "1001", "9999", days=3)
    assert profile is not None
    assert len(profile.daily) == 3
    # 中間日は 0
    assert profile.daily[1].message_count == 0


# =============================================================================
# Live voice delta (進行中ボイスセッションの merge)
# =============================================================================


async def test_summary_includes_active_voice_session(
    db_session: AsyncSession,
) -> None:
    """進行中セッションが summary の voice_seconds と active_users に乗る。"""
    await _seed_guild(db_session, "1001")
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=30),
        )
    )
    await db_session.commit()

    summary = await get_guild_summary(db_session, "1001", days=1)
    assert summary is not None
    # ~30 分 = 1800 秒。多少のずれを許容
    assert 1700 <= summary.total_voice_seconds <= 1900
    assert summary.active_users == 1


async def test_summary_active_user_unioned_with_static_users(
    db_session: AsyncSession,
) -> None:
    """daily_stats の users と live delta の users が和集合になる (重複排除)。"""
    await _seed_guild(db_session, "1001")
    today = today_local()
    db_session.add(_stat(user="2001", day=today, msgs=10))  # static
    db_session.add(_stat(user="2002", day=today, msgs=5))  # static
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",  # 既に static にいるユーザー
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2003",  # static にいない新規
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    summary = await get_guild_summary(db_session, "1001", days=1)
    assert summary is not None
    assert summary.active_users == 3  # 2001, 2002, 2003


async def test_daily_series_includes_live_voice_today(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=20),
        )
    )
    await db_session.commit()

    points = await get_daily_series(db_session, "1001", days=1)
    assert len(points) == 1
    assert 1100 <= points[0].voice_seconds <= 1300  # ~20 分


async def test_user_leaderboard_includes_live_only_user(
    db_session: AsyncSession,
) -> None:
    """daily_stats に居ないが進行中セッションだけあるユーザーも順位に乗る。"""
    today = today_local()
    db_session.add(_stat(user="2001", day=today, voice=300))  # 5 分 static
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2002",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(hours=1),  # 60 分 live
        )
    )
    await db_session.commit()

    entries = await get_user_leaderboard(db_session, "1001", days=1, metric="voice")
    assert [e.user_id for e in entries] == ["2002", "2001"]
    assert entries[0].voice_seconds >= 3500  # ~3600 秒


async def test_user_leaderboard_static_voice_plus_live(
    db_session: AsyncSession,
) -> None:
    """同じユーザーの static + live が合算される。"""
    today = today_local()
    db_session.add(_stat(user="2001", day=today, voice=600))  # 10 分 static
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=15),  # 15 分 live
        )
    )
    await db_session.commit()

    entries = await get_user_leaderboard(db_session, "1001", days=1, metric="voice")
    assert len(entries) == 1
    # 600 + ~900 = ~1500 秒
    assert 1450 <= entries[0].voice_seconds <= 1550


async def test_channel_leaderboard_includes_live(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=30),
        )
    )
    await db_session.commit()

    entries = await get_channel_leaderboard(db_session, "1001", days=1, metric="voice")
    assert len(entries) == 1
    assert entries[0].channel_id == "3001"
    assert 1700 <= entries[0].voice_seconds <= 1900


async def test_user_profile_includes_live_voice_in_total(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(user="9999", day=today, voice=300))  # static 5 分
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="9999",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),  # live 10 分
        )
    )
    await db_session.commit()

    profile = await get_user_profile(db_session, "1001", "9999", days=1)
    assert profile is not None
    # 300 + ~600 = ~900 秒
    assert 850 <= profile.total_voice_seconds <= 950


async def test_user_profile_rank_voice_considers_live_for_other_users(
    db_session: AsyncSession,
) -> None:
    """他ユーザーの live delta が大きいと、自分の rank_voice は下がる。"""
    today = today_local()
    db_session.add(_stat(user="6001", day=today, voice=600))  # 10 分

    # 他ユーザーが live で 60 分 → 1 位 should be other
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="6002",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db_session.commit()

    profile = await get_user_profile(db_session, "1001", "6001", days=1)
    assert profile is not None
    assert profile.rank_voice == 2  # OTHER が live で勝っている


async def test_user_profile_top_channels_includes_live_voice(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="9999",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=20),
        )
    )
    await db_session.commit()

    profile = await get_user_profile(db_session, "1001", "9999", days=1)
    assert profile is not None
    assert len(profile.top_channels) == 1
    assert profile.top_channels[0].channel_id == "3001"
    assert profile.top_channels[0].voice_seconds >= 1100


# =============================================================================
# Unit tests for _split_voice_session_by_local_day (DB 不要)
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
    splits = _split_voice_session_by_local_day(_vs(joined), now=now, tz=tz)
    assert splits == [(date(2026, 5, 7), 1800)]


def test_split_session_crossing_midnight_jst() -> None:
    """JST 23:50 入室 → 翌 00:30 で分割される。"""
    tz = get_timezone()  # JST
    # 2026-05-06 14:50 UTC = 2026-05-06 23:50 JST
    joined = datetime(2026, 5, 6, 14, 50, 0, tzinfo=UTC)
    # 2026-05-06 15:30 UTC = 2026-05-07 00:30 JST
    now = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
    splits = _split_voice_session_by_local_day(_vs(joined), now=now, tz=tz)
    # 23:50 → 24:00 (JST) = 10 分 = 600 秒、24:00 → 00:30 = 30 分 = 1800 秒
    assert splits == [(date(2026, 5, 6), 600), (date(2026, 5, 7), 1800)]


def test_split_session_spanning_multiple_days() -> None:
    """3 日にまたがるセッションは中日が 86400 秒、両端が部分日。"""
    tz = get_timezone()
    # 開始: 2026-05-04 23:50 JST
    joined = datetime(2026, 5, 4, 14, 50, 0, tzinfo=UTC)
    # 現在: 2026-05-07 00:30 JST
    now = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
    splits = _split_voice_session_by_local_day(_vs(joined), now=now, tz=tz)
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
    assert _split_voice_session_by_local_day(_vs(joined), now=now, tz=tz) == []


def test_split_handles_naive_datetime_as_utc() -> None:
    """tzinfo=None でも UTC として扱う (DB ドライバ次第のフォールバック)。"""
    tz = get_timezone()
    naive_joined = datetime(2026, 5, 6, 15, 0, 0)  # naive
    now = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
    splits = _split_voice_session_by_local_day(_vs(naive_joined), now=now, tz=tz)
    assert splits == [(date(2026, 5, 7), 1800)]


# =============================================================================
# get_user_lifetime_stats (ユーザーレベル算出の素データ)
# =============================================================================


async def test_lifetime_aggregates_all_history(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="9999", day=today, msgs=10, voice=600, chars=50),
            _stat(user="9999", day=today - timedelta(days=30), msgs=5, voice=120),
            _stat(user="9999", day=today - timedelta(days=365), msgs=3, voice=60),
            _stat(user="9999", day=today - timedelta(days=2000), msgs=2, voice=30),
        ]
    )
    await db_session.commit()

    stats = await get_user_lifetime_stats(db_session, "1001", "9999")
    assert stats is not None
    assert stats.total_messages == 20
    assert stats.total_voice_seconds == 810
    assert stats.total_char_count == 50
    assert stats.first_active_date == today - timedelta(days=2000)
    assert stats.last_active_date == today
    assert stats.active_days == 4


async def test_lifetime_includes_live_voice(
    db_session: AsyncSession,
) -> None:
    """lifetime も live delta を反映 (進行中 VC 滞在時間)。"""
    today = today_local()
    db_session.add(_stat(user="9999", day=today, voice=300))
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="9999",
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=20),
        )
    )
    await db_session.commit()

    stats = await get_user_lifetime_stats(db_session, "1001", "9999")
    assert stats is not None
    # 300 + ~1200 = ~1500 秒
    assert 1450 <= stats.total_voice_seconds <= 1550


async def test_lifetime_returns_none_for_unknown_user(
    db_session: AsyncSession,
) -> None:
    stats = await get_user_lifetime_stats(db_session, "1001", "9999")
    assert stats is None


async def test_lifetime_returns_meta_only_when_no_activity(
    db_session: AsyncSession,
) -> None:
    """活動 0 でも meta が登録されていれば 0 件のレコードを返す。"""
    await upsert_user_meta(
        db_session,
        user_id="9999",
        display_name="Ghost",
        avatar_url=None,
        is_bot=False,
    )
    stats = await get_user_lifetime_stats(db_session, "1001", "9999")
    assert stats is not None
    assert stats.display_name == "Ghost"
    assert stats.total_messages == 0
    assert stats.total_voice_seconds == 0
    assert stats.active_days == 0


async def test_lifetime_resolves_display_name(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(user="9999", day=today, msgs=1))
    await db_session.commit()
    await upsert_user_meta(
        db_session,
        user_id="9999",
        display_name="Alice",
        avatar_url="https://cdn/a.png",
        is_bot=False,
    )

    stats = await get_user_lifetime_stats(db_session, "1001", "9999")
    assert stats is not None
    assert stats.display_name == "Alice"
    assert stats.avatar_url == "https://cdn/a.png"
