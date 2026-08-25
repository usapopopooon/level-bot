"""Shared XP wallet and transaction lock.

This module is the integration boundary for features that spend server XP.  Individual
features no longer need to depend on the color-role shop just because it originally
hosted the wallet implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    CoffeeMarketXpTransaction,
    ColorRoleExchange,
    MarimoXpSpend,
    MinecraftItemGachaSpend,
    MinecraftMarketPurchase,
    MinecraftResourceExchange,
    MinecraftXpExchange,
    XpGiftTransfer,
)
from src.features.cafe_gacha.economy import (
    spent_xp_for_user as cafe_spent_xp_for_user,
)


@dataclass(frozen=True)
class Wallet:
    """Earned/received XP and all reserved or completed XP spending."""

    total_xp: int
    spent_xp: int

    @property
    def available_xp(self) -> int:
        return max(0, self.total_xp - self.spent_xp)


async def spent_xp_for_user(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> int:
    """Return XP reserved or committed across every XP-spending feature."""
    color_role_spent = (
        await session.execute(
            select(func.coalesce(func.sum(ColorRoleExchange.cost_xp), 0)).where(
                and_(
                    ColorRoleExchange.guild_id == guild_id,
                    ColorRoleExchange.user_id == user_id,
                )
            )
        )
    ).scalar_one()
    minecraft_spent = (
        await session.execute(
            select(func.coalesce(func.sum(MinecraftXpExchange.cost_xp), 0)).where(
                and_(
                    MinecraftXpExchange.guild_id == guild_id,
                    MinecraftXpExchange.user_id == user_id,
                    MinecraftXpExchange.status.in_(
                        ("pending", "delivering", "completed")
                    ),
                )
            )
        )
    ).scalar_one()
    resource_spent = (
        await session.execute(
            select(func.coalesce(func.sum(MinecraftResourceExchange.cost_xp), 0)).where(
                and_(
                    MinecraftResourceExchange.guild_id == guild_id,
                    MinecraftResourceExchange.user_id == user_id,
                    MinecraftResourceExchange.status.in_(
                        ("pending", "delivering", "completed")
                    ),
                )
            )
        )
    ).scalar_one()
    item_gacha_spent = (
        await session.execute(
            select(func.coalesce(func.sum(MinecraftItemGachaSpend.cost_xp), 0)).where(
                and_(
                    MinecraftItemGachaSpend.guild_id == guild_id,
                    MinecraftItemGachaSpend.user_id == user_id,
                    MinecraftItemGachaSpend.status.in_(("pending", "completed")),
                )
            )
        )
    ).scalar_one()
    market_spent = (
        await session.execute(
            select(func.coalesce(func.sum(MinecraftMarketPurchase.cost_xp), 0)).where(
                and_(
                    MinecraftMarketPurchase.guild_id == guild_id,
                    MinecraftMarketPurchase.buyer_user_id == user_id,
                    MinecraftMarketPurchase.status.in_(("pending", "completed")),
                )
            )
        )
    ).scalar_one()
    cafe_gacha_spent = await cafe_spent_xp_for_user(
        session,
        guild_id=guild_id,
        user_id=user_id,
    )
    marimo_spent = (
        await session.execute(
            select(func.coalesce(func.sum(MarimoXpSpend.cost_xp), 0)).where(
                and_(
                    MarimoXpSpend.guild_id == guild_id,
                    MarimoXpSpend.user_id == user_id,
                    MarimoXpSpend.status == "charged",
                )
            )
        )
    ).scalar_one()
    xp_gift_spent = (
        await session.execute(
            select(func.coalesce(func.sum(XpGiftTransfer.sender_cost_xp), 0)).where(
                and_(
                    XpGiftTransfer.guild_id == guild_id,
                    XpGiftTransfer.sender_user_id == user_id,
                )
            )
        )
    ).scalar_one()
    coffee_market_spent = (
        await session.execute(
            select(
                func.coalesce(func.sum(CoffeeMarketXpTransaction.amount_xp), 0)
            ).where(
                and_(
                    CoffeeMarketXpTransaction.guild_id == guild_id,
                    CoffeeMarketXpTransaction.user_id == user_id,
                    CoffeeMarketXpTransaction.direction == "debit",
                )
            )
        )
    ).scalar_one()
    return (
        int(color_role_spent)
        + int(minecraft_spent)
        + int(resource_spent)
        + int(item_gacha_spent)
        + int(market_spent)
        + int(cafe_gacha_spent)
        + int(marimo_spent)
        + int(xp_gift_spent)
        + int(coffee_market_spent)
    )


async def wallet_for_user(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    total_xp: int,
) -> Wallet:
    """Build the current wallet from earned XP and the shared spending ledger."""
    return Wallet(
        total_xp=max(0, total_xp),
        spent_xp=await spent_xp_for_user(
            session,
            guild_id=guild_id,
            user_id=user_id,
        ),
    )


async def lock_wallet(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> None:
    """Serialize all XP transactions for one guild user."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:wallet_key))"),
        {"wallet_key": f"xp-wallet:{guild_id}:{user_id}"},
    )
