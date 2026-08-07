from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftWoodcuttingComboEvent, MinecraftXpDaily
from src.web import security
from src.web.app import app
from src.web.deps import get_db


@pytest_asyncio.fixture
async def woodcutting_client(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(security, "MINECRAFT_API_KEY", "minecraft-secret")
    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


def _payload(event_id: str = "wood-account-1-log-5") -> dict[str, object]:
    return {
        "event_id": event_id,
        "guild_id": "1001",
        "user_id": "2001",
        "minecraft_account_id": "mc-bot:1",
        "log_count": 105,
        "combo_count": 5,
        "reward_xp": 2,
        "observed_at": "2026-08-11T00:00:00Z",
    }


async def test_records_woodcutting_reward_without_awarding_server_xp(
    woodcutting_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer minecraft-secret"}
    first = await woodcutting_client.post(
        "/api/v1/integrations/minecraft/woodcutting-combo-events",
        headers=headers,
        json=_payload(),
    )
    duplicate = await woodcutting_client.post(
        "/api/v1/integrations/minecraft/woodcutting-combo-events",
        headers=headers,
        json=_payload(),
    )
    assert first.status_code == 200
    assert first.json() == {
        "event_id": "wood-account-1-log-5",
        "log_count": 105,
        "combo_count": 5,
        "reward_xp": 2,
        "duplicate": False,
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    events = (
        (await db_session.execute(select(MinecraftWoodcuttingComboEvent)))
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert (await db_session.execute(select(MinecraftXpDaily))).scalars().all() == []


async def test_rejects_reusing_woodcutting_event_id_for_different_reward(
    woodcutting_client: AsyncClient,
) -> None:
    headers = {"Authorization": "Bearer minecraft-secret"}
    first = await woodcutting_client.post(
        "/api/v1/integrations/minecraft/woodcutting-combo-events",
        headers=headers,
        json=_payload(),
    )
    changed = _payload()
    changed["reward_xp"] = 10
    conflict = await woodcutting_client.post(
        "/api/v1/integrations/minecraft/woodcutting-combo-events",
        headers=headers,
        json=changed,
    )
    assert first.status_code == 200
    assert conflict.status_code == 422


async def test_requires_minecraft_api_key(woodcutting_client: AsyncClient) -> None:
    response = await woodcutting_client.post(
        "/api/v1/integrations/minecraft/woodcutting-combo-events",
        json=_payload(),
    )
    assert response.status_code == 401
