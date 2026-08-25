"""level-bot内のXP台帳へ接続するアダプター。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import CoffeeMarketXpTransaction
from src.features.coffee_market.ports import (
    CoffeeMarketDependencies,
    XpMovementConflict,
    XpMovementResult,
    XpWalletSnapshot,
)
from src.features.economy.service import lock_wallet, wallet_for_user
from src.features.guilds.service import stage_level_role_sync
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels


class LevelBotXpWallet:
    async def _balance(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
    ) -> XpWalletSnapshot:
        levels = await get_user_lifetime_levels(session, guild_id, user_id)
        total_xp = 0 if levels is None else earned_total_xp(levels)
        wallet = await wallet_for_user(
            session,
            guild_id=guild_id,
            user_id=user_id,
            total_xp=total_xp,
        )
        return XpWalletSnapshot(
            total_xp=wallet.total_xp,
            spent_xp=wallet.spent_xp,
            available_xp=wallet.available_xp,
        )

    async def get_balance(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
    ) -> XpWalletSnapshot:
        await lock_wallet(session, guild_id=guild_id, user_id=user_id)
        return await self._balance(session, guild_id=guild_id, user_id=user_id)

    async def _existing(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        direction: str,
        amount_xp: int,
    ) -> CoffeeMarketXpTransaction | None:
        row = (
            await session.execute(
                select(CoffeeMarketXpTransaction).where(
                    CoffeeMarketXpTransaction.event_id == event_id
                )
            )
        ).scalar_one_or_none()
        if row is not None and (
            row.guild_id != guild_id
            or row.user_id != user_id
            or row.direction != direction
            or row.amount_xp != amount_xp
        ):
            raise XpMovementConflict
        return row

    async def debit(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        amount_xp: int,
    ) -> XpMovementResult:
        await lock_wallet(session, guild_id=guild_id, user_id=user_id)
        existing = await self._existing(
            session,
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            direction="debit",
            amount_xp=amount_xp,
        )
        balance = await self._balance(session, guild_id=guild_id, user_id=user_id)
        if existing is not None:
            return XpMovementResult(
                status="already_completed",
                available_xp_before=balance.available_xp + amount_xp,
                available_xp_after=balance.available_xp,
            )
        if balance.available_xp < amount_xp:
            return XpMovementResult(
                status="insufficient",
                available_xp_before=balance.available_xp,
                available_xp_after=balance.available_xp,
            )
        session.add(
            CoffeeMarketXpTransaction(
                event_id=event_id,
                guild_id=guild_id,
                user_id=user_id,
                direction="debit",
                amount_xp=amount_xp,
            )
        )
        await session.flush()
        return XpMovementResult(
            status="completed",
            available_xp_before=balance.available_xp,
            available_xp_after=balance.available_xp - amount_xp,
        )

    async def credit(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        amount_xp: int,
    ) -> XpMovementResult:
        await lock_wallet(session, guild_id=guild_id, user_id=user_id)
        existing = await self._existing(
            session,
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            direction="credit",
            amount_xp=amount_xp,
        )
        balance = await self._balance(session, guild_id=guild_id, user_id=user_id)
        if existing is not None:
            return XpMovementResult(
                status="already_completed",
                available_xp_before=max(0, balance.available_xp - amount_xp),
                available_xp_after=balance.available_xp,
            )
        session.add(
            CoffeeMarketXpTransaction(
                event_id=event_id,
                guild_id=guild_id,
                user_id=user_id,
                direction="credit",
                amount_xp=amount_xp,
            )
        )
        await session.flush()
        return XpMovementResult(
            status="completed",
            available_xp_before=balance.available_xp,
            available_xp_after=balance.available_xp + amount_xp,
        )


class LevelBotLevelSync:
    async def request(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> None:
        await stage_level_role_sync(session, guild_id)


LEVEL_BOT_DEPENDENCIES = CoffeeMarketDependencies(
    xp_wallet=LevelBotXpWallet(),
    level_sync=LevelBotLevelSync(),
)
