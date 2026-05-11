"""HTTP-level smoke tests for the leveling route.

`AsyncClient + ASGITransport` で `get_db` を差し替えて Postgres に対して叩く。
"""

from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat
from src.features.leveling.service import ACTIVITY_RATE_WINDOW_DAYS
from src.features.meta.service import upsert_user_meta
from src.utils import today_local
from src.web.app import app
from src.web.deps import get_db


def _seed_full_activity_window(
    db_session: AsyncSession,
    *,
    guild_id: str = "1001",
    user_id: str = "2001",
    channel_id: str = "3001",
    message_count_per_day: int = 0,
    voice_seconds_per_day: int = 0,
    reactions_received_per_day: int = 0,
    reactions_given_per_day: int = 0,
) -> None:
    """activity_rate=1.0 にするため直近 N 日に均等に活動を埋める。"""
    today = today_local()
    for i in range(ACTIVITY_RATE_WINDOW_DAYS):
        db_session.add(
            DailyStat(
                guild_id=guild_id,
                user_id=user_id,
                channel_id=channel_id,
                stat_date=today - timedelta(days=i),
                message_count=message_count_per_day,
                voice_seconds=voice_seconds_per_day,
                reactions_received=reactions_received_per_day,
                reactions_given=reactions_given_per_day,
            )
        )


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """テスト用 db_session を差し込んだ AsyncClient。"""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_levels_lifetime_aggregates_all_axes(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """30 日連続活動で activity_rate=1.0、各 axis に XP が乗り total が一致する。"""
    _seed_full_activity_window(
        db_session,
        message_count_per_day=2,  # 30 日で 60 msg × 2 = 120 XP
        voice_seconds_per_day=200,  # 30 日で 6000 sec = 100 min × 1 = 100 XP
        reactions_received_per_day=4,  # 30 日で 120 × 0.5 = 60 XP
        reactions_given_per_day=4,  # 同上 = 60 XP
    )
    await db_session.commit()
    await upsert_user_meta(
        db_session, user_id="2001", display_name="u", avatar_url=None, is_bot=False
    )

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["activity_rate"] == 1.0
    assert body["activity_rate_window_days"] == ACTIVITY_RATE_WINDOW_DAYS
    assert body["voice"]["xp"] == 100
    assert body["text"]["xp"] == 120
    assert body["reactions_received"]["xp"] == 60
    assert body["reactions_given"]["xp"] == 60
    # axis 合計が total と完全一致 (丸めズレ無し)
    assert body["total"]["xp"] == (
        body["voice"]["xp"]
        + body["text"]["xp"]
        + body["reactions_received"]["xp"]
        + body["reactions_given"]["xp"]
    )


async def test_levels_returns_404_when_no_stats(api_client: AsyncClient) -> None:
    """ライフタイムに記録の無いユーザーは 404。"""
    resp = await api_client.get("/api/v1/guilds/1001/users/9999/levels")
    assert resp.status_code == 404


async def test_levels_with_days_uses_window(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """``?days=7`` で 7 日以前の行は集計対象外。activity_rate=1.0 を担保しつつ
    ``days=7`` の場合 7 日分のみが XP に乗ることを確認する。
    """
    # 30 日連続活動で rate=1.0、各日 message_count=2
    _seed_full_activity_window(db_session, message_count_per_day=2)
    await db_session.commit()

    # days=7: 直近 7 日分の合計 = 14 msg × 2 XP = 28 XP
    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["activity_rate"] == 1.0
    assert body["text"]["xp"] == 28


async def test_levels_with_days_returns_zero_for_inactive_user(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """期間内に活動の無いユーザーは 404 でなく L0 を返す (window はゼロ許容)。"""
    db_session.add(
        DailyStat(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            stat_date=date(2020, 1, 1),  # 遥か昔
            message_count=100,
        )
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"]["level"] == 0
    assert body["total"]["xp"] == 0


async def test_activity_rate_decay_reduces_xp(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """1 日だけ活動 → rate ≈ 1/30 → 大きな raw XP も大幅に減衰される。"""
    today = today_local()
    db_session.add(
        DailyStat(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            stat_date=today,
            message_count=150,  # raw 300 XP
        )
    )
    await db_session.commit()
    await upsert_user_meta(
        db_session, user_id="2001", display_name="u", avatar_url=None, is_bot=False
    )

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels")
    assert resp.status_code == 200
    body = resp.json()
    # rate = 1/30、text raw 300 → 300 * (1/30) = 10 XP
    assert body["activity_rate"] == 1 / ACTIVITY_RATE_WINDOW_DAYS
    assert body["text"]["xp"] == 10
