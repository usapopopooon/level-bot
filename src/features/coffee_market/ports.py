"""同一DBトランザクション内で使う市場インフラ境界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class XpWalletSnapshot:
    total_xp: int
    spent_xp: int
    available_xp: int


type XpMovementStatus = Literal["completed", "already_completed", "insufficient"]


@dataclass(frozen=True)
class XpMovementResult:
    status: XpMovementStatus
    available_xp_before: int
    available_xp_after: int


class XpMovementConflict(RuntimeError):
    pass


class XpWalletPort(Protocol):
    """市場DBと原子的に更新する、トランザクション内XP接続。"""

    async def get_balance(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
    ) -> XpWalletSnapshot: ...

    async def debit(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        amount_xp: int,
    ) -> XpMovementResult: ...

    async def credit(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        amount_xp: int,
    ) -> XpMovementResult: ...


class LevelSyncPort(Protocol):
    async def request(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> None: ...


@dataclass(frozen=True)
class CoffeeMarketDependencies:
    xp_wallet: XpWalletPort
    level_sync: LevelSyncPort
