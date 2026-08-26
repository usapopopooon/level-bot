from datetime import UTC, date, datetime, timedelta

import pytest

from src.features.coffee_market.domain import (
    MARKET_TIMEZONE,
    MarketPeriod,
    market_day_for,
    market_period_for,
    next_market_period,
    next_reset_at,
    quote_for,
)


def test_market_period_changes_four_times_a_day_in_japan() -> None:
    midnight = datetime(2026, 8, 25, 0, 0, tzinfo=MARKET_TIMEZONE)
    six = datetime(2026, 8, 25, 6, 0, tzinfo=MARKET_TIMEZONE)
    noon = datetime(2026, 8, 25, 12, 0, tzinfo=MARKET_TIMEZONE)
    evening = datetime(2026, 8, 25, 18, 0, tzinfo=MARKET_TIMEZONE)

    assert market_period_for(midnight) == MarketPeriod(date(2026, 8, 25), 0)
    assert market_period_for(six) == MarketPeriod(date(2026, 8, 25), 1)
    assert market_period_for(noon) == MarketPeriod(date(2026, 8, 25), 2)
    assert market_period_for(evening) == MarketPeriod(date(2026, 8, 25), 3)
    assert market_period_for(evening.astimezone(UTC)) == MarketPeriod(
        date(2026, 8, 25), 3
    )
    assert market_day_for(evening) == date(2026, 8, 25)


def test_market_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        market_day_for(datetime(2026, 8, 25, 0, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        market_period_for(datetime(2026, 8, 25, 6, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        next_reset_at(datetime(2026, 8, 25, 0, 0))


def test_quote_is_deterministic_and_server_scoped() -> None:
    period = MarketPeriod(date(2026, 8, 25), 2)

    first = quote_for("1001", period)
    replay = quote_for("1001", period)
    other_guild = quote_for("1002", period)

    assert first == replay
    assert first != other_guild
    assert 75 <= first.buy_price_xp <= 125
    assert 35 <= first.sell_price_xp <= 250
    assert 35 <= first.previous_sell_price_xp <= 250


def test_next_reset_is_always_the_following_six_hour_boundary() -> None:
    before_six = datetime(2026, 8, 25, 5, 59, tzinfo=MARKET_TIMEZONE)
    after_six = datetime(2026, 8, 25, 6, 1, tzinfo=MARKET_TIMEZONE)
    after_eighteen = datetime(2026, 8, 25, 18, 1, tzinfo=MARKET_TIMEZONE)

    assert next_reset_at(before_six) == datetime(
        2026, 8, 25, 6, 0, tzinfo=MARKET_TIMEZONE
    )
    assert next_reset_at(after_six) == datetime(
        2026, 8, 25, 12, 0, tzinfo=MARKET_TIMEZONE
    )
    assert next_reset_at(after_eighteen) == datetime(
        2026, 8, 26, 0, 0, tzinfo=MARKET_TIMEZONE
    )


def test_market_period_rolls_from_evening_to_next_midnight() -> None:
    assert next_market_period(MarketPeriod(date(2026, 8, 25), 2)) == MarketPeriod(
        date(2026, 8, 25), 3
    )
    assert next_market_period(MarketPeriod(date(2026, 8, 25), 3)) == MarketPeriod(
        date(2026, 8, 26), 0
    )


def test_price_curves_are_generous_but_keep_a_meaningful_loss_risk() -> None:
    next_day_profits: list[int] = []
    best_ratios: list[float] = []
    profits_per_bag: list[int] = []
    expiry_profits: list[int] = []
    start = date(2026, 1, 5)
    for guild_number in range(1000, 1100):
        guild_id = str(guild_number)
        for offset in range(28):
            buy_day = start + timedelta(days=offset)
            buy_period = MarketPeriod(buy_day, 0)
            buy_price = quote_for(guild_id, buy_period).buy_price_xp
            sell_prices = [
                quote_for(
                    guild_id,
                    MarketPeriod(buy_day + timedelta(days=held_days), 0),
                ).sell_price_xp
                for held_days in range(1, 8)
            ]
            best_sell = max(sell_prices)
            next_day_profits.append(sell_prices[0] - buy_price)
            best_ratios.append(best_sell / buy_price)
            profits_per_bag.append(best_sell - buy_price)
            expiry_profits.append(sell_prices[-1] - buy_price)

    next_day_win_rate = sum(profit > 0 for profit in next_day_profits) / len(
        next_day_profits
    )
    best_window_win_rate = sum(profit > 0 for profit in profits_per_bag) / len(
        profits_per_bag
    )
    expiry_win_rate = sum(profit > 0 for profit in expiry_profits) / len(expiry_profits)
    mean_best_ratio = sum(best_ratios) / len(best_ratios)
    mean_profit_per_bag = sum(profits_per_bag) / len(profits_per_bag)

    assert 0.70 <= next_day_win_rate < 0.95
    assert 0.97 <= best_window_win_rate <= 1.0
    assert 0.65 <= expiry_win_rate < 0.95
    assert 1.45 <= mean_best_ratio <= 1.90
    assert 45 <= mean_profit_per_bag <= 90


def test_intraday_prices_move_often_and_reward_active_trading() -> None:
    next_period_profits: list[int] = []
    best_window_profits: list[int] = []
    expiry_profits: list[int] = []
    adjacent_price_changes: list[bool] = []
    start = date(2026, 1, 5)
    for guild_number in range(1000, 1100):
        guild_id = str(guild_number)
        for offset in range(28):
            buy_day = start + timedelta(days=offset)
            intraday_sells = [
                quote_for(guild_id, MarketPeriod(buy_day, slot)).sell_price_xp
                for slot in range(4)
            ]
            adjacent_price_changes.extend(
                left != right
                for left, right in zip(intraday_sells, intraday_sells[1:], strict=False)
            )
            for slot in range(4):
                buy_period = MarketPeriod(buy_day, slot)
                buy_price = quote_for(guild_id, buy_period).buy_price_xp
                sell_period = next_market_period(buy_period)
                expiry_day = buy_day + timedelta(days=7)
                future_prices: list[int] = []
                while sell_period.market_day < expiry_day or (
                    sell_period.market_day == expiry_day
                    and sell_period.market_slot == 0
                ):
                    future_prices.append(quote_for(guild_id, sell_period).sell_price_xp)
                    sell_period = next_market_period(sell_period)
                next_period_profits.append(future_prices[0] - buy_price)
                best_window_profits.append(max(future_prices) - buy_price)
                expiry_profits.append(future_prices[-1] - buy_price)

    next_period_win_rate = sum(profit > 0 for profit in next_period_profits) / len(
        next_period_profits
    )
    best_window_win_rate = sum(profit > 0 for profit in best_window_profits) / len(
        best_window_profits
    )
    expiry_win_rate = sum(profit > 0 for profit in expiry_profits) / len(expiry_profits)

    assert sum(adjacent_price_changes) / len(adjacent_price_changes) >= 0.95
    assert 0.80 <= next_period_win_rate < 0.86
    assert 25 <= sum(next_period_profits) / len(next_period_profits) <= 33
    assert 0.99 <= best_window_win_rate <= 1.0
    assert 75 <= sum(best_window_profits) / len(best_window_profits) <= 88
    assert 0.70 <= expiry_win_rate < 0.84
