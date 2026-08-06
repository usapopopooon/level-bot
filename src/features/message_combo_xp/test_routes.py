from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, MessageComboXpEvent
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
def combo_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "ITSUKA_BOT_API_TOKEN", "itsuka-secret")


def _payload(
    *, event_id: str = "itsuka:10:100", streak_days: int = 5
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "guild_id": "1001",
        "user_id": "11",
        "channel_id": "2001",
        "config_id": "10",
        "streak_days": streak_days,
        "observed_at": datetime(2026, 8, 7, 1, 0, tzinfo=UTC).isoformat(),
    }


async def test_awards_server_defined_combo_xp_once(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer itsuka-secret"}
    first = await api_client.post(
        "/api/v1/integrations/itsuka/message-combo-xp-events",
        json=_payload(),
        headers=headers,
    )
    duplicate = await api_client.post(
        "/api/v1/integrations/itsuka/message-combo-xp-events",
        json=_payload(),
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json() == {
        "event_id": "itsuka:10:100",
        "streak_days": 5,
        "awarded_xp": 100,
        "duplicate": False,
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["awarded_xp"] == 100
    assert duplicate.json()["streak_days"] == 5
    assert duplicate.json()["duplicate"] is True
    event = (await db_session.execute(select(MessageComboXpEvent))).scalar_one()
    stat = (await db_session.execute(select(DailyStat))).scalar_one()
    assert event.awarded_xp == 100
    assert stat.message_combo_xp == 100

    collision = await api_client.post(
        "/api/v1/integrations/itsuka/message-combo-xp-events",
        json=_payload(streak_days=20),
        headers=headers,
    )
    assert collision.status_code == 422


async def test_rejects_non_rewarded_streak_and_wrong_token(
    api_client: AsyncClient,
) -> None:
    invalid_streak = await api_client.post(
        "/api/v1/integrations/itsuka/message-combo-xp-events",
        json=_payload(streak_days=4),
        headers={"Authorization": "Bearer itsuka-secret"},
    )
    wrong_token = await api_client.post(
        "/api/v1/integrations/itsuka/message-combo-xp-events",
        json=_payload(),
        headers={"Authorization": "Bearer wrong"},
    )

    assert invalid_streak.status_code == 422
    assert wrong_token.status_code == 401


async def test_requires_timezone_aware_observed_at(api_client: AsyncClient) -> None:
    payload = _payload()
    payload["observed_at"] = "2026-08-07T10:00:00"
    response = await api_client.post(
        "/api/v1/integrations/itsuka/message-combo-xp-events",
        json=payload,
        headers={"Authorization": "Bearer itsuka-secret"},
    )

    assert response.status_code == 422
