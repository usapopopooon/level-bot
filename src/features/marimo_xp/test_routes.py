from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MarimoXpEvent, MarimoXpSpend
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


async def test_revival_spend_is_idempotent_and_reduces_current_xp(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer marimo-secret"}
    for index in range(3):
        award = _payload(event_id=f"watering-for-revival-{index}")
        award["user_id"] = "21"
        award["awarded_xp"] = 1000
        response = await api_client.post(
            "/api/v1/integrations/marimo/watering-events",
            json=award,
            headers=headers,
        )
        assert response.status_code == 200
    extra_award = _payload(event_id="watering-for-revival-extra")
    extra_award["user_id"] = "21"
    extra_award["awarded_xp"] = 500
    assert (
        await api_client.post(
            "/api/v1/integrations/marimo/watering-events",
            json=extra_award,
            headers=headers,
        )
    ).is_success

    payload = {
        "event_id": "00000000-0000-4000-8000-000000000099",
        "guild_id": "1001",
        "user_id": "21",
        "channel_id": "2001",
        "observed_at": datetime(2026, 8, 11, 1, 0, tzinfo=UTC).isoformat(),
    }
    endpoint = "/api/v1/integrations/marimo/revival-spends"
    first = await api_client.post(endpoint, json=payload, headers=headers)
    duplicate = await api_client.post(endpoint, json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json() == {
        "event_id": payload["event_id"],
        "status": "charged",
        "cost_xp": 3000,
        "remaining_xp": 500,
        "duplicate": False,
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    count = (
        await db_session.execute(select(func.count()).select_from(MarimoXpSpend))
    ).scalar_one()
    assert count == 1
    levels = await get_user_lifetime_levels(db_session, "1001", "21")
    assert levels is not None
    assert levels.total.xp == 500
    leaderboard = await get_level_leaderboard(
        db_session, "1001", axis="total", limit=10, offset=0
    )
    assert next(entry.xp for entry in leaderboard if entry.user_id == "21") == 500

    insufficient_payload = {**payload, "event_id": "another-revival"}
    insufficient = await api_client.post(
        endpoint, json=insufficient_payload, headers=headers
    )
    insufficient_duplicate = await api_client.post(
        endpoint, json=insufficient_payload, headers=headers
    )
    assert insufficient.status_code == 200
    assert insufficient.json() == {
        "event_id": "another-revival",
        "status": "insufficient_xp",
        "cost_xp": 3000,
        "remaining_xp": 500,
        "duplicate": False,
    }
    assert insufficient_duplicate.status_code == 200
    assert insufficient_duplicate.json()["status"] == "insufficient_xp"
    assert insufficient_duplicate.json()["duplicate"] is True
    levels_after_decline = await get_user_lifetime_levels(db_session, "1001", "21")
    assert levels_after_decline is not None
    assert levels_after_decline.total.xp == 500
    spends = (
        (await db_session.execute(select(MarimoXpSpend).order_by(MarimoXpSpend.id)))
        .scalars()
        .all()
    )
    assert [(spend.status, spend.cost_xp) for spend in spends] == [
        ("charged", 3000),
        ("declined", 3000),
    ]


async def test_revival_spend_rejects_event_collision(
    api_client: AsyncClient,
) -> None:
    headers = {"Authorization": "Bearer marimo-secret"}
    for index in range(3):
        award = _payload(event_id=f"collision-award-{index}")
        award["user_id"] = "31"
        award["awarded_xp"] = 1000
        assert (
            await api_client.post(
                "/api/v1/integrations/marimo/watering-events",
                json=award,
                headers=headers,
            )
        ).is_success
    endpoint = "/api/v1/integrations/marimo/revival-spends"
    payload = {
        "event_id": "collision-revival",
        "guild_id": "1001",
        "user_id": "31",
        "channel_id": "2001",
        "observed_at": datetime(2026, 8, 11, 1, 0, tzinfo=UTC).isoformat(),
    }
    assert (await api_client.post(endpoint, json=payload, headers=headers)).is_success
    collision = await api_client.post(
        endpoint,
        json={**payload, "channel_id": "2002"},
        headers=headers,
    )
    assert collision.status_code == 422
