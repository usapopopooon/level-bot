"""Minecraftプレイヤー市場のXP予約と売上確定を扱う。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftMarketPurchase
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user

type PurchaseRequestStatus = Literal[
    "reserved", "insufficient_xp", "unavailable", "conflict"
]


@dataclass(frozen=True)
class PurchaseRequestResult:
    status: PurchaseRequestStatus
    purchase: MinecraftMarketPurchase | None
    wallet_before: Wallet
    wallet_after: Wallet
    message: str


@dataclass(frozen=True)
class PendingMarketPurchase:
    event_id: str
    guild_id: str
    listing_id: int
    buyer_user_id: str
    seller_user_id: str
    buyer_minecraft_account_id: str
    seller_minecraft_account_id: str
    cost_xp: int


async def _lock_wallets(
    session: AsyncSession, *, guild_id: str, user_ids: tuple[str, str]
) -> None:
    for user_id in sorted(set(user_ids), key=int):
        await lock_wallet(session, guild_id=guild_id, user_id=user_id)


async def request_purchase(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    listing_id: int,
    buyer_user_id: str,
    seller_user_id: str,
    buyer_minecraft_account_id: str,
    seller_minecraft_account_id: str,
    cost_xp: int,
    buyer_total_xp: int,
    now: datetime | None = None,
) -> PurchaseRequestResult:
    """出品番号と価格を固定し、買い手XPを一度だけ予約する。"""
    if buyer_user_id == seller_user_id or listing_id <= 0 or cost_xp <= 0:
        wallet = await wallet_for_user(
            session,
            guild_id=guild_id,
            user_id=buyer_user_id,
            total_xp=buyer_total_xp,
        )
        await session.rollback()
        return PurchaseRequestResult(
            "unavailable", None, wallet, wallet, "この出品は購入できません。"
        )

    await _lock_wallets(
        session,
        guild_id=guild_id,
        user_ids=(buyer_user_id, seller_user_id),
    )
    wallet_before = await wallet_for_user(
        session,
        guild_id=guild_id,
        user_id=buyer_user_id,
        total_xp=buyer_total_xp,
    )
    existing = (
        await session.execute(
            select(MinecraftMarketPurchase).where(
                MinecraftMarketPurchase.event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        same = (
            existing.guild_id == guild_id
            and existing.listing_id == listing_id
            and existing.buyer_user_id == buyer_user_id
            and existing.seller_user_id == seller_user_id
            and existing.buyer_minecraft_account_id == buyer_minecraft_account_id
            and existing.seller_minecraft_account_id == seller_minecraft_account_id
            and existing.cost_xp == cost_xp
        )
        if not same or existing.status == "cancelled":
            await session.rollback()
            return PurchaseRequestResult(
                "conflict",
                None,
                wallet_before,
                wallet_before,
                "同じ操作IDが別の購入に使用されています。",
            )
        wallet_without_existing = Wallet(
            total_xp=wallet_before.total_xp,
            spent_xp=max(0, wallet_before.spent_xp - existing.cost_xp),
        )
        await session.rollback()
        return PurchaseRequestResult(
            "reserved",
            existing,
            wallet_without_existing,
            wallet_before,
            f"この購入は受付済みです。残り {wallet_before.available_xp:,} XPです。",
        )

    listing_taken = (
        await session.execute(
            select(MinecraftMarketPurchase.id).where(
                MinecraftMarketPurchase.guild_id == guild_id,
                MinecraftMarketPurchase.listing_id == listing_id,
                MinecraftMarketPurchase.status.in_(("pending", "completed")),
            )
        )
    ).scalar_one_or_none()
    if listing_taken is not None:
        await session.rollback()
        return PurchaseRequestResult(
            "unavailable",
            None,
            wallet_before,
            wallet_before,
            "この商品は売り切れました。",
        )
    if wallet_before.available_xp < cost_xp:
        await session.rollback()
        shortage = cost_xp - wallet_before.available_xp
        return PurchaseRequestResult(
            "insufficient_xp",
            None,
            wallet_before,
            wallet_before,
            (
                f"XPが {shortage:,} 不足しています。"
                f"現在XPは {wallet_before.available_xp:,} XPです。"
            ),
        )

    purchase = MinecraftMarketPurchase(
        event_id=event_id,
        guild_id=guild_id,
        listing_id=listing_id,
        buyer_user_id=buyer_user_id,
        seller_user_id=seller_user_id,
        buyer_minecraft_account_id=buyer_minecraft_account_id,
        seller_minecraft_account_id=seller_minecraft_account_id,
        cost_xp=cost_xp,
        status="pending",
        requested_at=now or datetime.now(UTC),
    )
    session.add(purchase)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return PurchaseRequestResult(
            "unavailable",
            None,
            wallet_before,
            wallet_before,
            "この商品はほかの人が購入しました。",
        )
    await session.refresh(purchase)
    wallet_after = Wallet(
        total_xp=wallet_before.total_xp,
        spent_xp=wallet_before.spent_xp + cost_xp,
    )
    return PurchaseRequestResult(
        "reserved",
        purchase,
        wallet_before,
        wallet_after,
        (
            "購入を受け付けました。"
            f"受け取り後の残高は {wallet_after.available_xp:,} XPです。"
        ),
    )


async def list_pending_purchases(
    session: AsyncSession, *, guild_id: str, limit: int
) -> tuple[PendingMarketPurchase, ...]:
    rows = (
        await session.execute(
            select(MinecraftMarketPurchase)
            .where(
                MinecraftMarketPurchase.guild_id == guild_id,
                MinecraftMarketPurchase.status == "pending",
            )
            .order_by(
                MinecraftMarketPurchase.requested_at,
                MinecraftMarketPurchase.id,
            )
            .limit(limit)
        )
    ).scalars()
    return tuple(
        PendingMarketPurchase(
            event_id=row.event_id,
            guild_id=row.guild_id,
            listing_id=row.listing_id,
            buyer_user_id=row.buyer_user_id,
            seller_user_id=row.seller_user_id,
            buyer_minecraft_account_id=row.buyer_minecraft_account_id,
            seller_minecraft_account_id=row.seller_minecraft_account_id,
            cost_xp=row.cost_xp,
        )
        for row in rows
    )


async def update_purchase(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    action: Literal["complete", "cancel"],
) -> bool:
    target = "completed" if action == "complete" else "cancelled"
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftMarketPurchase)
            .where(
                MinecraftMarketPurchase.event_id == event_id,
                MinecraftMarketPurchase.guild_id == guild_id,
                MinecraftMarketPurchase.status == "pending",
            )
            .values(status=target, completed_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftMarketPurchase.id).where(
                and_(
                    MinecraftMarketPurchase.event_id == event_id,
                    MinecraftMarketPurchase.guild_id == guild_id,
                    MinecraftMarketPurchase.status == target,
                )
            )
        )
    ).scalar_one_or_none() is not None
