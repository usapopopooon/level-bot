from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    DailyStat,
    Guild,
    MinecraftItemGachaSpend,
    MinecraftLevelUpEvent,
    MinecraftMaterialBuyback,
    MinecraftResourceExchange,
    MinecraftVoicePresence,
    MinecraftXpDaily,
    MinecraftXpEvent,
    MinecraftXpExchange,
    UserMeta,
    VoiceSession,
)
from src.features.leveling.service import get_user_lifetime_levels
from src.features.minecraft_resource_shop import service as resource_shop_service
from src.features.minecraft_xp.service import finalize_minecraft_voice_bonus
from src.features.minecraft_xp_shop.service import request_exchange
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


async def test_minecraft_bot_claims_and_completes_xp_exchange(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    db_session.add(
        MinecraftVoicePresence(
            guild_id="1001",
            user_id="2001",
            minecraft_account_id="mc-bot:1",
            last_seen_at=now,
            bonus_cursor_at=now,
        )
    )
    await db_session.commit()
    requested = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="2001",
        request_id="00000000-0000-4000-8000-000000000010",
        cost_xp=10,
        expected_reward_xp=50,
        total_xp=100,
        now=now,
    )
    assert requested.exchange_id is not None
    headers = {"Authorization": "Bearer minecraft-secret"}

    listed = await minecraft_client.get(
        "/api/v1/integrations/minecraft/xp-exchanges",
        headers=headers,
        params={"guild_id": "1001"},
    )
    claimed = await minecraft_client.post(
        f"/api/v1/integrations/minecraft/xp-exchanges/{requested.exchange_id}/claim",
        headers=headers,
        json={"guild_id": "1001", "claim_token": "worker-one"},
    )
    completed = await minecraft_client.post(
        f"/api/v1/integrations/minecraft/xp-exchanges/{requested.exchange_id}/complete",
        headers=headers,
        json={"guild_id": "1001", "claim_token": "worker-one"},
    )

    assert listed.status_code == 200
    assert listed.json()[0]["event_id"]
    assert listed.json()[0]["status"] == "pending"
    assert claimed.status_code == 204
    assert completed.status_code == 204
    exchange = await db_session.get(MinecraftXpExchange, requested.exchange_id)
    assert exchange is not None
    assert exchange.status == "completed"


