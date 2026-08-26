"""コーヒー豆相場の公開契約。DB・Discord実装には依存しない。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

type PanelKind = Literal["market", "ranking"]


class CoffeeMarketError(RuntimeError):
    """ユーザー操作として扱える豆相場エラー。"""


class CoffeeMarketUnavailable(CoffeeMarketError):
    """市場の永続化基盤を一時的に利用できない。"""


class InvalidQuantity(CoffeeMarketError):
    def __init__(self, *, maximum: int) -> None:
        self.maximum = maximum
        super().__init__("invalid quantity")


class AlreadyPurchasedThisPeriod(CoffeeMarketError):
    pass


class InsufficientXp(CoffeeMarketError):
    def __init__(self, *, required_xp: int, available_xp: int) -> None:
        self.required_xp = required_xp
        self.available_xp = available_xp
        super().__init__("insufficient XP")


class InsufficientBeans(CoffeeMarketError):
    def __init__(self, *, requested: int, available: int) -> None:
        self.requested = requested
        self.available = available
        super().__init__("insufficient sellable beans")


class NoSellableBeans(CoffeeMarketError):
    pass


class IdempotencyConflict(CoffeeMarketError):
    pass


@dataclass(frozen=True)
class MarketQuote:
    market_day: date
    buy_price_xp: int
    sell_price_xp: int
    previous_sell_price_xp: int
    news: str
    market_slot: int = 0

    @property
    def sell_price_change(self) -> int:
        return self.sell_price_xp - self.previous_sell_price_xp


@dataclass(frozen=True)
class PurchaseResult:
    status: str
    market_day: date
    quantity: int
    unit_price_xp: int
    cost_xp: int
    sellable_on: date
    expires_on: date
    available_xp_after: int
    purchased_slot: int = 0
    sellable_slot: int = 0


@dataclass(frozen=True)
class SaleResult:
    status: str
    market_day: date
    sale_kind: str
    quantity: int
    unit_price_xp: int
    payout_xp: int
    cost_basis_xp: int
    available_xp_after: int
    market_slot: int = 0

    @property
    def profit_xp(self) -> int:
        return self.payout_xp - self.cost_basis_xp


@dataclass(frozen=True)
class UserPosition:
    quantity: int
    sellable_quantity: int
    average_buy_price_xp: int
    evaluation_xp: int
    unrealized_profit_xp: int
    earliest_expiry: date | None
    purchased_this_period: bool
    available_xp: int


@dataclass(frozen=True)
class TradeHistoryEntry:
    kind: str
    market_day: date
    quantity: int
    unit_price_xp: int
    total_xp: int
    profit_xp: int | None
    created_at: datetime
    record_id: int = 0
    market_slot: int = 0


@dataclass(frozen=True)
class PublicTradeEntry:
    user_id: str
    kind: str
    market_day: date
    quantity: int
    unit_price_xp: int
    total_xp: int
    profit_xp: int | None
    created_at: datetime
    record_id: int = 0
    market_slot: int = 0


@dataclass(frozen=True)
class RankingEntry:
    user_id: str
    payout_xp: int
    cost_basis_xp: int
    profit_xp: int

    @property
    def profit_rate(self) -> float:
        return self.profit_xp / self.cost_basis_xp * 100


@dataclass(frozen=True)
class RankingSnapshot:
    market_day: date
    daily: tuple[RankingEntry, ...]
    last_five_days: tuple[RankingEntry, ...]
    cumulative: tuple[RankingEntry, ...]


@dataclass(frozen=True)
class GuildPanelConfig:
    guild_id: str
    panel_channel_id: str | None
    panel_message_id: str | None
    ledger_channel_id: str | None
    ranking_channel_id: str | None
    ranking_message_id: str | None
