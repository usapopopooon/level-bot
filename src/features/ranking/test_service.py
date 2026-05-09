"""Postgres-backed tests for ranking (user / channel leaderboards)."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, VoiceSession
from src.features.meta.service import upsert_channel_meta, upsert_user_meta
from src.features.ranking.service import (
    get_channel_leaderboard,
    get_user_leaderboard,
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


async def test_user_leaderboard_offset_returns_next_page(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    # 7000 が最大、6994 が最小。msgs と user_id の降順が一致するように仕込む。
    for i in range(7):
        db_session.add(_stat(user=str(7000 - i), day=today, msgs=(7 - i) * 10))
    await db_session.commit()

    page1 = await get_user_leaderboard(db_session, "1001", days=1, limit=3, offset=0)
    page2 = await get_user_leaderboard(db_session, "1001", days=1, limit=3, offset=3)
    page3 = await get_user_leaderboard(db_session, "1001", days=1, limit=3, offset=6)

    assert [e.user_id for e in page1] == ["7000", "6999", "6998"]
    assert [e.user_id for e in page2] == ["6997", "6996", "6995"]
    assert [e.user_id for e in page3] == ["6994"]


async def test_user_leaderboard_offset_beyond_dataset_returns_empty(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(user="9999", day=today, msgs=1))
    await db_session.commit()

    entries = await get_user_leaderboard(
        db_session, "1001", days=1, limit=10, offset=10
    )
    assert entries == []


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


async def test_channel_leaderboard_offset_returns_next_page(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    # 5000 が最大、4996 が最小。msgs と channel_id の降順が一致するように仕込む。
    for i in range(5):
        db_session.add(_stat(channel=str(5000 - i), day=today, msgs=(5 - i) * 10))
    await db_session.commit()

    page1 = await get_channel_leaderboard(db_session, "1001", days=1, limit=2, offset=0)
    page2 = await get_channel_leaderboard(db_session, "1001", days=1, limit=2, offset=2)

    assert [e.channel_id for e in page1] == ["5000", "4999"]
    assert [e.channel_id for e in page2] == ["4998", "4997"]


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
# Live voice deltas merging into leaderboards
# =============================================================================


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
