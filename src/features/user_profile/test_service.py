"""Postgres-backed tests for user profile + lifetime aggregation."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, VoiceSession
from src.features.meta.service import upsert_user_meta
from src.features.user_profile.service import (
    get_user_lifetime_stats,
    get_user_profile,
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
