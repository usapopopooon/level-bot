"""Discord やDBに依存しない、コーヒー豆相場の規則。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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


def _prices_for(guild_id: str, period: MarketPeriod) -> tuple[int, int, str]:
    day = period.market_day
    pattern, base_price, spike_day = _pattern_for(guild_id, day)
    day_seed = _hash_int("coffee-market-day", guild_id, day.isoformat())
    buy_jitter = day_seed % 17 - 8
    sell_jitter = (day_seed // 37) % 7 - 3
    buy_price = max(75, min(125, base_price + buy_jitter))
    basis_points = _sell_basis_points(pattern, day.weekday(), spike_day)
    daily_sell_price = round(base_price * basis_points / 100) + sell_jitter
    intraday_seed = _hash_int(
        "coffee-market-period",
        guild_id,
        day.isoformat(),
        period.market_slot,
    )
    buy_offsets = (0, -3, 2, -1)
    sell_multipliers = (97, 101, 95, 105)
    intraday_buy_jitter = 0 if period.market_slot == 0 else intraday_seed % 5 - 2
    intraday_sell_jitter = (
        0 if period.market_slot == 0 else (intraday_seed // 17) % 7 - 3
    )
    buy_price = max(
        75,
        min(
            125,
            buy_price + buy_offsets[period.market_slot] + intraday_buy_jitter,
        ),
    )
    sell_price = max(
        35,
        min(
            250,
            round(daily_sell_price * sell_multipliers[period.market_slot] / 100)
            + intraday_sell_jitter,
        ),
    )
    news_by_pattern = {
        "stable": "いつも通りの入荷が続いています。",
        "rising": "豆を求める店が少しずつ増えているようです。",
        "spike": "一部の産地で入荷が不安定になっています。",
        "falling": "市場には十分な量の豆が届いています。",
        "volatile": "買い付けの噂が入り交じり、落ち着かない相場です。",
    }
    return buy_price, sell_price, news_by_pattern[pattern]


def quote_for(guild_id: str, period: MarketPeriod) -> QuoteSpec:
    """サーバーと相場枠から、再実行しても同じ6時間価格を生成する。"""
    if not guild_id.isdigit():
        msg = "guild_id must be a digit string"
        raise ValueError(msg)
    buy_price, sell_price, news = _prices_for(guild_id, period)
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
