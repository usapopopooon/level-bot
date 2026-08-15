from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftItemGachaSpend, MinecraftVoicePresence
from src.features.color_role_shop.service import wallet_for_user
from src.features.minecraft_item_gacha.service import (
    ITEM_GACHA_COST_XP,
    ITEM_GACHA_DAILY_LIMIT,
    ITEM_GACHA_PREMIUM_COST_XP,
    SpendRequestResult,
    cancel_spend,
    complete_spend,
    request_spend,
)

NOW = datetime(2026, 8, 15, tzinfo=UTC)
DRAW_DAY = date(2026, 8, 15)
REQUEST_ID = "00000000-0000-4000-8000-000000000201"


async def _add_presence(
    session: AsyncSession,
    *,
    observed_at: datetime = NOW,
    account_id: str = "mc-bot:7",
) -> None:
    session.add(
        MinecraftVoicePresence(
            guild_id="1001",
            user_id="3001",
            minecraft_account_id=account_id,
            last_seen_at=observed_at,
            bonus_cursor_at=observed_at,
        )
    )
    await session.commit()


async def _request(
    session: AsyncSession,
    *,
    request_id: str = REQUEST_ID,
    total_xp: int = 100,
    expected_cost_xp: int = ITEM_GACHA_COST_XP,
) -> SpendRequestResult:
    return await request_spend(
        session,
        guild_id="1001",
        user_id="3001",
        request_id=request_id,
        minecraft_account_id="mc-bot:7",
        draw_day=DRAW_DAY,
        expected_cost_xp=expected_cost_xp,
        total_xp=total_xp,
        now=NOW,
    )


async def test_item_gacha_requires_current_price_online_account_and_balance(
    db_session: AsyncSession,
) -> None:
    stale_price = await _request(db_session, expected_cost_xp=99)
    assert stale_price.status == "unavailable"

    await _add_presence(db_session, observed_at=NOW - timedelta(minutes=2))
    offline = await _request(db_session)
    assert offline.status == "offline"

    presence = (await db_session.execute(select(MinecraftVoicePresence))).scalar_one()
    presence.last_seen_at = NOW
    await db_session.commit()
    insufficient = await _request(db_session, total_xp=99)
    assert insufficient.status == "insufficient_xp"
    premium_insufficient = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000205",
        total_xp=999,
        expected_cost_xp=ITEM_GACHA_PREMIUM_COST_XP,
    )
    assert premium_insufficient.status == "insufficient_xp"
    assert premium_insufficient.cost_xp == 1_000
    assert "1 XP不足" in premium_insufficient.message

    rows = (await db_session.execute(select(MinecraftItemGachaSpend))).scalars().all()
    assert rows == []


async def test_item_gacha_reservation_is_idempotent_and_limited_to_three_per_day(
    db_session: AsyncSession,
) -> None:
    await _add_presence(db_session)

    first = await _request(db_session, total_xp=5_000)
    duplicate = await _request(db_session, total_xp=5_000)
    premium = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000202",
        total_xp=5_000,
        expected_cost_xp=ITEM_GACHA_PREMIUM_COST_XP,
    )
    third = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000203",
        total_xp=5_000,
    )
    fourth = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000204",
        total_xp=5_000,
    )

    assert first.status == "reserved"
    assert first.wallet_before.available_xp == 5_000
    assert first.wallet_after.available_xp == 4_900
    assert duplicate.status == "reserved"
    assert duplicate.wallet_before.available_xp == 5_000
    assert duplicate.wallet_after.available_xp == 4_900
    assert premium.status == "reserved"
    assert premium.wallet_after.available_xp == 3_900
    assert third.status == "reserved"
    assert third.wallet_after.available_xp == 3_800
    assert fourth.status == "unavailable"
    assert str(ITEM_GACHA_DAILY_LIMIT) in fourth.message
    rows = (await db_session.execute(select(MinecraftItemGachaSpend))).scalars().all()
    assert len(rows) == 3
    assert [row.cost_xp for row in rows] == [100, 1_000, 100]
    assert all(row.status == "pending" for row in rows)


async def test_cancel_releases_xp_and_same_draw_can_be_reserved_again(
    db_session: AsyncSession,
) -> None:
    await _add_presence(db_session)
    assert (await _request(db_session)).status == "reserved"
    reserved = await wallet_for_user(
        db_session, guild_id="1001", user_id="3001", total_xp=100
    )
    assert reserved.available_xp == 0

    assert await cancel_spend(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id=REQUEST_ID,
    )
    released = await wallet_for_user(
        db_session, guild_id="1001", user_id="3001", total_xp=100
    )
    assert released.available_xp == 100

    retried = await _request(db_session)
    assert retried.status == "reserved"
    assert retried.wallet_after.available_xp == 0


async def test_complete_keeps_charge_and_cannot_be_cancelled(
    db_session: AsyncSession,
) -> None:
    await _add_presence(db_session)
    assert (await _request(db_session, total_xp=200)).status == "reserved"

    assert await complete_spend(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id=REQUEST_ID,
    )
    assert await complete_spend(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id=REQUEST_ID,
    )
    assert not await cancel_spend(
        db_session,
        guild_id="1001",
        user_id="3001",
        request_id=REQUEST_ID,
    )
    duplicate = await _request(db_session, total_xp=200)
    assert duplicate.status == "completed"
    assert duplicate.wallet_after.available_xp == 100
