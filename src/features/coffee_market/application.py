"""Discordなどの呼び出し側が利用する、実装非依存の市場境界。"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from src.features.coffee_market.contracts import (
    GuildPanelConfig,
    MarketQuote,
    PanelKind,
    PublicTradeEntry,
    PurchaseResult,
    RankingEntry,
    SaleResult,
    TradeHistoryEntry,
    UserPosition,
)


class CoffeeMarketApplication(Protocol):
    async def is_user_excluded(self, *, guild_id: str, user_id: str) -> bool: ...

    async def purchase(
        self,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        quantity: int,
        market_day: date,
    ) -> PurchaseResult: ...

    async def sell(
        self,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        quantity: int | None,
        market_day: date,
    ) -> SaleResult: ...

    async def settle_expired(self, *, guild_id: str, market_day: date) -> bool: ...

    async def quote(self, *, guild_id: str, market_day: date) -> MarketQuote: ...

    async def position(
        self, *, guild_id: str, user_id: str, market_day: date
    ) -> tuple[MarketQuote, UserPosition]: ...

    async def user_history(
        self, *, guild_id: str, user_id: str
    ) -> tuple[TradeHistoryEntry, ...]: ...

    async def public_ledger(self, *, guild_id: str) -> tuple[PublicTradeEntry, ...]: ...

    async def weekly_ranking(
        self, *, guild_id: str, market_day: date
    ) -> tuple[RankingEntry, ...]: ...

    async def save_panel(
        self,
        *,
        guild_id: str,
        panel_kind: PanelKind,
        channel_id: str,
        message_id: str,
    ) -> GuildPanelConfig: ...

    async def guild_config(self, *, guild_id: str) -> GuildPanelConfig | None: ...

    async def guild_configs(self) -> tuple[GuildPanelConfig, ...]: ...

    async def activity_version(self, *, guild_id: str) -> tuple[int, int]: ...