async def test_minecraft_bot_reserves_and_completes_material_buyback(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer minecraft-secret"}
    request_id = "00000000-0000-4000-8000-000000000053"
    payload = {
        "request_id": request_id,
        "guild_id": "1001",
        "user_id": "2001",
        "minecraft_account_id": "mc-bot:1",
        "item_id": "minecraft:tuff",
        "item_count": 256,
        "expected_reward_xp": 160,
    }

    requested = await minecraft_client.post(
        "/api/v1/integrations/minecraft/material-buybacks",
        headers=headers,
        json=payload,
    )
    duplicate = await minecraft_client.post(
        "/api/v1/integrations/minecraft/material-buybacks",
        headers=headers,
        json=payload,
    )
    completed = await minecraft_client.post(
        f"/api/v1/integrations/minecraft/material-buybacks/{request_id}/complete",
        headers=headers,
        json={"guild_id": "1001", "user_id": "2001"},
    )

    assert requested.status_code == 200
    assert requested.json()["status"] == "reserved"
    assert requested.json()["daily_limit_xp"] == 1_500
    assert duplicate.status_code == 409
    assert duplicate.json()["duplicate"] is True
    assert completed.status_code == 204
    buyback = (
        await db_session.execute(
            select(MinecraftMaterialBuyback).where(
                MinecraftMaterialBuyback.event_id == request_id
            )
        )
    ).scalar_one()
    assert buyback.status == "completed"


async def test_minecraft_bot_reads_shop_and_requests_exchange_for_user(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _post(minecraft_client, "shop-earned-xp", 10_000)
    now = datetime.now(UTC)
    db_session.add(
        MinecraftVoicePresence(
            guild_id="1001",
            user_id="2001",
            minecraft_account_id="mc-bot:1",
            last_seen_at=now,
            bonus_cursor_at=now,
        )
    )
    await db_session.commit()
    headers = {"Authorization": "Bearer minecraft-secret"}

    shop = await minecraft_client.get(
        "/api/v1/integrations/minecraft/xp-shop",
        headers=headers,
        params={"guild_id": "1001", "user_id": "2001"},
    )
    exchange_payload = {
        "request_id": "00000000-0000-4000-8000-000000000011",
        "guild_id": "1001",
        "user_id": "2001",
        "cost_xp": 10,
        "expected_reward_xp": 50,
    }
    exchanged = await minecraft_client.post(
        "/api/v1/integrations/minecraft/xp-shop/exchanges",
        headers=headers,
        json=exchange_payload,
    )
    retried = await minecraft_client.post(
        "/api/v1/integrations/minecraft/xp-shop/exchanges",
        headers=headers,
        json=exchange_payload,
    )

    assert shop.status_code == 200
    assert shop.json() == {
        "wallet": {"total_xp": 100, "spent_xp": 0, "available_xp": 100},
        "packs": [
            {"cost_xp": 10, "reward_xp": 50},
            {"cost_xp": 50, "reward_xp": 250},
            {"cost_xp": 100, "reward_xp": 500},
            {"cost_xp": 1_000, "reward_xp": 5_000},
        ],
    }
    assert exchanged.status_code == 200
    assert exchanged.json()["status"] == "reserved"
    assert exchanged.json()["wallet_after"] == {
        "total_xp": 100,
        "spent_xp": 10,
        "available_xp": 90,
    }
    assert retried.status_code == 200
    assert retried.json()["status"] == "reserved"
    assert retried.json()["wallet_after"]["available_xp"] == 90
    exchanges = (await db_session.execute(select(MinecraftXpExchange))).scalars().all()
    assert len(exchanges) == 1


async def test_minecraft_bot_resource_shop_reserves_claims_and_completes_safely(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _post(minecraft_client, "resource-shop-earned-xp", 200_000)
    now = datetime.now(UTC)
    db_session.add(
        MinecraftVoicePresence(
            guild_id="1001",
            user_id="2001",
            minecraft_account_id="mc-bot:1",
            last_seen_at=now,
            bonus_cursor_at=now,
        )
    )
    await db_session.commit()
    headers = {"Authorization": "Bearer minecraft-secret"}

    shop = await minecraft_client.get(
        "/api/v1/integrations/minecraft/resource-shop",
        headers=headers,
        params={"guild_id": "1001", "user_id": "2001"},
    )
    payload = {
        "request_id": "00000000-0000-4000-8000-000000000012",
        "guild_id": "1001",
        "user_id": "2001",
        "item_id": "minecraft:emerald",
        "item_count": 4,
        "expected_cost_xp": 100,
    }
    exchanged = await minecraft_client.post(
        "/api/v1/integrations/minecraft/resource-shop/exchanges",
        headers=headers,
        json=payload,
    )
    retried = await minecraft_client.post(
        "/api/v1/integrations/minecraft/resource-shop/exchanges",
        headers=headers,
        json=payload,
    )
    tampered = await minecraft_client.post(
        "/api/v1/integrations/minecraft/resource-shop/exchanges",
        headers=headers,
        json={
            **payload,
            "request_id": "00000000-0000-4000-8000-000000000013",
            "expected_cost_xp": 1,
        },
    )
    monkeypatch.setattr(
        resource_shop_service,
        "MINECRAFT_RESOURCE_PACKS",
        (
            resource_shop_service.MinecraftResourcePack(
                "minecraft:emerald", "エメラルド", 4, 999
            ),
        ),
    )
    retried_after_rate_change = await minecraft_client.post(
        "/api/v1/integrations/minecraft/resource-shop/exchanges",
        headers=headers,
        json=payload,
    )

    assert shop.status_code == 200
    assert shop.json()["packs"] == [
        {
            "item_id": "minecraft:emerald",
            "item_name": "エメラルド",
            "item_count": 4,
            "cost_xp": 100,
        },
        {
            "item_id": "minecraft:emerald",
            "item_name": "エメラルド",
            "item_count": 16,
            "cost_xp": 360,
        },
        {
            "item_id": "minecraft:emerald",
            "item_name": "エメラルド",
            "item_count": 32,
            "cost_xp": 720,
        },
        {
            "item_id": "minecraft:emerald",
            "item_name": "エメラルド",
            "item_count": 64,
            "cost_xp": 1_440,
        },
        {
            "item_id": "minecraft:diamond",
            "item_name": "ダイヤモンド",
            "item_count": 1,
            "cost_xp": 720,
        },
        {
            "item_id": "minecraft:diamond",
            "item_name": "ダイヤモンド",
            "item_count": 3,
            "cost_xp": 2_160,
        },
        {
            "item_id": "minecraft:diamond",
            "item_name": "ダイヤモンド",
            "item_count": 8,
            "cost_xp": 5_760,
        },
        {
            "item_id": "minecraft:diamond",
            "item_name": "ダイヤモンド",
            "item_count": 16,
            "cost_xp": 11_520,
        },
        {
            "item_id": "minecraft:diamond",
            "item_name": "ダイヤモンド",
            "item_count": 32,
            "cost_xp": 23_040,
        },
        {
            "item_id": "minecraft:diamond",
            "item_name": "ダイヤモンド",
            "item_count": 64,
            "cost_xp": 46_080,
        },
    ]
    assert exchanged.json()["status"] == "reserved"
    assert exchanged.json()["wallet_after"]["available_xp"] == 1_900
    assert retried.json()["wallet_after"]["available_xp"] == 1_900
    assert retried_after_rate_change.json()["status"] == "reserved"
    assert retried_after_rate_change.json()["pack"]["cost_xp"] == 100
    assert tampered.json()["status"] == "unavailable"

    rows = (await db_session.execute(select(MinecraftResourceExchange))).scalars().all()
    assert len(rows) == 1
    exchange = rows[0]
    listed = await minecraft_client.get(
        "/api/v1/integrations/minecraft/resource-exchanges",
        headers=headers,
        params={"guild_id": "1001"},
    )
    claimed = await minecraft_client.post(
        f"/api/v1/integrations/minecraft/resource-exchanges/{exchange.id}/claim",
        headers=headers,
        json={"guild_id": "1001", "claim_token": "resource-worker"},
    )
    completed = await minecraft_client.post(
        f"/api/v1/integrations/minecraft/resource-exchanges/{exchange.id}/complete",
        headers=headers,
        json={"guild_id": "1001", "claim_token": "resource-worker"},
    )

    assert listed.json()[0]["item_id"] == "minecraft:emerald"
    assert claimed.status_code == 204
    assert completed.status_code == 204
    await db_session.refresh(exchange)
    assert exchange.status == "completed"


async def test_minecraft_item_gacha_reserves_and_completes_both_prices(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _post(minecraft_client, "item-gacha-earned-xp", 200_000)
    now = datetime.now(UTC)
    db_session.add(
        MinecraftVoicePresence(
            guild_id="1001",
            user_id="2001",
            minecraft_account_id="mc-bot:1",
            last_seen_at=now,
            bonus_cursor_at=now,
        )
    )
    await db_session.commit()
    headers = {"Authorization": "Bearer minecraft-secret"}
    request_id = "00000000-0000-4000-8000-000000000021"

    offer = await minecraft_client.get(
        "/api/v1/integrations/minecraft/item-gacha",
        headers=headers,
        params={"guild_id": "1001", "user_id": "2001"},
    )
    payload = {
        "request_id": request_id,
        "guild_id": "1001",
        "user_id": "2001",
        "minecraft_account_id": "mc-bot:1",
        "draw_day": "2026-08-15",
        "draw_category": "resources",
        "expected_cost_xp": 100,
    }
    reserved = await minecraft_client.post(
        "/api/v1/integrations/minecraft/item-gacha/spends",
        headers=headers,
        json=payload,
    )
    duplicate = await minecraft_client.post(
        "/api/v1/integrations/minecraft/item-gacha/spends",
        headers=headers,
        json=payload,
    )
    completed = await minecraft_client.post(
        f"/api/v1/integrations/minecraft/item-gacha/spends/{request_id}/complete",
        headers=headers,
        json={"guild_id": "1001", "user_id": "2001"},
    )
    premium_request_id = "00000000-0000-4000-8000-000000000022"
    premium_payload = {
        **payload,
        "request_id": premium_request_id,
        "draw_category": "equipment",
        "expected_cost_xp": 1_000,
    }
    premium_reserved = await minecraft_client.post(
        "/api/v1/integrations/minecraft/item-gacha/spends",
        headers=headers,
        json=premium_payload,
    )
    premium_completed = await minecraft_client.post(
        f"/api/v1/integrations/minecraft/item-gacha/spends/{premium_request_id}/complete",
        headers=headers,
        json={"guild_id": "1001", "user_id": "2001"},
    )
    offer_after = await minecraft_client.get(
        "/api/v1/integrations/minecraft/item-gacha",
        headers=headers,
        params={"guild_id": "1001", "user_id": "2001"},
    )
    levels_after = await get_user_lifetime_levels(db_session, "1001", "2001")

    assert offer.status_code == 200
    assert offer.json()["cost_xp"] == 100
    assert offer.json()["normal_cost_xp"] == 100
    assert offer.json()["premium_cost_xp"] == 1_000
    assert offer.json()["daily_limit"] == 3
    assert offer.json()["wallet"]["available_xp"] == 2_000
    assert reserved.status_code == 200
    assert reserved.json()["status"] == "reserved"
    assert reserved.json()["wallet_after"]["available_xp"] == 1_900
    assert duplicate.json()["wallet_after"]["available_xp"] == 1_900
    assert completed.status_code == 204
    assert premium_reserved.status_code == 200
    assert premium_reserved.json()["cost_xp"] == 1_000
    assert premium_reserved.json()["wallet_after"]["available_xp"] == 900
    assert premium_completed.status_code == 204
    assert offer_after.status_code == 200
    assert offer_after.json()["wallet"] == {
        "total_xp": 2_000,
        "spent_xp": 1_100,
        "available_xp": 900,
    }
    assert levels_after is not None
    assert levels_after.total.xp == 900
    spends = (
        (
            await db_session.execute(
                select(MinecraftItemGachaSpend).order_by(MinecraftItemGachaSpend.id)
            )
        )
        .scalars()
        .all()
    )
    assert [spend.cost_xp for spend in spends] == [100, 1_000]
    assert [spend.draw_category for spend in spends] == ["resources", "equipment"]
    assert all(spend.status == "completed" for spend in spends)


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


async def test_daily_award_has_no_upper_limit(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    first = await _post(minecraft_client, "event-large", 20_000)
    extra = await _post(minecraft_client, "event-extra", 1_000)

    assert first["awarded_xp"] == 200
    assert first["daily_awarded_xp"] == 200
    assert first["daily_limit"] is None
    assert extra["awarded_xp"] == 10
    assert extra["daily_awarded_xp"] == 210
    assert extra["daily_limit"] is None
    levels = await get_user_lifetime_levels(
        db_session, "1001", "2001", include_live_voice=False
    )
    assert levels is not None
    assert levels.total.xp == 210
    assert levels.total.level == 1


async def test_multiple_minecraft_accounts_have_no_shared_daily_limit(
    minecraft_client: AsyncClient,
) -> None:
    first = await _post(minecraft_client, "account-one", 6_000, account="mc-bot:1")
    second = await _post(minecraft_client, "account-two", 6_000, account="mc-bot:2")

    assert first["awarded_xp"] == 60
    assert second["awarded_xp"] == 60
    assert second["daily_awarded_xp"] == 120


async def test_voice_heartbeat_awards_only_continuous_vc_overlap(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer minecraft-secret"}
    baseline = {
        "guild_id": "1001",
        "user_id": "2001",
        "minecraft_account_id": "mc-bot:1",
        "observed_at": "2026-08-01T15:00:00Z",
    }
    first = await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers=headers,
        json=baseline,
    )
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime(2026, 8, 1, 15, 0, 10, tzinfo=UTC),
        )
    )
    await db_session.commit()
    second_payload = baseline | {"observed_at": "2026-08-01T15:01:10Z"}
    second = await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers=headers,
        json=second_payload,
    )
    duplicate = await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers=headers,
        json=second_payload,
    )

    assert first.json() == {
        "awarded_bonus_seconds": 0,
        "bonus_active": False,
        "duplicate": False,
    }
    assert second.json() == {
        "awarded_bonus_seconds": 60,
        "bonus_active": True,
        "duplicate": False,
    }
    assert duplicate.json() == {
        "awarded_bonus_seconds": 0,
        "bonus_active": True,
        "duplicate": True,
    }
    daily = (await db_session.execute(select(DailyStat))).scalar_one()
    assert daily.voice_seconds == 0
    assert daily.minecraft_voice_bonus_seconds == 60
    levels = await get_user_lifetime_levels(
        db_session, "1001", "2001", include_live_voice=False
    )
    assert levels is not None
    assert levels.voice.xp == 1
    presence = (await db_session.execute(select(MinecraftVoicePresence))).scalar_one()
    assert presence.last_seen_at == datetime(2026, 8, 1, 15, 1, 10, tzinfo=UTC)


async def test_voice_heartbeat_does_not_bridge_stale_gap(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        VoiceSession(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            joined_at=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()
    headers = {"Authorization": "Bearer minecraft-secret"}
    payload = {
        "guild_id": "1001",
        "user_id": "2001",
        "minecraft_account_id": "mc-bot:1",
        "observed_at": "2026-08-01T15:00:00Z",
    }
    await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers=headers,
        json=payload,
    )
    response = await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers=headers,
        json=payload | {"observed_at": "2026-08-01T15:02:00Z"},
    )

    assert response.json()["awarded_bonus_seconds"] == 0
    assert (await db_session.execute(select(DailyStat))).scalar_one_or_none() is None


async def test_voice_end_finalizes_tail_without_advancing_minecraft_presence(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    voice = VoiceSession(
        guild_id="1001",
        user_id="2001",
        channel_id="3001",
        joined_at=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
    )
    db_session.add(voice)
    await db_session.commit()
    headers = {"Authorization": "Bearer minecraft-secret"}
    payload = {
        "guild_id": "1001",
        "user_id": "2001",
        "minecraft_account_id": "mc-bot:1",
        "observed_at": "2026-08-01T15:00:00.900000Z",
    }
    await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers=headers,
        json=payload,
    )
    heartbeat = await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers=headers,
        json=payload | {"observed_at": "2026-08-01T15:00:30.900000Z"},
    )

    finalized = await finalize_minecraft_voice_bonus(
        db_session,
        voice=voice,
        ended_at=datetime(2026, 8, 1, 15, 0, 45, tzinfo=UTC),
    )

    assert heartbeat.json()["awarded_bonus_seconds"] == 30
    assert finalized == 15
    daily = (await db_session.execute(select(DailyStat))).scalar_one()
    assert daily.minecraft_voice_bonus_seconds == 45
    presence = (await db_session.execute(select(MinecraftVoicePresence))).scalar_one()
    assert presence.last_seen_at == datetime(2026, 8, 1, 15, 0, 30, tzinfo=UTC)
    assert presence.bonus_cursor_at == datetime(2026, 8, 1, 15, 0, 45, tzinfo=UTC)


