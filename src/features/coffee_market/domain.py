"""Discord やDBに依存しない、コーヒー豆相場の規則。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("Asia/Tokyo")
MARKET_UPDATE_HOURS = (0, 6, 12, 18)
LOT_LIFETIME_DAYS = 7
MAX_PURCHASE_QUANTITY_PER_PERIOD = 10
MAX_DAILY_PURCHASE_QUANTITY = MAX_PURCHASE_QUANTITY_PER_PERIOD * len(
    MARKET_UPDATE_HOURS
)
MAX_SELL_QUANTITY = MAX_DAILY_PURCHASE_QUANTITY * LOT_LIFETIME_DAYS
RANKING_WINDOW_DAYS = 5
NORMAL_PRICE_MARGIN_MIN_XP = 2
NORMAL_PRICE_MARGIN_MAX_XP = 9
OUTLIER_SURGE_RATIO_PERCENT = 180
OUTLIER_CRASH_RATIO_PERCENT = 75
SURGE_EVENT_PER_MILLE_ON_WIN = 12
CRASH_EVENT_PER_MILLE_ON_LOSS = 15
FORECAST_NEWS_PERCENT = 8
SURGE_NEWS = (
    "一部産地からの入荷が急減し、買い付けが集中しています。豆の売値が急騰しています。"
)
CRASH_NEWS = (
    "豊作と大口在庫の放出が重なり、市場への入荷が急増しています。"
    "豆の売値が急落しています。"
)
LOW_PRICE_NEWS = "入荷が増え、売値が買値を下回る安値相場になっています。"
NORMAL_DAILY_OUTCOME_ORDERS = (
    ("win", "break_even", "win", "loss"),
    ("win", "loss", "win", "break_even"),
    ("break_even", "win", "loss", "win"),
    ("loss", "win", "break_even", "win"),
    ("win", "break_even", "loss", "win"),
    ("win", "loss", "break_even", "win"),
    ("break_even", "win", "win", "loss"),
    ("loss", "win", "win", "break_even"),
    ("win", "win", "break_even", "loss"),
    ("win", "win", "loss", "break_even"),
    ("break_even", "loss", "win", "win"),
    ("loss", "break_even", "win", "win"),
)
RISK_DAILY_OUTCOME_ORDERS = (
    ("win", "break_even", "loss", "loss"),
    ("win", "loss", "break_even", "loss"),
    ("win", "loss", "loss", "break_even"),
    ("break_even", "win", "loss", "loss"),
    ("break_even", "loss", "win", "loss"),
    ("break_even", "loss", "loss", "win"),
    ("loss", "win", "break_even", "loss"),
    ("loss", "win", "loss", "break_even"),
    ("loss", "break_even", "win", "loss"),
    ("loss", "break_even", "loss", "win"),
    ("loss", "loss", "win", "break_even"),
    ("loss", "loss", "break_even", "win"),
)


@dataclass(frozen=True)
class QuoteSpec:
    market_day: date
    market_slot: int
    buy_price_xp: int
    sell_price_xp: int
    previous_sell_price_xp: int
    news: str


@dataclass(frozen=True, order=True)
class MarketPeriod:
    market_day: date
    market_slot: int

    def __post_init__(self) -> None:
        if not 0 <= self.market_slot < len(MARKET_UPDATE_HOURS):
            msg = "market_slot is out of range"
            raise ValueError(msg)

    @property
    def update_hour(self) -> int:
        return MARKET_UPDATE_HOURS[self.market_slot]


def market_period_for(now: datetime) -> MarketPeriod:
    """現在時刻を含む日本時間の6時間相場枠を返す。"""
    if now.tzinfo is None:
        msg = "now must be timezone-aware"
        raise ValueError(msg)
    local = now.astimezone(MARKET_TIMEZONE)
    slot = max(
        index
        for index, update_hour in enumerate(MARKET_UPDATE_HOURS)
        if update_hour <= local.hour
    )
    return MarketPeriod(local.date(), slot)


def market_day_for(now: datetime) -> date:
    """日本時間0時を境界とする相場日を返す。"""
    return market_period_for(now).market_day


def next_market_period(period: MarketPeriod) -> MarketPeriod:
    if period.market_slot + 1 < len(MARKET_UPDATE_HOURS):
        return MarketPeriod(period.market_day, period.market_slot + 1)
    return MarketPeriod(period.market_day + timedelta(days=1), 0)


def previous_market_period(period: MarketPeriod) -> MarketPeriod:
    if period.market_slot > 0:
        return MarketPeriod(period.market_day, period.market_slot - 1)
    return MarketPeriod(
        period.market_day - timedelta(days=1),
        len(MARKET_UPDATE_HOURS) - 1,
    )


def next_reset_at(now: datetime) -> datetime:
    """現在時刻より後に来る次の日本時間の相場更新時刻を返す。"""
    if now.tzinfo is None:
        msg = "now must be timezone-aware"
        raise ValueError(msg)
    local = now.astimezone(MARKET_TIMEZONE)
    next_period = next_market_period(market_period_for(local))
    return datetime(
        next_period.market_day.year,
        next_period.market_day.month,
        next_period.market_day.day,
        next_period.update_hour,
        tzinfo=MARKET_TIMEZONE,
    )


def _hash_int(*parts: object) -> int:
    payload = ":".join(str(part) for part in parts).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _pattern_for(guild_id: str, day: date) -> tuple[str, int, int]:
    week = _week_start(day)
    seed = _hash_int("coffee-market-week", guild_id, week.isoformat())
    roll = seed % 100
    if roll < 35:
        pattern = "stable"
    elif roll < 60:
        pattern = "rising"
    elif roll < 80:
        pattern = "spike"
    elif roll < 92:
        pattern = "falling"
    else:
        pattern = "volatile"
    base_price = 90 + (seed // 101) % 21
    spike_day = 1 + (seed // 211) % 5
    return pattern, base_price, spike_day


def _sell_basis_points(pattern: str, weekday: int, spike_day: int) -> int:
    curves = {
        "stable": (115, 126, 120, 135, 124, 142, 130),
        "rising": (92, 105, 120, 138, 158, 176, 192),
        "falling": (178, 158, 142, 126, 112, 98, 86),
        "volatile": (94, 162, 108, 188, 92, 152, 122),
    }
    if pattern != "spike":
        return curves[pattern][weekday]
    distance = weekday - spike_day
    spike_curve = {
        -5: 78,
        -4: 82,
        -3: 88,
        -2: 98,
        -1: 118,
        0: 215,
        1: 168,
        2: 130,
        3: 105,
        4: 88,
        5: 78,
    }
    return spike_curve[distance]


def _is_surge_price(*, buy_price: int, sell_price: int) -> bool:
    return sell_price * 100 >= buy_price * OUTLIER_SURGE_RATIO_PERCENT


def _is_crash_price(*, buy_price: int, sell_price: int) -> bool:
    return sell_price * 100 <= buy_price * OUTLIER_CRASH_RATIO_PERCENT


@lru_cache(maxsize=32_768)
def _normal_margin_for(guild_id: str, period: MarketPeriod) -> int:
    width = NORMAL_PRICE_MARGIN_MAX_XP - NORMAL_PRICE_MARGIN_MIN_XP + 1
    return NORMAL_PRICE_MARGIN_MIN_XP + (
        _hash_int(
            "coffee-market-normal-margin",
            guild_id,
            period.market_day.isoformat(),
            period.market_slot,
        )
        % width
    )


@lru_cache(maxsize=32_768)
def _buy_price_for(guild_id: str, period: MarketPeriod) -> int:
    day = period.market_day
    _pattern, base_price, _spike_day = _pattern_for(guild_id, day)
    day_seed = _hash_int("coffee-market-day", guild_id, day.isoformat())
    buy_price = max(75, min(125, base_price + day_seed % 17 - 8))
    intraday_seed = _hash_int(
        "coffee-market-period",
        guild_id,
        day.isoformat(),
        period.market_slot,
    )
    buy_offsets = (0, -3, 2, -1)
    intraday_buy_jitter = 0 if period.market_slot == 0 else intraday_seed % 5 - 2
    return max(
        75,
        min(
            125,
            buy_price + buy_offsets[period.market_slot] + intraday_buy_jitter,
        ),
    )


@lru_cache(maxsize=32_768)
def _normal_outcome_for(guild_id: str, period: MarketPeriod) -> str:
    """各相場日に通常の黒字・同値・赤字を偏りなく割り当てる。"""
    order_seed = _hash_int(
        "coffee-market-daily-outcomes",
        guild_id,
        period.market_day.isoformat(),
    )
    orders = (
        RISK_DAILY_OUTCOME_ORDERS
        if (order_seed // len(NORMAL_DAILY_OUTCOME_ORDERS)) % 3 == 0
        else NORMAL_DAILY_OUTCOME_ORDERS
    )
    start_index = order_seed % len(orders)
    for offset in range(len(orders)):
        order = orders[(start_index + offset) % len(orders)]
        for market_slot, outcome in enumerate(order):
            if outcome != "loss":
                continue
            candidate = MarketPeriod(period.market_day, market_slot)
            previous = previous_market_period(candidate)
            sell_price = _buy_price_for(guild_id, previous) - _normal_margin_for(
                guild_id, candidate
            )
            if sell_price < _buy_price_for(guild_id, candidate):
                return order[period.market_slot]
    return orders[start_index][period.market_slot]


def _outlier_price_for(
    guild_id: str,
    period: MarketPeriod,
    *,
    buy_price: int,
    outcome: str,
) -> int | None:
    seed = _hash_int(
        "coffee-market-outlier",
        guild_id,
        period.market_day.isoformat(),
        period.market_slot,
    )
    roll = seed % 1000
    if outcome == "win" and roll < SURGE_EVENT_PER_MILLE_ON_WIN:
        ratio = OUTLIER_SURGE_RATIO_PERCENT + (seed // 1000) % 41
        return min(250, round(buy_price * ratio / 100))
    if outcome == "loss" and roll < CRASH_EVENT_PER_MILLE_ON_LOSS:
        ratio = 45 + (seed // 1000) % (OUTLIER_CRASH_RATIO_PERCENT - 44)
        return max(35, round(buy_price * ratio / 100))
    return None


def _base_prices_for(
    guild_id: str,
    period: MarketPeriod,
) -> tuple[int, int, str]:
    day = period.market_day
    pattern, base_price, spike_day = _pattern_for(guild_id, day)
    day_seed = _hash_int("coffee-market-day", guild_id, day.isoformat())
    sell_jitter = (day_seed // 37) % 7 - 3
    buy_price = _buy_price_for(guild_id, period)
    basis_points = _sell_basis_points(pattern, day.weekday(), spike_day)
    daily_sell_price = round(base_price * basis_points / 100) + sell_jitter
    intraday_seed = _hash_int(
        "coffee-market-period",
        guild_id,
        day.isoformat(),
        period.market_slot,
    )
    sell_multipliers = (89, 95, 87, 99)
    intraday_sell_jitter = (
        0 if period.market_slot == 0 else (intraday_seed // 17) % 7 - 3
    )
    sell_price = max(
        35,
        min(
            250,
            round(daily_sell_price * sell_multipliers[period.market_slot] / 100)
            + intraday_sell_jitter,
        ),
    )
    outlier_price = _outlier_price_for(
        guild_id,
        period,
        buy_price=buy_price,
        outcome=_normal_outcome_for(guild_id, period),
    )
    if outlier_price is None:
        normal_min = buy_price * OUTLIER_CRASH_RATIO_PERCENT // 100 + 1
        normal_max = (buy_price * OUTLIER_SURGE_RATIO_PERCENT - 1) // 100
        sell_price = max(normal_min, min(normal_max, sell_price))
    else:
        sell_price = outlier_price
    is_surge = _is_surge_price(buy_price=buy_price, sell_price=sell_price)
    is_crash = _is_crash_price(buy_price=buy_price, sell_price=sell_price)
    news_by_pattern = {
        "stable": "いつも通りの入荷が続いています。",
        "rising": "豆を求める店が少しずつ増えているようです。",
        "spike": "一部の産地で入荷が不安定になっています。",
        "falling": "市場には十分な量の豆が届いています。",
        "volatile": "買い付けの噂が入り交じり、落ち着かない相場です。",
    }
    news = news_by_pattern[pattern]
    if is_surge:
        news = SURGE_NEWS
    elif is_crash:
        news = CRASH_NEWS
    return buy_price, sell_price, news


def _prices_for(guild_id: str, period: MarketPeriod) -> tuple[int, int, str]:
    buy_price, sell_price, news = _base_prices_for(guild_id, period)
    previous_buy_price, _previous_sell_price, _previous_news = _base_prices_for(
        guild_id, previous_market_period(period)
    )
    is_outlier = _is_surge_price(
        buy_price=buy_price,
        sell_price=sell_price,
    ) or _is_crash_price(
        buy_price=buy_price,
        sell_price=sell_price,
    )
    outcome = _normal_outcome_for(guild_id, period)
    if is_outlier:
        if _is_surge_price(buy_price=buy_price, sell_price=sell_price):
            sell_price = max(
                sell_price,
                round(
                    max(buy_price, previous_buy_price)
                    * OUTLIER_SURGE_RATIO_PERCENT
                    / 100
                ),
            )
            news = SURGE_NEWS
        else:
            sell_price = min(
                sell_price,
                round(
                    min(buy_price, previous_buy_price)
                    * OUTLIER_CRASH_RATIO_PERCENT
                    / 100
                ),
            )
            news = CRASH_NEWS
    else:
        margin = _normal_margin_for(guild_id, period)
        if outcome == "win":
            sell_price = previous_buy_price + margin
        elif outcome == "break_even":
            sell_price = previous_buy_price
        else:
            sell_price = previous_buy_price - margin
    if _is_crash_price(buy_price=buy_price, sell_price=sell_price):
        news = CRASH_NEWS
    elif sell_price < buy_price:
        news = LOW_PRICE_NEWS
    return buy_price, sell_price, news


def should_publish_forecast(guild_id: str, period: MarketPeriod) -> bool:
    return (
        _hash_int(
            "coffee-market-forecast",
            guild_id,
            period.market_day.isoformat(),
            period.market_slot,
        )
        % 100
        < FORECAST_NEWS_PERCENT
    )


def forecast_news_for(
    guild_id: str,
    period: MarketPeriod,
    *,
    current_sell_price: int,
    next_sell_price: int,
) -> str | None:
    if not should_publish_forecast(guild_id, period):
        return None
    if next_sell_price > current_sell_price:
        direction = "値上がりしそうです"
    elif next_sell_price < current_sell_price:
        direction = "値下がりしそうです"
    else:
        direction = "横ばいになりそうです"
    return f"市場筋の予測では、次の相場は{direction}。"


def quote_for(
    guild_id: str,
    period: MarketPeriod,
    *,
    include_forecast: bool = True,
) -> QuoteSpec:
    """サーバーと相場枠から、再実行しても同じ6時間価格を生成する。"""
    if not guild_id.isdigit():
        msg = "guild_id must be a digit string"
        raise ValueError(msg)
    buy_price, sell_price, news = _prices_for(guild_id, period)
    if include_forecast:
        _next_buy, next_sell_price, _next_news = _prices_for(
            guild_id, next_market_period(period)
        )
        forecast_news = forecast_news_for(
            guild_id,
            period,
            current_sell_price=sell_price,
            next_sell_price=next_sell_price,
        )
        if forecast_news is not None:
            news = f"{news}\n{forecast_news}"
    previous_period = previous_market_period(period)
    _previous_buy, previous_sell, _previous_news = _prices_for(
        guild_id, previous_period
    )
    return QuoteSpec(
        market_day=period.market_day,
        market_slot=period.market_slot,
        buy_price_xp=buy_price,
        sell_price_xp=sell_price,
        previous_sell_price_xp=previous_sell,
        news=news,
    )
