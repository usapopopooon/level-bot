"""Postgres-backed tests for stats summary + daily series."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, VoiceSession
from src.features.guilds.service import upsert_guild
from src.features.stats.service import get_daily_series, get_guild_summary
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
    summary = await get_guild_summary(db_session, "9999", days=30)
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
# Live voice delta merging into summary / daily
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
