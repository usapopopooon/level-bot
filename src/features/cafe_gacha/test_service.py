import secrets
from collections.abc import Mapping
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    CafeGachaDraw,
    CafeGachaMedalRedemption,
    CafeGachaRedemption,
    CafeGachaUserState,
    DailyStat,
)
from src.features.cafe_gacha.catalog import (
    CARDS,
    ENDGAME_PITY_MIN_COLLECTED,
    TOTAL_WEIGHT,
)
from src.features.cafe_gacha.ports import CafeGachaDependencies
from src.features.cafe_gacha.service import (
    TOKYO,
    active_cosmetic,
    cafe_medal_balance,
    draw_availability,
    draw_card,
    draw_cards,
    favorite_card,
    get_guild_config,
    guild_analytics,
    list_collection,
    redeem_cards,
    redeem_cards_for_medals,
    save_guild_config,
    set_card_protection,
    set_favorite_card,
    unlock_or_equip_cosmetic,
)
from src.features.color_role_shop.service import wallet_for_user
from src.features.leveling.service import (
    get_level_leaderboard,
    get_user_lifetime_levels,
)

GUILD_ID = "1001"
USER_ID = "2001"


class _ExternalConsumption:
    def __init__(self, counts: Mapping[str, int]) -> None:
        self.counts = counts

    async def consumed_card_counts(
        self,
        _session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
    ) -> Mapping[str, int]:
        assert (guild_id, user_id) == (GUILD_ID, USER_ID)
        return self.counts


class _LeaderboardAudience:
    async def blocked_user_ids(
        self,
        _session: AsyncSession,
        *,
        guild_id: str,
    ) -> set[str]:
        assert guild_id == GUILD_ID
        return set()


class _PublicGuildAccess:
    async def is_public_guild(
        self,
        _session: AsyncSession,
        *,
        guild_id: str,
    ) -> bool:
        return guild_id == GUILD_ID


class _UserPresentation:
    async def avatar_urls(
        self,
        _session: AsyncSession,
        *,
        user_ids: tuple[str, ...],
    ) -> dict[str, str | None]:
        return dict.fromkeys(user_ids)


def _dependencies(external_counts: Mapping[str, int]) -> CafeGachaDependencies:
    return CafeGachaDependencies(
        external_consumption=_ExternalConsumption(external_counts),
        leaderboard_audience=_LeaderboardAudience(),
        public_guild_access=_PublicGuildAccess(),
        user_presentation=_UserPresentation(),
    )


