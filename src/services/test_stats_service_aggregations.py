"""Postgres-backed tests for read-side aggregation queries.

カバー:
    - ``get_guild_summary``: 指定ウィンドウ内の合計・ユニーク数
    - ``get_daily_series``: 欠損日をゼロで埋める
    - ``get_user_leaderboard`` / ``get_channel_leaderboard``: 並び順 / メトリック
    - ``get_user_profile``: ランクの正確性 / トップチャンネル
"""

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat
from src.services.stats_service import (
    get_channel_leaderboard,
    get_daily_series,
    get_guild_summary,
    get_user_leaderboard,
    get_user_profile,
    upsert_channel_meta,
    upsert_guild,
    upsert_user_meta,
)
from src.utils import today_local

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