async def test_voice_end_does_not_finalize_after_stale_minecraft_heartbeat(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    voice = VoiceSession(
        guild_id="1001",
        user_id="2001",
        channel_id="3001",
        joined_at=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
    )
    db_session.add(voice)
    await db_session.commit()
    await minecraft_client.post(
        "/api/v1/integrations/minecraft/voice-heartbeats",
        headers={"Authorization": "Bearer minecraft-secret"},
        json={
            "guild_id": "1001",
            "user_id": "2001",
            "minecraft_account_id": "mc-bot:1",
            "observed_at": "2026-08-01T15:00:00Z",
        },
    )

    finalized = await finalize_minecraft_voice_bonus(
        db_session,
        voice=voice,
        ended_at=datetime(2026, 8, 1, 15, 2, tzinfo=UTC),
    )

    assert finalized == 0
    assert (await db_session.execute(select(DailyStat))).scalar_one_or_none() is None


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


async def test_minecraft_xp_level_up_is_queued_with_discord_names(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(Guild(guild_id="1001", name="うさぽサーバー"))
    db_session.add(
        UserMeta(
            user_id="2001",
            display_name="うさぽ",
            avatar_url=None,
            is_bot=False,
        )
    )
    await db_session.commit()

    awarded = await _post(minecraft_client, "level-up-event", 10_000)
    response = await minecraft_client.get(
        "/api/v1/integrations/minecraft/level-up-events",
        headers={"Authorization": "Bearer minecraft-secret"},
        params={"guild_id": "1001"},
    )

    assert awarded["awarded_xp"] == 100
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "guild_id": "1001",
            "guild_name": "うさぽサーバー",
            "user_id": "2001",
            "display_name": "うさぽ",
            "level": 1,
            "minecraft_delivered": False,
            "discord_delivered": False,
        }
    ]

    ack = await minecraft_client.post(
        "/api/v1/integrations/minecraft/level-up-events/1/ack",
        headers={"Authorization": "Bearer minecraft-secret"},
        json={"guild_id": "1001", "destination": "minecraft"},
    )
    assert ack.status_code == 204
    event = (await db_session.execute(select(MinecraftLevelUpEvent))).scalar_one()
    assert event.minecraft_delivered_at is not None
    assert event.discord_delivered_at is None

    empty = await minecraft_client.get(
        "/api/v1/integrations/minecraft/level-up-events",
        headers={"Authorization": "Bearer minecraft-secret"},
        params={"guild_id": "1001"},
    )
    assert empty.json()[0]["minecraft_delivered"] is True
    assert empty.json()[0]["discord_delivered"] is False

    discord_ack = await minecraft_client.post(
        "/api/v1/integrations/minecraft/level-up-events/1/ack",
        headers={"Authorization": "Bearer minecraft-secret"},
        json={"guild_id": "1001", "destination": "discord"},
    )
    assert discord_ack.status_code == 204
    finished = await minecraft_client.get(
        "/api/v1/integrations/minecraft/level-up-events",
        headers={"Authorization": "Bearer minecraft-secret"},
        params={"guild_id": "1001"},
    )
    assert finished.json() == []


async def test_level_up_ack_is_scoped_to_discord_guild(
    minecraft_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(
        MinecraftLevelUpEvent(
            dedupe_key="1001:2001:2",
            guild_id="1001",
            user_id="2001",
            guild_name="うさぽサーバー",
            display_name="うさぽ",
            level=2,
        )
    )
    await db_session.commit()

    response = await minecraft_client.post(
        "/api/v1/integrations/minecraft/level-up-events/1/ack",
        headers={"Authorization": "Bearer minecraft-secret"},
        json={"guild_id": "9999", "destination": "minecraft"},
    )

    assert response.status_code == 404
