from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftVoicePresence
from src.features.color_role_shop.service import wallet_for_user
from src.features.minecraft_resource_shop.service import (
    MINECRAFT_RESOURCE_PACKS,
    MinecraftResourcePack,
    cancel_exchange,
    claim_exchange,
    complete_exchange,
    get_resource_catalog,
    list_pending_exchanges,
    remove_resource_pack,
    request_exchange,
    upsert_resource_pack,
)


def test_resource_packs_extend_existing_rates_to_one_stack() -> None:
    assert [
        (pack.item_id, pack.item_count, pack.cost_xp)
        for pack in MINECRAFT_RESOURCE_PACKS
    ] == [
        ("minecraft:emerald", 4, 75),
        ("minecraft:emerald", 16, 250),
        ("minecraft:emerald", 32, 500),
        ("minecraft:emerald", 64, 1_000),
        ("minecraft:gunpowder", 64, 150),
        ("minecraft:diamond", 1, 250),
        ("minecraft:diamond", 3, 750),
        ("minecraft:diamond", 8, 2_000),
        ("minecraft:diamond", 16, 4_000),
    ]


async def test_dynamic_catalog_adds_and_removes_pack_without_losing_pending_label(
    db_session: AsyncSession,
) -> None:
    catalog = await upsert_resource_pack(
        db_session,
        guild_id="1001",
        actor_user_id="9001",
        pack=MinecraftResourcePack("minecraft:copper_ingot", "銅インゴット", 16, 240),
    )
    assert catalog.revision == 1
    assert catalog.packs[-1] == MinecraftResourcePack(
        "minecraft:copper_ingot", "銅インゴット", 16, 240
    )

    now = datetime(2026, 8, 8, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)
    result = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id="00000000-0000-4000-8000-000000000105",
        item_id="minecraft:copper_ingot",
        item_count=16,
        expected_cost_xp=240,
        total_xp=240,
        now=now,
    )
    assert result.status == "reserved"

    removed = await remove_resource_pack(
        db_session,
        guild_id="1001",
        actor_user_id="9001",
        item_id="minecraft:copper_ingot",
        item_count=16,
    )
    assert removed is not None
    assert removed.revision == 2
    assert all(pack.item_id != "minecraft:copper_ingot" for pack in removed.packs)
    pending = await list_pending_exchanges(db_session, guild_id="1001", limit=20)
    assert pending[0].item_name == "銅インゴット"


async def test_dynamic_catalog_rate_change_rejects_stale_selection(
    db_session: AsyncSession,
) -> None:
    catalog = await upsert_resource_pack(
        db_session,
        guild_id="1001",
        actor_user_id="9001",
        pack=MinecraftResourcePack("minecraft:emerald", "エメラルド", 4, 120),
    )
    assert catalog.revision == 1
    current = await get_resource_catalog(db_session, guild_id="1001")
    assert current.packs[0].cost_xp == 120

    now = datetime(2026, 8, 8, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)
    result = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id="00000000-0000-4000-8000-000000000106",
        item_id="minecraft:emerald",
        item_count=4,
        expected_cost_xp=100,
        total_xp=120,
        now=now,
    )
    assert result.status == "unavailable"
    assert "レートが更新" in result.message


async def test_dynamic_catalog_keeps_one_display_name_for_every_pack_of_an_item(
    db_session: AsyncSession,
) -> None:
    catalog = await upsert_resource_pack(
        db_session,
        guild_id="1001",
        actor_user_id="9001",
        pack=MinecraftResourcePack("minecraft:emerald", "翠玉", 4, 100),
    )

    emeralds = [pack for pack in catalog.packs if pack.item_id == "minecraft:emerald"]
    assert len(emeralds) == 4
    assert {pack.item_name for pack in emeralds} == {"翠玉"}


async def test_resource_exchange_reserves_exact_gunpowder_pack(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)

    result = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id="00000000-0000-4000-8000-000000000104",
        item_id="minecraft:gunpowder",
        item_count=64,
        expected_cost_xp=150,
        total_xp=150,
        now=now,
    )

    assert result.status == "reserved"
    assert result.pack is not None
    assert (result.pack.item_name, result.pack.item_count, result.pack.cost_xp) == (
        "火薬",
        64,
        150,
    )
    assert result.wallet_after.available_xp == 0


async def _add_presence(
    session: AsyncSession, *, observed_at: datetime, user_id: str = "3001"
) -> None:
    session.add(
        MinecraftVoicePresence(
            guild_id="1001",
            user_id=user_id,
            minecraft_account_id="mc-bot:7",
            last_seen_at=observed_at,
            bonus_cursor_at=observed_at,
        )
    )
    await session.commit()


async def test_resource_exchange_offline_does_not_reserve_xp(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now - timedelta(minutes=2))

    result = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id="00000000-0000-4000-8000-000000000101",
        item_id="minecraft:emerald",
        item_count=4,
        expected_cost_xp=100,
        total_xp=100,
        now=now,
    )

    assert result.status == "offline"
    assert result.wallet_after.available_xp == 100
    assert await list_pending_exchanges(db_session, guild_id="1001", limit=20) == ()


async def test_resource_exchange_cancel_releases_reserved_xp(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)
    requested = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id="00000000-0000-4000-8000-000000000102",
        item_id="minecraft:emerald",
        item_count=4,
        expected_cost_xp=100,
        total_xp=100,
        now=now,
    )
    assert requested.exchange_id is not None
    reserved_wallet = await wallet_for_user(
        db_session, guild_id="1001", user_id="3001", total_xp=100
    )
    assert reserved_wallet.available_xp == 0

    assert await cancel_exchange(
        db_session,
        guild_id="1001",
        exchange_id=requested.exchange_id,
    )

    released_wallet = await wallet_for_user(
        db_session, guild_id="1001", user_id="3001", total_xp=100
    )
    assert released_wallet.available_xp == 100
    assert await list_pending_exchanges(db_session, guild_id="1001", limit=20) == ()


async def test_resource_exchange_claim_and_complete_are_owned_and_idempotent(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)
    requested = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id="00000000-0000-4000-8000-000000000103",
        item_id="minecraft:emerald",
        item_count=4,
        expected_cost_xp=100,
        total_xp=100,
        now=now,
    )
    assert requested.exchange_id is not None

    assert await claim_exchange(
        db_session,
        guild_id="1001",
        exchange_id=requested.exchange_id,
        claim_token="worker-one",
    )
    assert await claim_exchange(
        db_session,
        guild_id="1001",
        exchange_id=requested.exchange_id,
        claim_token="worker-one",
    )
    assert not await claim_exchange(
        db_session,
        guild_id="1001",
        exchange_id=requested.exchange_id,
        claim_token="worker-two",
    )
    assert not await complete_exchange(
        db_session,
        guild_id="1001",
        exchange_id=requested.exchange_id,
        claim_token="worker-two",
    )
    assert await complete_exchange(
        db_session,
        guild_id="1001",
        exchange_id=requested.exchange_id,
        claim_token="worker-one",
    )
    assert await complete_exchange(
        db_session,
        guild_id="1001",
        exchange_id=requested.exchange_id,
        claim_token="worker-one",
    )
    assert await list_pending_exchanges(db_session, guild_id="1001", limit=20) == ()
