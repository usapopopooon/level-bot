from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftVoicePresence
from src.features.color_role_shop.service import wallet_for_user
from src.features.minecraft_xp_shop.service import (
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


async def test_online_exchange_reserves_then_completes_ledger(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)

    result = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        cost_xp=10,
        total_xp=100,
        now=now,
    )

    assert result.status == "reserved"
    assert result.exchange_id is not None
    assert result.wallet_after.available_xp == 90
    pending = await list_pending_exchanges(db_session, guild_id="1001", limit=20)
    assert len(pending) == 1
    assert pending[0].event_id
    assert pending[0].minecraft_account_id == "mc-bot:7"
    assert pending[0].reward_xp == 50
    assert await claim_exchange(
        db_session,
        guild_id="1001",
        exchange_id=result.exchange_id,
        claim_token="worker-one",
    )
    assert await complete_exchange(
        db_session,
        guild_id="1001",
        exchange_id=result.exchange_id,
        claim_token="worker-one",
    )
    assert await list_pending_exchanges(db_session, guild_id="1001", limit=20) == ()
    wallet = await wallet_for_user(
        db_session, guild_id="1001", user_id="3001", total_xp=100
    )
    assert wallet.available_xp == 90


async def test_offline_exchange_does_not_reserve_xp(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now - timedelta(minutes=2))

    result = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        cost_xp=10,
        total_xp=100,
        now=now,
    )

    assert result.status == "offline"
    assert result.wallet_after.available_xp == 100
    assert await list_pending_exchanges(db_session, guild_id="1001", limit=20) == ()


async def test_cancelled_delivery_releases_reserved_xp(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)
    result = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        cost_xp=50,
        total_xp=100,
        now=now,
    )
    assert result.exchange_id is not None

    assert await cancel_exchange(
        db_session, guild_id="1001", exchange_id=result.exchange_id
    )
    wallet = await wallet_for_user(
        db_session, guild_id="1001", user_id="3001", total_xp=100
    )
    assert wallet.available_xp == 100


async def test_claim_and_complete_are_idempotent_for_the_same_owner(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    await _add_presence(db_session, observed_at=now)
    requested = await request_exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        cost_xp=10,
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
