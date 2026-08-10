from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MarimoXpEvent
from src.features.leveling.service import (
    get_level_leaderboard,
    get_user_lifetime_levels,
)
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
def marimo_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "MARIMO_BOT_API_TOKEN", "marimo-secret")


def _payload(*, event_id: str = "marimo:1001:11:2026-08-10") -> dict[str, object]:
    return {
        "event_id": event_id,
        "guild_id": "1001",
        "user_id": "11",
        "channel_id": "2001",
        "awarded_xp": 5,
        "observed_at": datetime(2026, 8, 10, 1, 0, tzinfo=UTC).isoformat(),
    }


async def test_records_once_and_adds_bonus_to_levels_and_leaderboard(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer marimo-secret"}
    first = await api_client.post(
        "/api/v1/integrations/marimo/watering-events",
        json=_payload(),
        headers=headers,
    )
    duplicate = await api_client.post(
        "/api/v1/integrations/marimo/watering-events",
        json=_payload(),
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json() == {
        "event_id": "marimo:1001:11:2026-08-10",
        "awarded_xp": 5,
        "duplicate": False,
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    count = (
        await db_session.execute(select(func.count()).select_from(MarimoXpEvent))
    ).scalar_one()
    assert count == 1

    levels = await get_user_lifetime_levels(db_session, "1001", "11")
    assert levels is not None
    assert levels.bonus_total_xp == 5
    assert levels.total.xp == 5
    leaderboard = await get_level_leaderboard(
        db_session, "1001", axis="total", limit=10, offset=0
    )
    assert [(entry.user_id, entry.xp) for entry in leaderboard] == [("11", 5)]


async def test_rejects_wrong_token_invalid_payload_and_event_collision(
    api_client: AsyncClient,
) -> None:
    endpoint = "/api/v1/integrations/marimo/watering-events"
    wrong_token = await api_client.post(
        endpoint,
        json=_payload(),
        headers={"Authorization": "Bearer wrong"},
    )
    naive = _payload(event_id="naive")
    naive["observed_at"] = "2026-08-10T10:00:00"
    invalid_time = await api_client.post(
        endpoint,
        json=naive,
        headers={"Authorization": "Bearer marimo-secret"},
    )
    headers = {"Authorization": "Bearer marimo-secret"}
    assert (
        await api_client.post(endpoint, json=_payload(), headers=headers)
    ).is_success
    changed = _payload()
    changed["user_id"] = "12"
    collision = await api_client.post(endpoint, json=changed, headers=headers)

    assert wrong_token.status_code == 401
    assert invalid_time.status_code == 422
    assert collision.status_code == 422
