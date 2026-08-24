from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import CafeGachaDraw
from src.features.cafe_gacha import internal_routes
from src.features.feature_access import service as feature_access_service
from src.web import security
from src.web.app import app
from src.web.deps import get_db


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def cafe_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "CAFE_COLLECTION_API_TOKEN", "cafe-secret")


def _actor(*, role_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "guild_id": "1001",
        "user_id": "11",
        "role_ids": role_ids or [],
        "can_manage_guild": False,
    }


async def test_cafe_api_rejects_wrong_dedicated_token(
    api_client: AsyncClient,
) -> None:
    missing = await api_client.get("/api/v1/integrations/cafe-collection/capabilities")
    response = await api_client.get(
        "/api/v1/integrations/cafe-collection/capabilities",
        headers={"Authorization": "Bearer wrong"},
    )

    assert missing.status_code == 401
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid API key"}


async def test_cafe_api_draw_is_atomic_idempotent_and_visible_in_collection(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer cafe-secret"}
    availability = await api_client.post(
        "/api/v1/integrations/cafe-collection/draw-availability",
        json={"actor": _actor(), "count": 1},
        headers=headers,
    )
    payload = {
        "actor": _actor(),
        "event_id": "new-bot:interaction:5001",
        "display_name": "カフェ客",
        "count": 1,
        "expected_cost_xp": 0,
    }
    first = await api_client.post(
        "/api/v1/integrations/cafe-collection/draws",
        json=payload,
        headers=headers,
    )
    duplicate = await api_client.post(
        "/api/v1/integrations/cafe-collection/draws",
        json=payload,
        headers=headers,
    )
    collection = await api_client.post(
        "/api/v1/integrations/cafe-collection/collection",
        json={"actor": _actor()},
        headers=headers,
    )

    assert availability.status_code == 200
    assert availability.json()["cost_xp"] == 0
    assert first.status_code == 200
    assert first.json()["status"] == "drawn"
    assert len(first.json()["draws"]) == 1
    assert duplicate.status_code == 200
    assert (
        duplicate.json()["draws"][0]["event_id"] == first.json()["draws"][0]["event_id"]
    )
    assert collection.status_code == 200
    owned = [card for card in collection.json()["cards"] if card["count"] > 0]
    assert [(card["key"], card["count"]) for card in owned] == [
        (first.json()["draws"][0]["reward_key"], 1)
    ]
    persisted = (
        await db_session.execute(
            select(CafeGachaDraw).where(
                CafeGachaDraw.batch_id == "new-bot:interaction:5001"
            )
        )
    ).scalar_one()
    assert persisted.ledger_message_id is None


async def test_cafe_api_returns_committed_draw_when_role_sync_request_fails(
    api_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    role_sync = AsyncMock(side_effect=SQLAlchemyError("role sync unavailable"))
    monkeypatch.setattr(internal_routes, "request_level_role_sync", role_sync)

    response = await api_client.post(
        "/api/v1/integrations/cafe-collection/draws",
        json={
            "actor": _actor(),
            "event_id": "new-bot:interaction:role-sync-failure",
            "display_name": "カフェ客",
            "count": 1,
            "expected_cost_xp": 0,
        },
        headers={"Authorization": "Bearer cafe-secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "drawn"
    role_sync.assert_awaited_once_with(db_session, "1001")
    persisted = (
        await db_session.execute(
            select(CafeGachaDraw).where(
                CafeGachaDraw.batch_id == "new-bot:interaction:role-sync-failure"
            )
        )
    ).scalar_one()
    assert persisted.user_id == "11"


async def test_cafe_api_enforces_level_bot_access_roles(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await feature_access_service.add_access_role(
        db_session,
        guild_id="1001",
        feature=feature_access_service.CAFE_GACHA,
        role_id="9001",
    )
    headers = {"Authorization": "Bearer cafe-secret"}
    denied = await api_client.post(
        "/api/v1/integrations/cafe-collection/collection",
        json={"actor": _actor()},
        headers=headers,
    )
    allowed = await api_client.post(
        "/api/v1/integrations/cafe-collection/collection",
        json={"actor": _actor(role_ids=["9001"])},
        headers=headers,
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200


async def test_cafe_capabilities_report_pinned_assets(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get(
        "/api/v1/integrations/cafe-collection/capabilities",
        headers={"Authorization": "Bearer cafe-secret"},
    )

    assert response.status_code == 200
    assert response.json()["api_version"] == 1
    assert response.json()["catalog_size"] == 361
    assert response.json()["asset_count"] == 363
    assert len(response.json()["asset_manifest_sha256"]) == 64
