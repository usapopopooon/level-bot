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


def test_rare_market_forecasts_always_match_the_next_quote() -> None:
    forecast_count = 0
    quote_count = 0
    start = date(2026, 1, 5)
    for guild_number in range(1000, 1020):
        guild_id = str(guild_number)
        for offset in range(28):
            market_day = start + timedelta(days=offset)
            for slot in range(4):
                period = MarketPeriod(market_day, slot)
                quote = quote_for(guild_id, period)
                quote_count += 1
                if "市場筋の予測" not in quote.news:
                    continue
                forecast_count += 1
                next_quote = quote_for(guild_id, next_market_period(period))
                if next_quote.sell_price_xp > quote.sell_price_xp:
                    assert "値上がりしそう" in quote.news
                elif next_quote.sell_price_xp < quote.sell_price_xp:
                    assert "値下がりしそう" in quote.news
                else:
                    assert "横ばいになりそう" in quote.news

    assert 0.06 <= forecast_count / quote_count <= 0.10


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

    assert 0.58 <= next_day_win_rate < 0.62
    assert 0.97 <= best_window_win_rate <= 1.0
    assert 0.60 <= expiry_win_rate < 0.64
    assert 1.45 <= mean_best_ratio <= 1.90
    assert 45 <= mean_profit_per_bag <= 90


def test_intraday_prices_move_often_and_reward_active_trading() -> None:
    next_period_profits: list[int] = []
    best_window_profits: list[int] = []
    expiry_profits: list[int] = []
    adjacent_price_changes: list[bool] = []
    current_price_spreads: list[int] = []
    normal_price_spreads: list[int] = []
    surge_news: list[str] = []
    crash_news: list[str] = []
    start = date(2026, 1, 5)
    for guild_number in range(1000, 1100):
        guild_id = str(guild_number)
        for offset in range(28):
            buy_day = start + timedelta(days=offset)
            intraday_quotes = [
                quote_for(guild_id, MarketPeriod(buy_day, slot)) for slot in range(4)
            ]
            intraday_sells = [quote.sell_price_xp for quote in intraday_quotes]
            current_price_spreads.extend(
                abs(quote.sell_price_xp - quote.buy_price_xp)
                for quote in intraday_quotes
            )
            surge_news.extend(
                quote.news
                for quote in intraday_quotes
                if quote.sell_price_xp * 100 >= quote.buy_price_xp * 180
            )
            crash_news.extend(
                quote.news
                for quote in intraday_quotes
                if quote.sell_price_xp * 100 <= quote.buy_price_xp * 75
            )
            normal_price_spreads.extend(
                abs(quote.sell_price_xp - quote.buy_price_xp)
                for quote in intraday_quotes
                if quote.buy_price_xp * 75
                < quote.sell_price_xp * 100
                < quote.buy_price_xp * 180
            )
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
    next_period_loss_rate = sum(profit < 0 for profit in next_period_profits) / len(
        next_period_profits
    )
    best_window_win_rate = sum(profit > 0 for profit in best_window_profits) / len(
        best_window_profits
    )
    expiry_win_rate = sum(profit > 0 for profit in expiry_profits) / len(expiry_profits)
    expiry_loss_rate = sum(profit < 0 for profit in expiry_profits) / len(
        expiry_profits
    )
    next_period_break_even_rate = sum(
        profit == 0 for profit in next_period_profits
    ) / len(next_period_profits)

    assert sum(adjacent_price_changes) / len(adjacent_price_changes) >= 0.95
    assert 21.5 <= sum(current_price_spreads) / len(current_price_spreads) <= 23
    assert 17 <= sum(normal_price_spreads) / len(normal_price_spreads) <= 19
    assert 0.04 <= len(surge_news) / len(current_price_spreads) <= 0.07
    assert 0.02 <= len(crash_news) / len(current_price_spreads) <= 0.04
    assert all("入荷が急減" in news and "売値が急騰" in news for news in surge_news)
    assert all("入荷が急増" in news and "売値が急落" in news for news in crash_news)
    assert 0.58 <= next_period_win_rate < 0.62
    assert 0.20 <= next_period_loss_rate < 0.24
    assert 0.17 <= next_period_break_even_rate < 0.20
    assert 15 <= sum(next_period_profits) / len(next_period_profits) <= 18
    assert 0.99 <= best_window_win_rate <= 1.0
    assert 70 <= sum(best_window_profits) / len(best_window_profits) <= 75
    assert 0.60 <= expiry_win_rate < 0.65
    assert 0.33 <= expiry_loss_rate < 0.37
