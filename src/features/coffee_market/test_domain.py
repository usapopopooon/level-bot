from datetime import UTC, date, datetime, timedelta

import pytest

from src.features.coffee_market.domain import (
    MARKET_TIMEZONE,
    market_day_for,
    next_reset_at,
    quote_for,
)


def test_market_day_changes_at_five_in_japan() -> None:
    before = datetime(2026, 8, 25, 4, 59, tzinfo=MARKET_TIMEZONE)
    after = datetime(2026, 8, 25, 5, 0, tzinfo=MARKET_TIMEZONE)

    assert market_day_for(before) == date(2026, 8, 24)
    assert market_day_for(after) == date(2026, 8, 25)
    assert market_day_for(after.astimezone(UTC)) == date(2026, 8, 25)


def test_market_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        market_day_for(datetime(2026, 8, 25, 5, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        next_reset_at(datetime(2026, 8, 25, 5, 0))


def test_quote_is_deterministic_and_server_scoped() -> None:
    day = date(2026, 8, 25)

    first = quote_for("1001", day)
    replay = quote_for("1001", day)
    other_guild = quote_for("1002", day)

    assert first == replay
    assert first != other_guild
    assert 75 <= first.buy_price_xp <= 125
    assert 35 <= first.sell_price_xp <= 250
    assert 35 <= first.previous_sell_price_xp <= 250


def test_next_reset_is_always_the_following_five_oclock() -> None:
    before = datetime(2026, 8, 25, 4, 59, tzinfo=MARKET_TIMEZONE)
    after = datetime(2026, 8, 25, 5, 1, tzinfo=MARKET_TIMEZONE)

    assert next_reset_at(before) == datetime(2026, 8, 25, 5, 0, tzinfo=MARKET_TIMEZONE)
    assert next_reset_at(after) == datetime(2026, 8, 26, 5, 0, tzinfo=MARKET_TIMEZONE)


def test_daily_limit_and_price_curves_bound_optimal_xp_creation() -> None:
    best_ratios: list[float] = []
    profits_per_bag: list[int] = []
    start = date(2026, 1, 5)
    for guild_number in range(1000, 1100):
        guild_id = str(guild_number)
        for offset in range(28):
            buy_day = start + timedelta(days=offset)
            buy_price = quote_for(guild_id, buy_day).buy_price_xp
            best_sell = max(
                quote_for(guild_id, buy_day + timedelta(days=held_days)).sell_price_xp
                for held_days in range(1, 8)
            )
            best_ratios.append(best_sell / buy_price)
            profits_per_bag.append(best_sell - buy_price)

    mean_best_ratio = sum(best_ratios) / len(best_ratios)
    mean_profit_per_bag = sum(profits_per_bag) / len(profits_per_bag)
    assert 1.15 <= mean_best_ratio <= 1.35
    assert mean_profit_per_bag <= 30
