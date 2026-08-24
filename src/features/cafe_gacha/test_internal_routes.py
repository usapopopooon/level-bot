from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import CafeGachaDraw, CafeGachaRedemption
from src.features.cafe_gacha import internal_routes, service
from src.features.cafe_gacha.catalog import CARDS
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


def _actor(
    *,
    role_ids: list[str] | None = None,
    can_manage_guild: bool = False,
) -> dict[str, object]:
    return {
        "guild_id": "1001",
        "user_id": "11",
        "role_ids": role_ids or [],
        "can_manage_guild": can_manage_guild,
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
    assert collection.json()["endgame_pity_active"] is False
    assert collection.json()["endgame_pity_duplicate_draws"] == 100
    assert collection.json()["mastery_tiers"] == [
        {"name": "発見", "emoji": "🔎", "card_count": 1},
        {"name": "なじみ", "emoji": "☕", "card_count": 0},
        {"name": "常連", "emoji": "⭐", "card_count": 0},
        {"name": "看板メニュー", "emoji": "🏆", "card_count": 0},
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
    assert response.json()["api_version"] == 3
    assert response.json()["catalog_size"] == 361
    assert response.json()["asset_count"] == 363
    assert len(response.json()["asset_manifest_sha256"]) == 64
    assert response.json()["paid_draw_cost_xp"] == 20
    assert response.json()["hourly_draw_limit"] == 10


@pytest.mark.parametrize(
    ("owned", "expected"),
    [(165, False), (166, True), (360, True), (361, False)],
)
def test_endgame_pity_active_only_between_threshold_and_completion(
    owned: int,
    expected: bool,
) -> None:
    cards = tuple(
        service.CollectionCard(
            card=card,
            count=1 if index < owned else 0,
            redeemable_count=0,
            lifetime_count=1 if index < owned else 0,
        )
        for index, card in enumerate(CARDS)
    )

    assert internal_routes._endgame_pity_active(cards) is expected


async def test_cafe_bot_layout_requires_admin_and_preserves_other_placements(
    api_client: AsyncClient,
) -> None:
    headers = {"Authorization": "Bearer cafe-secret"}
    denied = await api_client.post(
        "/api/v1/integrations/cafe-collection/discord-layout/placements",
        json={
            "actor": _actor(),
            "placement": "panel",
            "channel_id": "3001",
            "message_id": "4001",
        },
        headers=headers,
    )
    panel = await api_client.post(
        "/api/v1/integrations/cafe-collection/discord-layout/placements",
        json={
            "actor": _actor(can_manage_guild=True),
            "placement": "panel",
            "channel_id": "3001",
            "message_id": "4001",
        },
        headers=headers,
    )
    ledger = await api_client.post(
        "/api/v1/integrations/cafe-collection/discord-layout/placements",
        json={
            "actor": _actor(can_manage_guild=True),
            "placement": "ledger",
            "channel_id": "3002",
            "message_id": "4002",
        },
        headers=headers,
    )
    current = await api_client.post(
        "/api/v1/integrations/cafe-collection/discord-layout",
        json={"actor": _actor(can_manage_guild=True)},
        headers=headers,
    )

    assert denied.status_code == 403
    assert panel.status_code == 200
    assert ledger.status_code == 200
    assert current.json() == {
        "panel_channel_id": "3001",
        "panel_message_id": "4001",
        "ledger_channel_id": "3002",
        "ledger_message_id": "4002",
        "ranking_channel_id": None,
        "ranking_message_id": None,
    }


async def test_each_bot_tracks_ledger_delivery_independently(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer cafe-secret"}
    configured = await api_client.post(
        "/api/v1/integrations/cafe-collection/discord-layout/placements",
        json={
            "actor": _actor(can_manage_guild=True),
            "placement": "ledger",
            "channel_id": "3002",
            "message_id": "4002",
        },
        headers=headers,
    )
    payload = {
        "actor": _actor(),
        "event_id": "dual-ledger-draw",
        "display_name": "カフェ客",
        "count": 1,
        "expected_cost_xp": 0,
    }
    first = await api_client.post(
        "/api/v1/integrations/cafe-collection/draws",
        json=payload,
        headers=headers,
    )
    retry = await api_client.post(
        "/api/v1/integrations/cafe-collection/draws",
        json=payload,
        headers=headers,
    )
    old_bot_delivery = (
        await db_session.execute(
            select(CafeGachaDraw).where(CafeGachaDraw.batch_id == "dual-ledger-draw")
        )
    ).scalar_one()
    old_bot_delivery.ledger_message_id = "5001"
    await db_session.commit()
    pending = await api_client.post(
        "/api/v1/integrations/cafe-collection/ledger/pending",
        json={"guild_id": "1001"},
        headers=headers,
    )

    assert configured.status_code == 200
    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json()["draws"] == first.json()["draws"]
    assert pending.status_code == 200
    assert pending.json()["ledger_channel_id"] == "3002"
    assert [item["event_id"] for item in pending.json()["draw_batches"]] == [
        "dual-ledger-draw"
    ]

    delivered = await api_client.post(
        "/api/v1/integrations/cafe-collection/ledger/delivered",
        json={
            "guild_id": "1001",
            "record_type": "draw",
            "event_id": "dual-ledger-draw",
            "message_id": "5002",
        },
        headers=headers,
    )
    empty = await api_client.post(
        "/api/v1/integrations/cafe-collection/ledger/pending",
        json={"guild_id": "1001"},
        headers=headers,
    )
    persisted = (
        await db_session.execute(
            select(CafeGachaDraw).where(CafeGachaDraw.batch_id == "dual-ledger-draw")
        )
    ).scalar_one()

    assert delivered.status_code == 200
    assert delivered.json() == {"delivered": True}
    assert empty.json()["draw_batches"] == []
    assert persisted.ledger_message_id == "5001"
    assert persisted.collection_bot_ledger_message_id == "5002"


async def test_pending_ledger_returns_only_complete_draw_batches_at_page_boundary(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": "Bearer cafe-secret"}
    configured = await api_client.post(
        "/api/v1/integrations/cafe-collection/discord-layout/placements",
        json={
            "actor": _actor(can_manage_guild=True),
            "placement": "ledger",
            "channel_id": "3002",
            "message_id": "4002",
        },
        headers=headers,
    )
    assert configured.status_code == 200

    card = CARDS[0]
    created_at = datetime.now(UTC)
    rows = []
    # 51 concurrent 10-draw batches can have interleaved row IDs. The pending
    # page must select 50 batch IDs first instead of cutting through card rows.
    for position in range(1, 11):
        for batch_index in range(51):
            batch_id = f"interleaved-{batch_index:02d}"
            rows.append(
                CafeGachaDraw(
                    event_id=f"{batch_id}:{position}",
                    batch_id=batch_id,
                    batch_position=position,
                    guild_id="1001",
                    user_id="11",
                    display_name="カフェ客",
                    draw_type="paid",
                    cost_xp=20,
                    reward_xp=30,
                    reward_key=card.key,
                    reward_name=card.name,
                    reward_description=card.description,
                    rarity=card.rarity,
                    image_filename=card.image_filename,
                    exchange_xp=card.exchange_xp,
                    was_duplicate=position > 1,
                    owned_count=position,
                    collected_count=1,
                    created_at=created_at,
                )
            )
    db_session.add_all(rows)
    await db_session.commit()

    pending = await api_client.post(
        "/api/v1/integrations/cafe-collection/ledger/pending",
        json={"guild_id": "1001"},
        headers=headers,
    )

    assert pending.status_code == 200
    batches = pending.json()["draw_batches"]
    assert [batch["event_id"] for batch in batches] == [
        f"interleaved-{index:02d}" for index in range(50)
    ]
    assert all(len(batch["draws"]) == 10 for batch in batches)
    assert all(
        [draw["batch_position"] for draw in batch["draws"]] == list(range(1, 11))
        for batch in batches
    )


async def test_cafe_rankings_include_draws_created_by_new_bot_api(
    api_client: AsyncClient,
) -> None:
    headers = {"Authorization": "Bearer cafe-secret"}
    draw = await api_client.post(
        "/api/v1/integrations/cafe-collection/draws",
        json={
            "actor": _actor(),
            "event_id": "new-bot:ranking-draw",
            "display_name": "カフェ客",
            "count": 1,
            "expected_cost_xp": 0,
        },
        headers=headers,
    )
    rankings = await api_client.post(
        "/api/v1/integrations/cafe-collection/rankings",
        json={"actor": _actor()},
        headers=headers,
    )

    assert draw.status_code == 200
    assert rankings.status_code == 200
    payload = rankings.json()
    assert payload["participant_count"] == 1
    collection = next(
        category
        for category in payload["categories"]
        if category["key"] == "collection"
    )
    assert collection["entries"][0]["user_id"] == "11"
    assert collection["entries"][0]["rank"] == 1
    assert collection["viewer_entry"]["user_id"] == "11"
    assert collection["viewer_entry"]["rank"] == 1


async def test_cafe_api_supports_full_collection_settings_and_idempotent_exchange(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    for index in range(2):
        result = await service.draw_card(
            db_session,
            event_id=f"full-parity-draw-{index}",
            guild_id="1001",
            user_id="11",
            display_name="カフェ客",
            earned_xp=1000,
            allow_paid=True,
            random_value=0,
        )
        assert result.status == "drawn"
    headers = {"Authorization": "Bearer cafe-secret"}
    before = await api_client.post(
        "/api/v1/integrations/cafe-collection/collection",
        json={"actor": _actor()},
        headers=headers,
    )
    owned = next(card for card in before.json()["cards"] if card["count"] == 2)
    favorite = await api_client.post(
        "/api/v1/integrations/cafe-collection/favorite",
        json={"actor": _actor(), "reward_key": owned["key"]},
        headers=headers,
    )
    protection = await api_client.post(
        "/api/v1/integrations/cafe-collection/protection",
        json={
            "actor": _actor(),
            "reward_key": owned["key"],
            "protected": True,
        },
        headers=headers,
    )
    await api_client.post(
        "/api/v1/integrations/cafe-collection/protection",
        json={
            "actor": _actor(),
            "reward_key": owned["key"],
            "protected": False,
        },
        headers=headers,
    )
    redemption_payload = {
        "actor": _actor(),
        "event_id": "cafe-bot:redemption:8001",
        "display_name": "カフェ客",
        "quantities": {owned["key"]: 1},
    }
    first = await api_client.post(
        "/api/v1/integrations/cafe-collection/redemptions/xp",
        json=redemption_payload,
        headers=headers,
    )
    retried = await api_client.post(
        "/api/v1/integrations/cafe-collection/redemptions/xp",
        json=redemption_payload,
        headers=headers,
    )
    after = await api_client.post(
        "/api/v1/integrations/cafe-collection/collection",
        json={"actor": _actor()},
        headers=headers,
    )

    assert before.status_code == 200
    assert before.json()["cosmetics"]
    assert before.json()["sets"]
    assert owned["exchangeable_count"] == 1
    assert favorite.json()["status"] == "updated"
    assert protection.json()["protected"] is True
    assert first.status_code == 200
    assert first.json()["status"] == "redeemed"
    assert retried.json() == first.json()
    after_card = next(
        card for card in after.json()["cards"] if card["key"] == owned["key"]
    )
    assert after_card["count"] == 1
    assert after.json()["favorite_reward_key"] == owned["key"]
    redemption = (
        await db_session.execute(
            select(CafeGachaRedemption).where(
                CafeGachaRedemption.event_id == "cafe-bot:redemption:8001"
            )
        )
    ).scalar_one()
    assert redemption.ledger_message_id is None


async def test_cafe_api_admin_parity_for_analytics_and_access_roles(
    api_client: AsyncClient,
) -> None:
    headers = {"Authorization": "Bearer cafe-secret"}
    denied = await api_client.post(
        "/api/v1/integrations/cafe-collection/analytics",
        json={"actor": _actor()},
        headers=headers,
    )
    added = await api_client.post(
        "/api/v1/integrations/cafe-collection/access-roles/add",
        json={"actor": _actor(can_manage_guild=True), "role_id": "9001"},
        headers=headers,
    )
    listed = await api_client.post(
        "/api/v1/integrations/cafe-collection/access-roles",
        json={"actor": _actor(can_manage_guild=True)},
        headers=headers,
    )
    analytics = await api_client.post(
        "/api/v1/integrations/cafe-collection/analytics",
        json={"actor": _actor(can_manage_guild=True)},
        headers=headers,
    )
    removed = await api_client.post(
        "/api/v1/integrations/cafe-collection/access-roles/remove",
        json={"actor": _actor(can_manage_guild=True), "role_id": "9001"},
        headers=headers,
    )

    assert denied.status_code == 403
    assert added.json() == {"role_ids": ["9001"], "changed": True}
    assert listed.json() == {"role_ids": ["9001"], "changed": None}
    assert analytics.status_code == 200
    assert analytics.json()["total_draws"] == 0
    assert removed.json() == {"role_ids": [], "changed": True}
