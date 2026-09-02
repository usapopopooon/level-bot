"""Ports for data used by marimo integrations but owned by other features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CafeCardBalance:
    current_count: int
    redeemable_count: int


class CafeCardInventoryPort(Protocol):
    async def card_balance(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
        card_key: str,
    ) -> CafeCardBalance: ...


class RankingAudiencePort(Protocol):
    async def blocked_user_ids(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> set[str]: ...


@dataclass(frozen=True)
class MarimoXpDependencies:
    cafe_card_inventory: CafeCardInventoryPort
    ranking_audience: RankingAudiencePort
