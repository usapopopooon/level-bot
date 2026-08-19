from collections.abc import AsyncIterator
from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, MinecraftMarketPurchase
from src.web import security
from src.web.app import app
from src.web.deps import get_db


@pytest_asyncio.fixture
async def market_client(
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


async def test_market_routes_report_balance_and_complete_exact_parties(
    market_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        DailyStat(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            stat_date=date(2026, 8, 24),
            message_count=1_000,
        )
    )
    await db_session.commit()
    headers = {"Authorization": "Bearer minecraft-secret"}
    payload = {
        "request_id": "00000000-0000-4000-8000-000000000043",
        "guild_id": "1001",
        "listing_id": 25,
        "buyer_user_id": "2001",
        "seller_user_id": "2002",
        "buyer_minecraft_account_id": "mc-bot:1",
        "seller_minecraft_account_id": "mc-bot:2",
        "expected_cost_xp": 1_500,
    }

    balance = await market_client.get(
        "/api/v1/integrations/minecraft/market/wallet",
        headers=headers,
        params={"guild_id": "1001", "user_id": "2001"},
    )
    reserved = await market_client.post(
        "/api/v1/integrations/minecraft/market/purchases",
        headers=headers,
        json=payload,
    )
    retried = await market_client.post(
        "/api/v1/integrations/minecraft/market/purchases",
        headers=headers,
        json=payload,
    )
    conflicted = await market_client.post(
        "/api/v1/integrations/minecraft/market/purchases",
        headers=headers,
        json={**payload, "expected_cost_xp": 1_400},
    )
    pending = await market_client.get(
        "/api/v1/integrations/minecraft/market/purchases",
        headers=headers,
        params={"guild_id": "1001"},
    )
    completed = await market_client.post(
        "/api/v1/integrations/minecraft/market/purchases/"
        "00000000-0000-4000-8000-000000000043/complete",
        headers=headers,
        json={"guild_id": "1001"},
    )

    assert balance.status_code == 200
    assert balance.json()["wallet"]["available_xp"] == 3_000
    assert reserved.status_code == 200
    assert reserved.json()["duplicate"] is False
    assert reserved.json()["wallet_after"]["available_xp"] == 1_500
    assert retried.status_code == 409
    assert retried.json()["status"] == "reserved"
    assert retried.json()["duplicate"] is True
    assert retried.json()["request_id"] == payload["request_id"]
    assert retried.json()["wallet_after"]["available_xp"] == 1_500
    assert conflicted.status_code == 409
    assert conflicted.json()["status"] == "conflict"
    assert conflicted.json()["duplicate"] is False
    assert pending.status_code == 200
    assert pending.json() == [
        {
            "request_id": payload["request_id"],
            "guild_id": "1001",
            "listing_id": 25,
            "buyer_user_id": "2001",
            "seller_user_id": "2002",
            "buyer_minecraft_account_id": "mc-bot:1",
            "seller_minecraft_account_id": "mc-bot:2",
            "cost_xp": 1_500,
        }
    ]
    assert completed.status_code == 204
    row = await db_session.get(MinecraftMarketPurchase, 1)
    assert row is not None and row.status == "completed"
