"""level-bot内で市場ユースケースを実行するアプリケーションアダプター。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.engine import async_session
from src.database.models import CoffeeMarketGuildConfig
from src.features.coffee_market import service
from src.features.coffee_market.adapters.level_bot import LEVEL_BOT_DEPENDENCIES
from src.features.coffee_market.contracts import (
    CoffeeMarketUnavailable,
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
from src.features.feature_access import service as feature_access_service
from src.features.guilds import service as guilds_service


@asynccontextmanager
async def _market_session() -> AsyncIterator[AsyncSession]:
    try:
        async with async_session() as session:
            yield session
    except SQLAlchemyError as error:
        raise CoffeeMarketUnavailable from error


def _config_view(row: CoffeeMarketGuildConfig) -> GuildPanelConfig:
    return GuildPanelConfig(
        guild_id=row.guild_id,
        panel_channel_id=row.panel_channel_id,
        panel_message_id=row.panel_message_id,
        ledger_channel_id=row.ledger_channel_id,
        ranking_channel_id=row.ranking_channel_id,
        ranking_message_id=row.ranking_message_id,
    )


class LevelBotCoffeeMarketApplication:
    """市場DB・XP・レベル同期を同じlevel-botトランザクションで扱う。"""

    async def add_access_role(self, *, guild_id: str, role_id: str) -> bool:
        async with _market_session() as session:
            return await feature_access_service.add_access_role(
                session,
                guild_id=guild_id,
                feature=feature_access_service.COFFEE_MARKET,
                role_id=role_id,
            )

    async def remove_access_role(self, *, guild_id: str, role_id: str) -> bool:
        async with _market_session() as session:
            return await feature_access_service.remove_access_role(
                session,
                guild_id=guild_id,
                feature=feature_access_service.COFFEE_MARKET,
                role_id=role_id,
            )

    async def list_access_role_ids(self, *, guild_id: str) -> tuple[str, ...]:
        async with _market_session() as session:
            return await feature_access_service.list_access_role_ids(
                session,
                guild_id=guild_id,
                feature=feature_access_service.COFFEE_MARKET,
            )

    async def is_user_excluded(self, *, guild_id: str, user_id: str) -> bool:
        async with _market_session() as session:
            return await guilds_service.is_user_excluded(session, guild_id, user_id)

    async def purchase(
        self,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        quantity: int,
        market_period: MarketPeriod,
    ) -> PurchaseResult:
        async with _market_session() as session:
            return await service.purchase_beans(
                session,
                event_id=event_id,
                guild_id=guild_id,
                user_id=user_id,
                quantity=quantity,
                market_period=market_period,
                dependencies=LEVEL_BOT_DEPENDENCIES,
            )

    async def sell(
        self,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        quantity: int | None,
        market_period: MarketPeriod,
    ) -> SaleResult:
        async with _market_session() as session:
            return await service.sell_beans(
                session,
                event_id=event_id,
                guild_id=guild_id,
                user_id=user_id,
                quantity=quantity,
                market_period=market_period,
                dependencies=LEVEL_BOT_DEPENDENCIES,
            )

    async def settle_expired(
        self, *, guild_id: str, market_period: MarketPeriod
    ) -> bool:
        async with _market_session() as session:
            settled = await service.settle_expired_lots(
                session,
                guild_id=guild_id,
                market_period=market_period,
                dependencies=LEVEL_BOT_DEPENDENCIES,
            )
        return bool(settled)

    async def quote(self, *, guild_id: str, market_period: MarketPeriod) -> MarketQuote:
        async with _market_session() as session:
            return await service.get_quote(
                session, guild_id=guild_id, market_period=market_period
            )

    async def position(
        self, *, guild_id: str, user_id: str, market_period: MarketPeriod
    ) -> tuple[MarketQuote, UserPosition]:
        async with _market_session() as session:
            return await service.get_user_position(
                session,
                guild_id=guild_id,
                user_id=user_id,
                market_period=market_period,
                dependencies=LEVEL_BOT_DEPENDENCIES,
            )

    async def user_history(
        self, *, guild_id: str, user_id: str
    ) -> tuple[TradeHistoryEntry, ...]:
        async with _market_session() as session:
            return await service.list_user_history(
                session, guild_id=guild_id, user_id=user_id
            )

    async def pending_ledger_entries(
        self, *, guild_id: str
    ) -> tuple[PublicTradeEntry, ...]:
        async with _market_session() as session:
            return await service.list_pending_ledger_entries(session, guild_id=guild_id)

    async def mark_ledger_entry_posted(
        self,
        *,
        guild_id: str,
        kind: str,
        record_id: int,
        message_id: str,
    ) -> bool:
        async with _market_session() as session:
            return await service.mark_ledger_entry_posted(
                session,
                guild_id=guild_id,
                kind=kind,
                record_id=record_id,
                message_id=message_id,
            )

    async def rankings(self, *, guild_id: str, market_day: date) -> RankingSnapshot:
        async with _market_session() as session:
            return await service.rankings(
                session, guild_id=guild_id, market_day=market_day
            )

    async def save_panel(
        self,
        *,
        guild_id: str,
        panel_kind: PanelKind,
        channel_id: str,
        message_id: str,
    ) -> GuildPanelConfig:
        async with _market_session() as session:
            row = await service.save_panel_placement(
                session,
                guild_id=guild_id,
                panel_kind=panel_kind,
                channel_id=channel_id,
                message_id=message_id,
            )
            return _config_view(row)

    async def save_ledger_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> GuildPanelConfig:
        async with _market_session() as session:
            row = await service.save_ledger_channel(
                session,
                guild_id=guild_id,
                channel_id=channel_id,
            )
            return _config_view(row)

    async def guild_config(self, *, guild_id: str) -> GuildPanelConfig | None:
        async with _market_session() as session:
            row = await service.get_guild_config(session, guild_id=guild_id)
            return None if row is None else _config_view(row)

    async def guild_configs(self) -> tuple[GuildPanelConfig, ...]:
        async with _market_session() as session:
            rows = await service.list_guild_configs(session)
            return tuple(_config_view(row) for row in rows)

    async def activity_version(self, *, guild_id: str) -> tuple[int, int]:
        async with _market_session() as session:
            return await service.get_public_activity_version(session, guild_id=guild_id)


LEVEL_BOT_COFFEE_MARKET_APPLICATION = LevelBotCoffeeMarketApplication()
