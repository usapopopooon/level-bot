"""Postgres-backed tests for stats summary + daily series."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    DailyStat,
    ExcludedUser,
    HourlyStat,
    SocialEdgeDaily,
    UserMeta,
    VoiceSession,
)
from src.features.guilds.service import upsert_guild
from src.features.stats.service import (
    get_daily_series,
    get_guild_summary,
    get_hourly_activity_heatmap,
    get_social_graph,
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
    reacts_recv: int = 0,
    reacts_given: int = 0,
) -> DailyStat:
    return DailyStat(
        guild_id=guild,
        user_id=user,
        channel_id=channel,
        stat_date=day or today_local(),
        message_count=msgs,
        char_count=chars,
        voice_seconds=voice,
        reactions_received=reacts_recv,
        reactions_given=reacts_given,
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


async def test_guild_summary_aggregates_reactions(
    db_session: AsyncSession,
) -> None:
    """reactions_received / reactions_given も合計される。"""
    await _seed_guild(db_session, "1001")
    today = today_local()
    db_session.add_all(
        [
            _stat(user="2001", day=today, reacts_recv=4, reacts_given=2),
            _stat(user="2002", day=today, reacts_recv=1, reacts_given=5),
        ]
    )
    await db_session.commit()

    summary = await get_guild_summary(db_session, "1001", days=1)
    assert summary is not None
    assert summary.total_reactions_received == 5
    assert summary.total_reactions_given == 7


async def test_daily_series_aggregates_reactions(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="2001", day=today, reacts_recv=2, reacts_given=1),
            _stat(user="2002", day=today, reacts_recv=3, reacts_given=4),
        ]
    )
    await db_session.commit()

    points = await get_daily_series(db_session, "1001", days=1)
    assert len(points) == 1
    assert points[0].reactions_received == 5
    assert points[0].reactions_given == 5


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


# =============================================================================
# get_hourly_activity_heatmap
# =============================================================================


async def test_hourly_activity_heatmap_excludes_bots(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    weekday = today.weekday()
    db_session.add_all(
        [
            UserMeta(user_id="2001", display_name="human", is_bot=False),
            UserMeta(user_id="2002", display_name="bot", is_bot=True),
            HourlyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=today,
                stat_hour=20,
                voice_seconds=600,
            ),
            HourlyStat(
                guild_id="1001",
                user_id="2002",
                channel_id="3001",
                stat_date=today,
                stat_hour=20,
                voice_seconds=9999,
            ),
        ]
    )
    await db_session.commit()

    cells = await get_hourly_activity_heatmap(db_session, "1001", days=1)

    assert len(cells) == 168
    cell = next(c for c in cells if c.weekday == weekday and c.hour == 20)
    assert cell.voice_seconds == 600
    assert cell.active_users == 1
    assert cell.intensity_percent == 100


# =============================================================================
# get_social_graph
# =============================================================================


async def test_social_graph_combines_activity_and_edges(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            UserMeta(user_id="2001", display_name="Alice", avatar_url="https://a"),
            UserMeta(user_id="2002", display_name="Bob", avatar_url=None),
            _stat(user="2001", day=today, msgs=10, voice=1200, reacts_recv=2),
            _stat(user="2002", day=today, msgs=4, reacts_given=3),
            SocialEdgeDaily(
                guild_id="1001",
                source_user_id="2001",
                target_user_id="2002",
                channel_id="3001",
                stat_date=today,
                voice_seconds=600,
                voice_sessions=1,
                replies=2,
                reactions=3,
            ),
        ]
    )
    await db_session.commit()

    graph = await get_social_graph(db_session, "1001", days=1)

    assert [node.user_id for node in graph.nodes] == ["2001", "2002"]
    assert graph.nodes[0].display_name == "Alice"
    assert graph.nodes[0].message_count == 10
    assert graph.nodes[0].voice_seconds == 1200
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.source_user_id == "2001"
    assert edge.target_user_id == "2002"
    assert edge.voice_seconds == 600
    assert edge.voice_sessions == 1
    assert edge.replies == 2
    assert edge.reactions == 3
    assert edge.co_activity > 0
    assert edge.weight > 0


async def test_social_graph_infers_edges_from_same_channel_activity(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="2001", channel="3001", day=today, msgs=10),
            _stat(user="2002", channel="3001", day=today, voice=1200),
            _stat(user="2003", channel="9999", day=today, msgs=10),
        ]
    )
    await db_session.commit()

    graph = await get_social_graph(db_session, "1001", days=1)

    pair = {(edge.source_user_id, edge.target_user_id): edge for edge in graph.edges}
    assert ("2001", "2002") in pair
    assert pair[("2001", "2002")].co_activity > 0
    assert ("2001", "2003") not in pair


async def test_social_graph_includes_active_users_without_edges(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add(_stat(user="2001", day=today, msgs=10))
    await db_session.commit()

    graph = await get_social_graph(db_session, "1001", days=1)

    assert [node.user_id for node in graph.nodes] == ["2001"]
    assert graph.edges == []


async def test_social_graph_excludes_old_edges_and_excluded_users(
    db_session: AsyncSession,
) -> None:
    today = today_local()
    db_session.add_all(
        [
            _stat(user="2001", day=today, msgs=10),
            _stat(user="2002", day=today, msgs=10),
            _stat(user="2003", day=today, msgs=10),
            ExcludedUser(guild_id="1001", user_id="2003"),
            SocialEdgeDaily(
                guild_id="1001",
                source_user_id="2001",
                target_user_id="2002",
                channel_id="3001",
                stat_date=today - timedelta(days=10),
                voice_seconds=9999,
            ),
            SocialEdgeDaily(
                guild_id="1001",
                source_user_id="2001",
                target_user_id="2003",
                channel_id="3001",
                stat_date=today,
                replies=99,
            ),
        ]
    )
    await db_session.commit()

    graph = await get_social_graph(db_session, "1001", days=1)

    assert {node.user_id for node in graph.nodes} == {"2001", "2002"}
    assert len(graph.edges) == 1
    assert graph.edges[0].source_user_id == "2001"
    assert graph.edges[0].target_user_id == "2002"
    assert graph.edges[0].voice_seconds == 0
    assert graph.edges[0].co_activity > 0