async def test_guild_analytics_uses_jst_boundaries_and_separates_new_draws(
    db_session: AsyncSession,
) -> None:
    moments = (
        ("today", "2001", datetime(2026, 8, 17, 0, tzinfo=UTC), False, "R", 20, 60),
        ("week", "2002", datetime(2026, 8, 11, 0, tzinfo=UTC), True, "C", 20, 25),
        ("old", "2001", datetime(2026, 8, 9, 0, tzinfo=UTC), True, "C", 20, 25),
    )
    for index, (event, user, created_at, duplicate, rarity, cost, reward) in enumerate(
        moments
    ):
        db_session.add(
            CafeGachaDraw(
                event_id=f"analytics-{event}",
                batch_id=f"analytics-{event}",
                batch_position=1,
                guild_id=GUILD_ID,
                user_id=user,
                display_name="客",
                draw_type="paid",
                cost_xp=cost,
                reward_xp=reward,
                reward_key=CARDS[index].key,
                reward_name=CARDS[index].name,
                reward_description=CARDS[index].description,
                rarity=rarity,
                image_filename=CARDS[index].image_filename,
                exchange_xp=reward,
                was_duplicate=duplicate,
                owned_count=2 if duplicate else 1,
                collected_count=index + 1,
                created_at=created_at,
            )
        )
    db_session.add(
        CafeGachaRedemption(
            event_id="analytics-redemption",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            reward_xp=25,
            created_at=datetime(2026, 8, 16, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    result = await guild_analytics(
        db_session,
        guild_id=GUILD_ID,
        now=datetime(2026, 8, 17, 3, tzinfo=UTC),
    )

    assert (result.draws_today, result.active_today) == (1, 1)
    assert (result.draws_7d, result.active_7d) == (2, 2)
    assert (result.total_draws, result.total_users) == (3, 2)
    assert (result.new_7d, result.duplicate_7d) == (1, 1)
    assert dict(result.rarity_7d) == {"C": 1, "R": 1}
    assert (result.spent_xp_7d, result.draw_reward_xp_7d) == (40, 85)
    assert result.redemption_xp_7d == 25


async def test_guild_config_keeps_counter_and_ledger_ids_distinct(
    db_session: AsyncSession,
) -> None:
    await save_guild_config(
        db_session,
        guild_id=GUILD_ID,
        counter_channel_id="3001",
        ledger_channel_id="3002",
        panel_message_id="4001",
        leaderboard_panel_message_id="4002",
    )

    config = await get_guild_config(db_session, GUILD_ID)
    assert config is not None
    assert config.counter_channel_id == "3001"
    assert config.ledger_channel_id == "3002"
    assert config.panel_message_id == "4001"
    assert config.leaderboard_panel_message_id == "4002"


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
    assert free.draw.reward_xp == 25
    assert free.wallet_after.total_xp == 125

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
    assert paid.draw.reward_xp == 25
    assert paid.wallet_after.available_xp == 105
    assert wallet.spent_xp == 20
    assert wallet.available_xp == 80


async def test_collection_uses_injected_external_consumption_port(
    db_session: AsyncSession,
) -> None:
    dependencies = _dependencies({})
    first = await draw_card(
        db_session,
        event_id="port-first",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=True,
        today=date(2026, 8, 9),
        random_value=0,
        dependencies=dependencies,
    )
    second = await draw_card(
        db_session,
        event_id="port-second",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=True,
        today=date(2026, 8, 9),
        random_value=0,
        dependencies=dependencies,
    )
    assert first.draw is not None and second.draw is not None

    dependencies = _dependencies({first.draw.reward_key: 1})
    collection = await list_collection(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        dependencies=dependencies,
    )
    selected = next(
        item for item in collection if item.card.key == first.draw.reward_key
    )

    assert selected.lifetime_count == 2
    assert selected.count == 1
    assert selected.redeemable_count == 0


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


async def test_confirmed_cost_change_never_charges_without_reconfirmation(
    db_session: AsyncSession,
) -> None:
    free = await draw_card(
        db_session,
        event_id="cost-race-free",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=0,
    )
    changed = await draw_card(
        db_session,
        event_id="cost-race-confirmed",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=True,
        expected_cost_xp=0,
        today=date(2026, 8, 9),
        random_value=0,
    )
    availability = await draw_availability(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        earned_xp=100,
        now=datetime(2026, 8, 8, 15, 0, tzinfo=UTC),
    )
    reconfirmed = await draw_card(
        db_session,
        event_id="cost-race-confirmed",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        allow_paid=True,
        expected_cost_xp=20,
        today=date(2026, 8, 9),
        random_value=0,
    )

    assert free.status == "drawn"
    assert changed.status == "confirmation_required"
    assert changed.draw is None
    assert availability.hourly_remaining == 9
    assert availability.wallet.spent_xp == 0
    assert reconfirmed.status == "drawn"
    assert reconfirmed.draw is not None
    assert reconfirmed.draw.cost_xp == 20


async def test_unowned_bonus_is_applied_to_persisted_collection(
    db_session: AsyncSession,
) -> None:
    first = await draw_card(
        db_session,
        event_id="bonus-first",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=1_000,
    )
    second = await draw_card(
        db_session,
        event_id="bonus-second",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 10),
        random_value=1_000,
    )

    assert first.draw is not None and first.draw.reward_key == "spent-tea"
    assert second.draw is not None and second.draw.reward_key == "cold-black-tea"
    assert second.draw.collected_count == 2


async def test_hourly_draw_limit_resets_at_the_next_clock_hour(
    db_session: AsyncSession,
) -> None:
    first_hour = datetime(2026, 8, 9, 1, 15, tzinfo=UTC)
    results = []
    for index in range(10):
        results.append(
            await draw_card(
                db_session,
                event_id=f"hourly-draw-{index}",
                guild_id=GUILD_ID,
                user_id=USER_ID,
                display_name="客",
                earned_xp=1000,
                allow_paid=index > 0,
                now=first_hour,
                random_value=0,
            )
        )

    blocked = await draw_card(
        db_session,
        event_id="hourly-draw-blocked",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=1000,
        allow_paid=False,
        now=first_hour,
        random_value=0,
    )
    retried = await draw_card(
        db_session,
        event_id="hourly-draw-9",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=1000,
        allow_paid=True,
        now=first_hour,
        random_value=0,
    )
    next_hour = await draw_card(
        db_session,
        event_id="hourly-draw-next-hour",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=1000,
        allow_paid=True,
        now=datetime(2026, 8, 9, 2, 0, tzinfo=UTC),
        random_value=0,
    )

    assert all(result.status == "drawn" for result in results)
    assert blocked.status == "hourly_limit"
    assert retried.status == "drawn"
    assert next_hour.status == "drawn"


async def test_hourly_limit_can_repeat_in_every_hour_without_daily_limit(
    db_session: AsyncSession,
) -> None:
    for hour in range(24):
        result = await draw_cards(
            db_session,
            event_id=f"all-day-hour-{hour}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=100_000,
            count=10,
            allow_paid=True,
            now=datetime(2026, 8, 9, hour, 0, tzinfo=TOKYO),
            random_values=(0,) * 10,
        )
        assert result.status == "drawn"
        assert len(result.draws) == 10

    availability = await draw_availability(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        earned_xp=100_000,
        now=datetime(2026, 8, 10, 0, 0, tzinfo=TOKYO),
    )
    assert availability.hourly_remaining == 10
    assert availability.available_count == 10


async def test_endgame_pity_guarantees_an_unowned_card_after_100_duplicates(
    db_session: AsyncSession,
) -> None:
    for index, card in enumerate(CARDS[:ENDGAME_PITY_MIN_COLLECTED]):
        db_session.add(
            CafeGachaDraw(
                event_id=f"pity-owned-{index}",
                batch_id=f"pity-owned-{index}",
                batch_position=1,
                guild_id=GUILD_ID,
                user_id=USER_ID,
                display_name="客",
                draw_type="free",
                cost_xp=0,
                reward_xp=card.draw_reward_xp,
                reward_key=card.key,
                reward_name=card.name,
                reward_description=card.description,
                rarity=card.rarity,
                image_filename=card.image_filename,
                exchange_xp=card.exchange_xp,
                was_duplicate=False,
                owned_count=1,
                collected_count=index + 1,
            )
        )
    duplicate = CARDS[0]
    for index in range(100):
        db_session.add(
            CafeGachaDraw(
                event_id=f"pity-duplicate-{index}",
                batch_id=f"pity-duplicate-{index}",
                batch_position=1,
                guild_id=GUILD_ID,
                user_id=USER_ID,
                display_name="客",
                draw_type="paid",
                cost_xp=20,
                reward_xp=duplicate.draw_reward_xp,
                reward_key=duplicate.key,
                reward_name=duplicate.name,
                reward_description=duplicate.description,
                rarity=duplicate.rarity,
                image_filename=duplicate.image_filename,
                exchange_xp=duplicate.exchange_xp,
                was_duplicate=True,
                owned_count=index + 2,
                collected_count=ENDGAME_PITY_MIN_COLLECTED,
            )
        )
    await db_session.commit()

    result = await draw_card(
        db_session,
        event_id="pity-guaranteed-new",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=10_000,
        allow_paid=True,
        now=datetime(2026, 8, 9, 0, 0, tzinfo=UTC),
        random_value=0,
    )

    assert result.status == "drawn"
    assert result.draw is not None
    assert result.draw.was_duplicate is False
    assert result.draw.reward_key == CARDS[ENDGAME_PITY_MIN_COLLECTED].key
    assert result.draw.collected_count == ENDGAME_PITY_MIN_COLLECTED + 1


async def test_ten_draws_commit_atomically_with_one_free_draw(
    db_session: AsyncSession,
) -> None:
    result = await draw_cards(
        db_session,
        event_id="ten-draw",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        count=10,
        today=date(2026, 8, 9),
        random_values=(0,) * 10,
    )

    assert result.status == "drawn"
    assert len(result.draws) == 10
    assert [draw.draw_type for draw in result.draws] == ["free"] + ["paid"] * 9
    assert [draw.batch_position for draw in result.draws] == list(range(1, 11))
    assert all(draw.batch_id == "ten-draw" for draw in result.draws)
    assert [draw.owned_count for draw in result.draws] == list(range(1, 11))
    assert result.draws[0].was_duplicate is False
    assert all(draw.was_duplicate for draw in result.draws[1:])
    assert result.wallet_after.total_xp == 250
    assert result.wallet_after.spent_xp == 180
    assert result.wallet_after.available_xp == 70


async def test_ten_paid_draws_can_reinvest_each_guaranteed_reward(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        CafeGachaUserState(
            guild_id=GUILD_ID,
            user_id=USER_ID,
            last_free_draw_on=date(2026, 8, 9),
            hourly_draw_count=0,
        )
    )
    await db_session.commit()

    result = await draw_cards(
        db_session,
        event_id="ten-paid-reinvested",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=20,
        count=10,
        expected_cost_xp=200,
        today=date(2026, 8, 9),
        random_values=(0,) * 10,
    )

    assert result.status == "drawn"
    assert len(result.draws) == 10
    assert all(draw.draw_type == "paid" for draw in result.draws)
    assert result.wallet_after.total_xp == 270
    assert result.wallet_after.spent_xp == 200
    assert result.wallet_after.available_xp == 70


async def test_ten_draws_are_idempotent_and_respect_remaining_hourly_capacity(
    db_session: AsyncSession,
) -> None:
    first = await draw_cards(
        db_session,
        event_id="ten-idempotent",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        count=10,
        today=date(2026, 8, 9),
        random_values=(0,) * 10,
    )
    retry = await draw_cards(
        db_session,
        event_id="ten-idempotent",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        count=10,
        today=date(2026, 8, 9),
        random_values=(9999,) * 10,
    )
    first_draw_ids = [draw.id for draw in first.draws]
    retry_draw_ids = [draw.id for draw in retry.draws]
    blocked = await draw_cards(
        db_session,
        event_id="ten-blocked",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=100,
        count=10,
        today=date(2026, 8, 9),
        random_values=(9999,) * 10,
    )

    assert first.status == "drawn"
    assert retry.status == "drawn"
    assert retry_draw_ids == first_draw_ids
    assert blocked.status == "hourly_limit"
    assert blocked.draws == ()


async def test_ten_draws_do_not_partially_commit_when_xp_is_insufficient(
    db_session: AsyncSession,
) -> None:
    state = CafeGachaUserState(
        guild_id=GUILD_ID,
        user_id=USER_ID,
        last_free_draw_on=date(2026, 8, 9),
        hourly_draw_count=0,
    )
    db_session.add(state)
    await db_session.commit()

    result = await draw_cards(
        db_session,
        event_id="ten-insufficient",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        count=10,
        today=date(2026, 8, 9),
        random_values=(0,) * 10,
    )
    collection = await list_collection(db_session, guild_id=GUILD_ID, user_id=USER_ID)
    await db_session.refresh(state)

    assert result.status == "insufficient_xp"
    assert result.draws == ()
    assert all(item.count == 0 for item in collection)
    assert state.hourly_draw_count == 0


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
        random_value=TOTAL_WEIGHT - 1,
    )

    levels = await get_user_lifetime_levels(
        db_session, GUILD_ID, USER_ID, include_live_voice=False
    )
    leaderboard = await get_level_leaderboard(
        db_session, GUILD_ID, axis="total", limit=10
    )

    assert result.draw is not None and result.draw.reward_xp == 5_000
    assert result.draw.rarity == "MYTHIC"
    assert result.wallet_after.available_xp == 5_000
    assert levels is not None
    assert levels.bonus_total_xp == 5_000
    assert levels.total.xp == 5_000
    assert leaderboard[0].user_id == USER_ID
    assert leaderboard[0].xp == 5_000


async def test_runtime_random_draw_uses_the_full_catalog_weight_range(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upper_bounds: list[int] = []

    def _last_value(upper_bound: int) -> int:
        upper_bounds.append(upper_bound)
        return upper_bound - 1

    monkeypatch.setattr(secrets, "randbelow", _last_value)

    result = await draw_card(
        db_session,
        event_id="runtime-weight-range",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 9),
    )

    assert upper_bounds == [TOTAL_WEIGHT]
    assert result.draw is not None
    assert result.draw.rarity == "MYTHIC"


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
    assert before.lifetime_count == 3
    assert redeemed.status == "redeemed"
    assert redeemed.redemption is not None
    assert redeemed.redemption.reward_xp == 5
    assert redeemed.items[0].xp_per_card == 5
    assert after.count == 2
    assert after.redeemable_count == 1
    assert after.lifetime_count == 3


async def test_medal_redemption_consumes_only_duplicates_and_preserves_mastery(
    db_session: AsyncSession,
) -> None:
    for index, day in enumerate((9, 10, 11)):
        await draw_card(
            db_session,
            event_id=f"medal-draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=0,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=0,
        )
    result = await redeem_cards_for_medals(
        db_session,
        event_id="medal-redeem",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantities={"spent-tea": 2},
    )
    collection = await list_collection(db_session, guild_id=GUILD_ID, user_id=USER_ID)

    assert result.status == "redeemed"
    assert result.redemption is not None and result.redemption.reward_medals == 2
    assert collection[0].count == 1
    assert collection[0].lifetime_count == 3
    assert await cafe_medal_balance(db_session, guild_id=GUILD_ID, user_id=USER_ID) == 2


async def test_card_protection_excludes_all_duplicates_from_both_exchanges(
    db_session: AsyncSession,
) -> None:
    await draw_card(
        db_session,
        event_id="protected-draw-0",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        earned_xp=0,
        allow_paid=False,
        today=date(2026, 8, 9),
        random_value=0,
    )

    protected = await set_card_protection(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        reward_key="spent-tea",
        protected=True,
    )
    for index, day in enumerate((10, 11), start=1):
        await draw_card(
            db_session,
            event_id=f"protected-draw-{index}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            display_name="客",
            earned_xp=0,
            allow_paid=False,
            today=date(2026, 8, day),
            random_value=0,
        )
    collection = await list_collection(db_session, guild_id=GUILD_ID, user_id=USER_ID)
    card = collection[0]
    xp_result = await redeem_cards(
        db_session,
        event_id="protected-xp-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="客",
        quantities={"spent-tea": 1},
    )
    medal_result = await redeem_cards_for_medals(
        db_session,
        event_id="protected-medal-redemption",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantities={"spent-tea": 1},
    )

    assert protected is not None and protected.key == "spent-tea"
    assert card.is_protected is True
    assert (card.count, card.redeemable_count, card.exchangeable_count) == (3, 2, 0)
    assert xp_result.status == "unavailable"
    assert medal_result.status == "unavailable"

    await set_card_protection(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        reward_key="spent-tea",
        protected=False,
    )
    unprotected = (
        await list_collection(db_session, guild_id=GUILD_ID, user_id=USER_ID)
    )[0]
    assert unprotected.is_protected is False
    assert unprotected.exchangeable_count == 2


async def test_cosmetic_purchase_charges_once_then_re_equips_for_free(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        CafeGachaMedalRedemption(
            event_id="seed-medals",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            reward_medals=150,
        )
    )
    await db_session.commit()

    purchased = await unlock_or_equip_cosmetic(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        cosmetic_key="sunny-wood",
    )
    equipped_again = await unlock_or_equip_cosmetic(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        cosmetic_key="sunny-wood",
    )

    assert purchased.status == "equipped" and purchased.balance == 50
    assert equipped_again.status == "equipped" and equipped_again.balance == 50
    active = await active_cosmetic(db_session, guild_id=GUILD_ID, user_id=USER_ID)
    assert active is not None
    assert active.key == "sunny-wood"


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
    draws = ((9, 0), (10, 0), (11, 97_500), (12, 97_500))
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
    assert result.redemption.reward_xp == 15
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
        db_session, guild_id=GUILD_ID, user_id=USER_ID, total_xp=165
    )
    leaderboard = await get_level_leaderboard(
        db_session, GUILD_ID, axis="total", limit=10
    )

    assert levels is not None
    assert levels.text.xp == 60
    assert levels.bonus_total_xp == 105
    assert levels.total.xp == 145
    assert wallet.spent_xp == 20
    assert wallet.available_xp == 145
    assert leaderboard[0].user_id == USER_ID
    assert leaderboard[0].xp == 145
