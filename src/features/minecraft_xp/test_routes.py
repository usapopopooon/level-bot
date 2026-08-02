from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftXpDaily, MinecraftXpEvent
from src.features.leveling.service import get_user_lifetime_levels
from src.web import security
from src.web.app import app
from src.web.deps import get_db


@pytest_asyncio.fixture
async def minecraft_client(
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


def _payload(
    event_id: str, minecraft_xp: int, *, account: str = "mc-bot:1"
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "guild_id": "1001",
        "user_id": "2001",
        "minecraft_account_id": account,
        "minecraft_xp": minecraft_xp,
        "observed_at": "2026-08-01T15:00:00Z",
    }


async def _post(
    client: AsyncClient,
    event_id: str,
    minecraft_xp: int,
    *,
    account: str = "mc-bot:1",
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/integrations/minecraft/xp-events",
        headers={"Authorization": "Bearer minecraft-secret"},
        json=_payload(event_id, minecraft_xp, account=account),
    )
    assert response.status_code == 200
    data: dict[str, Any] = response.json()
    return data


async def test_accumulates_raw_xp_before_awarding(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    first = await _post(minecraft_client, "event-1", 40)
    second = await _post(minecraft_client, "event-2", 60)

    assert first["awarded_xp"] == 0
    assert second["awarded_xp"] == 1
    assert second["daily_awarded_xp"] == 1
    daily = (await db_session.execute(select(MinecraftXpDaily))).scalar_one()
    assert daily.minecraft_xp == 100
    assert daily.awarded_xp == 1
    assert daily.stat_date.isoformat() == "2026-08-02"


async def test_duplicate_event_is_idempotent(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    first = await _post(minecraft_client, "same-event", 500)
    duplicate = await _post(minecraft_client, "same-event", 500)

    assert first["awarded_xp"] == 5
    assert first["duplicate"] is False
    assert duplicate["awarded_xp"] == 5
    assert duplicate["duplicate"] is True
    assert (
        len((await db_session.execute(select(MinecraftXpEvent))).scalars().all()) == 1
    )
    daily = (await db_session.execute(select(MinecraftXpDaily))).scalar_one()
    assert daily.minecraft_xp == 500
    assert daily.awarded_xp == 5


async def test_duplicate_event_uses_original_identity_and_date(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _post(minecraft_client, "same-identity-event", 500)
    changed = _payload("same-identity-event", 9_999, account="mc-bot:other")
    changed["user_id"] = "2999"
    changed["observed_at"] = "2026-08-03T15:00:00Z"

    response = await minecraft_client.post(
        "/api/v1/integrations/minecraft/xp-events",
        headers={"Authorization": "Bearer minecraft-secret"},
        json=changed,
    )

    assert response.status_code == 200
    assert response.json()["minecraft_xp"] == 500
    assert response.json()["duplicate"] is True
    daily_rows = (await db_session.execute(select(MinecraftXpDaily))).scalars().all()
    assert len(daily_rows) == 1
    assert daily_rows[0].user_id == "2001"


async def test_daily_award_is_capped_at_100(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    capped = await _post(minecraft_client, "event-cap", 20_000)
    extra = await _post(minecraft_client, "event-extra", 1_000)

    assert capped["awarded_xp"] == 100
    assert capped["daily_awarded_xp"] == 100
    assert extra["awarded_xp"] == 0
    assert extra["daily_awarded_xp"] == 100
    levels = await get_user_lifetime_levels(db_session, "1001", "2001")
    assert levels is not None
    assert levels.total.xp == 100
    assert levels.total.level == 1


async def test_multiple_minecraft_accounts_share_user_daily_limit(
    minecraft_client: AsyncClient,
) -> None:
    first = await _post(minecraft_client, "account-one", 6_000, account="mc-bot:1")
    second = await _post(minecraft_client, "account-two", 6_000, account="mc-bot:2")

    assert first["awarded_xp"] == 60
    assert second["awarded_xp"] == 40
    assert second["daily_awarded_xp"] == 100


async def test_rejects_wrong_minecraft_api_key(
    minecraft_client: AsyncClient,
) -> None:
    response = await minecraft_client.post(
        "/api/v1/integrations/minecraft/xp-events",
        headers={"Authorization": "Bearer wrong"},
        json=_payload("event-rejected", 100),
    )

    assert response.status_code == 401


async def test_requires_timezone_aware_observation(
    minecraft_client: AsyncClient,
) -> None:
    payload = _payload("event-naive", 100)
    payload["observed_at"] = datetime(2026, 8, 2, 0, 0).isoformat()
    response = await minecraft_client.post(
        "/api/v1/integrations/minecraft/xp-events",
        headers={"Authorization": "Bearer minecraft-secret"},
        json=payload,
    )

    assert response.status_code == 422
