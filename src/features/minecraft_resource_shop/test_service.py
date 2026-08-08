from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftVoicePresence
from src.features.color_role_shop.service import wallet_for_user
from src.features.minecraft_resource_shop.service import (
    cancel_exchange,
    claim_exchange,
    complete_exchange,
    list_pending_exchanges,
    request_exchange,
)


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
        expected_cost_xp=50,
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
        expected_cost_xp=50,
        total_xp=100,
        now=now,
    )
    assert requested.exchange_id is not None
    reserved_wallet = await wallet_for_user(
        db_session, guild_id="1001", user_id="3001", total_xp=100
    )
    assert reserved_wallet.available_xp == 50

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
        expected_cost_xp=50,
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
