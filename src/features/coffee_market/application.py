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
    RankingSnapshot,
    SaleResult,
    TradeHistoryEntry,
    UserPosition,
)
from src.features.coffee_market.domain import MarketPeriod


class CoffeeMarketApplication(Protocol):
    async def add_access_role(self, *, guild_id: str, role_id: str) -> bool: ...

    async def remove_access_role(self, *, guild_id: str, role_id: str) -> bool: ...

    async def list_access_role_ids(self, *, guild_id: str) -> tuple[str, ...]: ...

    async def is_user_excluded(self, *, guild_id: str, user_id: str) -> bool: ...

    async def purchase(
        self,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        quantity: int,
        market_period: MarketPeriod,
    ) -> PurchaseResult: ...

    async def sell(
        self,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        quantity: int | None,
        market_period: MarketPeriod,
    ) -> SaleResult: ...

    async def settle_expired(
        self, *, guild_id: str, market_period: MarketPeriod
    ) -> bool: ...

    async def quote(
        self, *, guild_id: str, market_period: MarketPeriod
    ) -> MarketQuote: ...

    async def position(
        self, *, guild_id: str, user_id: str, market_period: MarketPeriod
    ) -> tuple[MarketQuote, UserPosition]: ...

    async def user_history(
        self, *, guild_id: str, user_id: str
    ) -> tuple[TradeHistoryEntry, ...]: ...

    async def pending_ledger_entries(
        self, *, guild_id: str
    ) -> tuple[PublicTradeEntry, ...]: ...

    async def mark_ledger_entry_posted(
        self,
        *,
        guild_id: str,
        kind: str,
        record_id: int,
        message_id: str,
    ) -> bool: ...

    async def rankings(self, *, guild_id: str, market_day: date) -> RankingSnapshot: ...

    async def save_panel(
        self,
        *,
        guild_id: str,
        panel_kind: PanelKind,
        channel_id: str,
        message_id: str,
    ) -> GuildPanelConfig: ...

    async def save_ledger_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> GuildPanelConfig: ...

    async def guild_config(self, *, guild_id: str) -> GuildPanelConfig | None: ...

    async def guild_configs(self) -> tuple[GuildPanelConfig, ...]: ...

    async def activity_version(self, *, guild_id: str) -> tuple[int, int]: ...
