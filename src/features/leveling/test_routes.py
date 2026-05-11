"""HTTP-level smoke tests for the leveling route.

`AsyncClient + ASGITransport` で `get_db` を差し替えて Postgres に対して叩く。
"""

from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat
from src.features.meta.service import upsert_user_meta
from src.utils import today_local
from src.web.app import app
from src.web.deps import get_db


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
    """lifetime 呼び出しで各 axis XP がレスポンスに乗る。"""
    today = today_local()
    db_session.add(
        DailyStat(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            stat_date=today,
            message_count=50,  # 50 * 2 = 100 XP → text L1
            voice_seconds=60 * 100,  # 100 分 = 100 XP → voice L1
            reactions_received=200,  # 200 * 0.5 = 100 XP → r_recv L1
            reactions_given=200,  # 200 * 0.5 = 100 XP → r_given L1
        )
    )
    await db_session.commit()
    await upsert_user_meta(
        db_session, user_id="2001", display_name="u", avatar_url=None, is_bot=False
    )

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["voice"]["level"] == 1
    assert body["text"]["level"] == 1
    assert body["reactions_received"]["level"] == 1
    assert body["reactions_given"]["level"] == 1
    # 4 axis 合計 = 400 XP → total L3 (累積 364 で L3、484 で L4)
    assert body["total"]["xp"] == 400
    assert body["total"]["level"] == 3
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
    """``?days=7`` で 7 日以前の行は集計対象外。"""
    today = today_local()
    db_session.add_all(
        [
            DailyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=today,
                message_count=50,  # 100 XP (in window)
            ),
            DailyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=today - timedelta(days=30),
                message_count=1000,  # 2000 XP (out of window)
            ),
        ]
    )
    await db_session.commit()

    resp = await api_client.get(
        "/api/v1/guilds/1001/users/2001/levels?days=7"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"]["xp"] == 100
    assert body["text"]["level"] == 1


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

    resp = await api_client.get(
        "/api/v1/guilds/1001/users/2001/levels?days=30"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"]["level"] == 0
    assert body["total"]["xp"] == 0
