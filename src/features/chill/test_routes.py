from collections.abc import AsyncIterator
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ColorRoleExchange, DailyStat
from src.features.chill import service as chill_service
from src.features.meta.service import upsert_guild_member_meta
from src.web import security
from src.web.app import app
from src.web.deps import get_db
from src.web.jwt_auth import create_jwt_token


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session", create_jwt_token("tester"))
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def bearer_client(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(security, "CHILL_API_KEY", "chill-secret")
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _seed_level(
    db_session: AsyncSession,
    *,
    message_count: int = 500,
) -> None:
    await upsert_guild_member_meta(
        db_session,
        guild_id="1001",
        user_id="2001",
        is_active=True,
    )
    db_session.add(
        DailyStat(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            stat_date=date(2026, 7, 4),
            message_count=message_count,
        )
    )
    await db_session.commit()


async def test_get_user_chill_places(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_level(db_session)

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/chill-places")

    assert resp.status_code == 200
    body = resp.json()
    assert body["level"]["level"] >= 1
    assert body["places"][0]["required_level"] == 1
    assert "choice_label" in body["places"][0]
    assert body["chill_place"]["current"]["required_level"] == max(
        place["required_level"] for place in body["places"]
    )


async def test_put_user_chill_place(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_level(db_session)

    resp = await api_client.put(
        "/api/v1/guilds/1001/users/2001/chill-place",
        json={"required_level": 1},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["selected"]["required_level"] == 1
    assert body["chill_place"]["current"]["required_level"] == 1


async def test_get_user_chill_places_keeps_selected_place_after_level_drop(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_level(db_session, message_count=800)
    await chill_service.set_user_chill_place(db_session, "1001", "2001", 8)
    db_session.add(
        ColorRoleExchange(
            guild_id="1001",
            user_id="2001",
            role_id="3002",
            cost_xp=1000,
        )
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/chill-places")

    assert resp.status_code == 200
    body = resp.json()
    assert body["level"]["level"] < 8
    assert body["selected_required_level"] == 8
    assert body["chill_place"]["current"]["required_level"] == 8
    assert body["chill_place"]["next"]["required_level"] == 8
    assert body["chill_place"]["selected_locked"] is True
    assert all(
        place["required_level"] <= body["level"]["level"] for place in body["places"]
    )


async def test_bearer_can_write_chill_override(bearer_client: AsyncClient) -> None:
    resp = await bearer_client.put(
        "/api/v1/guilds/1001/chill-places/2",
        headers={"Authorization": "Bearer chill-secret"},
        json={"name": "秘密のロビー", "emoji": "✨"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "guild_id": "1001",
        "required_level": 2,
        "name": "秘密のロビー",
        "emoji": "✨",
    }


async def test_invalid_bearer_cannot_write_chill_override(
    bearer_client: AsyncClient,
) -> None:
    resp = await bearer_client.put(
        "/api/v1/guilds/1001/chill-places/2",
        headers={"Authorization": "Bearer wrong"},
        json={"name": "秘密のロビー"},
    )

    assert resp.status_code == 401
