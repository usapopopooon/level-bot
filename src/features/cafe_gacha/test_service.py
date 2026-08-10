from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat
from src.features.cafe_gacha.service import (
    draw_card,
    favorite_card,
    get_guild_config,
    list_collection,
    redeem_cards,
    save_guild_config,
    set_favorite_card,
)
from src.features.color_role_shop.service import wallet_for_user
from src.features.leveling.service import (
    get_level_leaderboard,
    get_user_lifetime_levels,
)

GUILD_ID = "1001"
USER_ID = "2001"


async def test_guild_config_keeps_counter_and_ledger_ids_distinct(
    db_session: AsyncSession,
) -> None:
    await save_guild_config(
        db_session,
        guild_id=GUILD_ID,
        counter_channel_id="3001",
        ledger_channel_id="3002",
        panel_message_id="4001",
    )

    config = await get_guild_config(db_session, GUILD_ID)
    assert config is not None
    assert config.counter_channel_id == "3001"
    assert config.ledger_channel_id == "3002"
    assert config.panel_message_id == "4001"


async def test_daily_free_draw_then_paid_draw_requires_confirmation(
    db_session: AsyncSession,
) -> None:
    free = await draw_card(
        db_session,
        event_id="free-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=0,
    )
    assert free.status == "drawn"
    assert free.draw is not None and free.draw.draw_type == "free"
    assert free.draw.reward_xp == 3
    assert free.wallet_after.total_xp == 103

    confirmation = await draw_card(
        db_session,
        event_id="paid-unconfirmed",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=0,
    )
    paid = await draw_card(
        db_session,
        event_id="paid-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=True,
        today=date(2026, 8, 9),
        random_value=0,
    )
    wallet = await wallet_for_user(
        db_session, guild_id=GUILD_ID, user_id=USER_ID, total_xp=100
    )

    assert confirmation.status == "confirmation_required"
    assert paid.status == "drawn"
    assert paid.draw is not None and paid.draw.cost_xp == 20
    assert paid.draw.reward_xp == 3
    assert paid.wallet_after.available_xp == 83
    assert wallet.spent_xp == 20
    assert wallet.available_xp == 80


async def test_next_day_is_free_again(db_session: AsyncSession) -> None:
    first = await draw_card(
        db_session,
        event_id="day-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=0,
    )
    second = await draw_card(
        db_session,
        event_id="day-2",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 10),
        random_value=0,
    )

    assert first.draw is not None and first.draw.draw_type == "free"
    assert second.draw is not None and second.draw.draw_type == "free"
    assert first.draw.owned_count == 1
    assert first.draw.collected_count == 1
    assert second.draw.owned_count == 2
    assert second.draw.collected_count == 1


async def test_draw_reward_immediately_increases_total_xp_and_leaderboard(
    db_session: AsyncSession,
) -> None:
    result = await draw_card(
        db_session,
        event_id="reward-only-draw",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=9999,
    )

    levels = await get_user_lifetime_levels(
        db_session, GUILD_ID, USER_ID, include_live_voice=False
    )
    leaderboard = await get_level_leaderboard(
        db_session, GUILD_ID, axis="total", limit=10
    )

    assert result.draw is not None and result.draw.reward_xp == 100
    assert result.wallet_after.available_xp == 100
    assert levels is not None
    assert levels.bonus_total_xp == 100
    assert levels.total.xp == 100
    assert leaderboard[0].user_id == USER_ID
    assert leaderboard[0].xp == 100


async def test_same_draw_event_is_idempotent_and_cannot_cross_users(
    db_session: AsyncSession,
) -> None:
    first = await draw_card(
        db_session,
        event_id="same-event",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=0,
    )
    retry = await draw_card(
        db_session,
        event_id="same-event",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=True,
        today=date(2026, 8, 9),
        random_value=9999,
    )
    assert first.draw is not None
    assert retry.draw is not None
    first_draw_id = first.draw.id
    retry_draw_id = retry.draw.id
    conflict = await draw_card(
        db_session,
        event_id="same-event",
        guild_id=GUILD_ID,
        user_id="2002",
        display_name="別の客",
        earned_xp=100,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=9999,
    )

    assert retry_draw_id == first_draw_id
    assert conflict.status == "conflict"


async def test_redemption_keeps_first_copy_and_uses_requested_quantity(
    db_session: AsyncSession,
) -> None:
    for index, day in enumerate((9, 10, 11)):
        result = await draw_card(
            db_session,
            event_id=f"draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=0,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=0,
        )
        assert result.status == "drawn"

    before = (await list_collection(db_session, guild_id=GUILD_ID, user_id=USER_ID))[0]
    redeemed = await redeem_cards(
        db_session,
        event_id="redeem-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1},
    )
    after = (await list_collection(db_session, guild_id=GUILD_ID, user_id=USER_ID))[0]

    assert before.count == 3
    assert before.redeemable_count == 2
    assert redeemed.status == "redeemed"
    assert redeemed.redemption is not None
    assert redeemed.redemption.reward_xp == 2
    assert after.count == 2
    assert after.redeemable_count == 1


