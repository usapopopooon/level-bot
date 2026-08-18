from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, MinecraftMarketPurchase
from src.features.color_role_shop.service import wallet_for_user
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels
from src.features.minecraft_market.service import (
    PurchaseRequestResult,
    request_purchase,
    update_purchase,
)

GUILD_ID = "1001"
BUYER_ID = "2001"
SELLER_ID = "2002"
REQUEST_ID = "00000000-0000-4000-8000-000000000041"


def _buyer_activity() -> DailyStat:
    return DailyStat(
        guild_id=GUILD_ID,
        user_id=BUYER_ID,
        channel_id="3001",
        stat_date=date(2026, 8, 24),
        message_count=1_000,
    )


async def _request(
    db_session: AsyncSession, *, request_id: str = REQUEST_ID
) -> PurchaseRequestResult:
    return await request_purchase(
        db_session,
        event_id=request_id,
        guild_id=GUILD_ID,
        listing_id=17,
        buyer_user_id=BUYER_ID,
        seller_user_id=SELLER_ID,
        buyer_minecraft_account_id="mc-bot:1",
        seller_minecraft_account_id="mc-bot:2",
        cost_xp=1_200,
        buyer_total_xp=3_000,
    )


async def test_purchase_reserves_once_and_completed_sale_moves_xp(
    db_session: AsyncSession,
) -> None:
    db_session.add(_buyer_activity())
    await db_session.commit()

    first = await _request(db_session)
    retried = await _request(db_session)

    assert first.status == "reserved"
    assert first.wallet_before.available_xp == 3_000
    assert first.wallet_after.available_xp == 1_800
    assert retried.status == "reserved"
    assert retried.wallet_after.available_xp == 1_800
    assert (
        len((await db_session.execute(select(MinecraftMarketPurchase))).scalars().all())
        == 1
    )

    assert await update_purchase(
        db_session,
        event_id=REQUEST_ID,
        guild_id=GUILD_ID,
        action="complete",
    )
    assert await update_purchase(
        db_session,
        event_id=REQUEST_ID,
        guild_id=GUILD_ID,
        action="complete",
    )

    buyer_levels = await get_user_lifetime_levels(db_session, GUILD_ID, BUYER_ID)
    seller_levels = await get_user_lifetime_levels(db_session, GUILD_ID, SELLER_ID)
    assert buyer_levels is not None
    assert seller_levels is not None
    assert buyer_levels.total.xp == 1_800
    assert seller_levels.total.xp == 1_200
    seller_wallet = await wallet_for_user(
        db_session,
        guild_id=GUILD_ID,
        user_id=SELLER_ID,
        total_xp=earned_total_xp(seller_levels),
    )
    assert seller_wallet.available_xp == 1_200


async def test_cancel_releases_buyer_xp_and_does_not_credit_seller(
    db_session: AsyncSession,
) -> None:
    db_session.add(_buyer_activity())
    await db_session.commit()
    requested = await _request(db_session)
    assert requested.wallet_after.available_xp == 1_800

    assert await update_purchase(
        db_session,
        event_id=REQUEST_ID,
        guild_id=GUILD_ID,
        action="cancel",
    )
    buyer_levels = await get_user_lifetime_levels(db_session, GUILD_ID, BUYER_ID)
    seller_levels = await get_user_lifetime_levels(db_session, GUILD_ID, SELLER_ID)
    assert buyer_levels is not None
    assert buyer_levels.total.xp == 3_000
    assert seller_levels is None


async def test_listing_can_only_have_one_active_or_completed_purchase(
    db_session: AsyncSession,
) -> None:
    first = await _request(db_session)
    second = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000042",
    )

    assert first.status == "reserved"
    assert second.status == "unavailable"


async def test_cancelled_purchase_releases_listing_for_a_new_request(
    db_session: AsyncSession,
) -> None:
    first = await _request(db_session)
    assert first.status == "reserved"
    assert await update_purchase(
        db_session,
        event_id=REQUEST_ID,
        guild_id=GUILD_ID,
        action="cancel",
    )

    second = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000042",
    )

    assert second.status == "reserved"