async def test_draw_after_redemption_snapshots_current_owned_count(
    db_session: AsyncSession,
) -> None:
    for index, day in enumerate((9, 10, 11)):
        await draw_card(
            db_session,
            event_id=f"snapshot-draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=0,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=0,
        )
    redeemed = await redeem_cards(
        db_session,
        event_id="snapshot-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 2},
    )
    latest = await draw_card(
        db_session,
        event_id="snapshot-after-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 12),
        random_value=0,
    )

    assert redeemed.status == "redeemed"
    assert latest.draw is not None
    assert latest.draw.was_duplicate is True
    assert latest.draw.owned_count == 2
    assert latest.draw.collected_count == 1


async def test_redemption_rejects_protected_first_copy(
    db_session: AsyncSession,
) -> None:
    await draw_card(
        db_session,
        event_id="only-copy",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=0,
    )
    result = await redeem_cards(
        db_session,
        event_id="invalid-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1},
    )

    assert result.status == "unavailable"


async def test_favorite_must_be_owned_and_survives_duplicate_exchange(
    db_session: AsyncSession,
) -> None:
    assert (
        await set_favorite_card(
            db_session,
            guild_id=GUILD_ID,
            user_id=USER_ID,
            reward_key="spent-tea",
        )
        is None
    )
    for index, day in enumerate((9, 10)):
        await draw_card(
            db_session,
            event_id=f"favorite-draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=0,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=0,
        )
    selected = await set_favorite_card(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        reward_key="spent-tea",
    )
    await redeem_cards(
        db_session,
        event_id="favorite-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1},
    )

    favorite = await favorite_card(db_session, guild_id=GUILD_ID, user_id=USER_ID)
    assert selected is not None and selected.name == "出がらし"
    assert favorite is not None and favorite.key == "spent-tea"


async def test_bulk_redemption_uses_only_explicit_cards_and_sums_rates(
    db_session: AsyncSession,
) -> None:
    draws = ((9, 0), (10, 0), (11, 5000), (12, 5000))
    for index, (day, random_value) in enumerate(draws):
        await draw_card(
            db_session,
            event_id=f"bulk-draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=0,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=random_value,
        )
    result = await redeem_cards(
        db_session,
        event_id="bulk-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1, "barley-chicory-coffee": 1},
    )

    assert result.redemption is not None
    assert result.redemption.reward_xp == 6
    assert {item.reward_key for item in result.items} == {
        "spent-tea",
        "barley-chicory-coffee",
    }


async def test_redemption_is_idempotent_but_rejects_changed_quantities(
    db_session: AsyncSession,
) -> None:
    for index, day in enumerate((9, 10, 11)):
        await draw_card(
            db_session,
            event_id=f"idempotent-draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=0,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=0,
        )
    first = await redeem_cards(
        db_session,
        event_id="same-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1},
    )
    retry = await redeem_cards(
        db_session,
        event_id="same-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1},
    )
    assert first.redemption is not None
    assert retry.redemption is not None
    first_redemption_id = first.redemption.id
    retry_redemption_id = retry.redemption.id
    conflict = await redeem_cards(
        db_session,
        event_id="same-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 2},
    )

    assert retry_redemption_id == first_redemption_id
    assert conflict.status == "unavailable"


async def test_paid_cost_and_redemption_bonus_match_wallet_levels_and_leaderboard(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        DailyStat(
            guild_id=GUILD_ID,
            user_id=USER_ID,
            channel_id="3001",
            stat_date=date(2026, 8, 9),
            message_count=20,
        )
    )
    await db_session.commit()
    for index, day in enumerate((9, 10, 11)):
        await draw_card(
            db_session,
            event_id=f"xp-draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=60,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=0,
        )
    await draw_card(
        db_session,
        event_id="xp-paid-draw",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=60,
        allow_paid=True,
        today=date(2026, 8, 11),
        random_value=0,
    )
    await redeem_cards(
        db_session,
        event_id="xp-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1},
    )

    levels = await get_user_lifetime_levels(
        db_session, GUILD_ID, USER_ID, include_live_voice=False
    )
    wallet = await wallet_for_user(
        db_session, guild_id=GUILD_ID, user_id=USER_ID, total_xp=74
    )
    leaderboard = await get_level_leaderboard(
        db_session, GUILD_ID, axis="total", limit=10
    )

    assert levels is not None
    assert levels.text.xp == 60
    assert levels.bonus_total_xp == 14
    assert levels.total.xp == 54
    assert wallet.spent_xp == 20
    assert wallet.available_xp == 54
    assert leaderboard[0].user_id == USER_ID
    assert leaderboard[0].xp == 54
