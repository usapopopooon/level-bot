"""Minecraft資源交換の予約・配信状態・消費台帳を扱う。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftResourceExchange, MinecraftVoicePresence
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user
from src.features.minecraft_xp_shop.service import ONLINE_PRESENCE_MAX_AGE

type ResourceItemId = Literal["minecraft:diamond", "minecraft:emerald"]
RESOURCE_ITEM_NAMES: dict[ResourceItemId, str] = {
    "minecraft:diamond": "ダイヤモンド",
    "minecraft:emerald": "エメラルド",
}


@dataclass(frozen=True)
class MinecraftResourcePack:
    item_id: ResourceItemId
    item_name: str
    item_count: int
    cost_xp: int


MINECRAFT_RESOURCE_PACKS = (
    MinecraftResourcePack("minecraft:emerald", "エメラルド", 4, 50),
    MinecraftResourcePack("minecraft:emerald", "エメラルド", 16, 180),
    MinecraftResourcePack("minecraft:diamond", "ダイヤモンド", 1, 200),
    MinecraftResourcePack("minecraft:diamond", "ダイヤモンド", 3, 550),
    MinecraftResourcePack("minecraft:diamond", "ダイヤモンド", 8, 1_400),
)

type ExchangeRequestStatus = Literal[
    "reserved", "offline", "insufficient_xp", "unavailable"
]


@dataclass(frozen=True)
class ExchangeRequestResult:
    status: ExchangeRequestStatus
    exchange_id: int | None
    pack: MinecraftResourcePack | None
    wallet_before: Wallet
    wallet_after: Wallet
    message: str


@dataclass(frozen=True)
class PendingMinecraftResourceExchange:
    id: int
    event_id: str
    guild_id: str
    user_id: str
    minecraft_account_id: str
    item_id: ResourceItemId
    item_name: str
    item_count: int
    cost_xp: int
    status: Literal["pending", "delivering"]


def find_pack(item_id: str, item_count: int) -> MinecraftResourcePack | None:
    return next(
        (
            pack
            for pack in MINECRAFT_RESOURCE_PACKS
            if pack.item_id == item_id and pack.item_count == item_count
        ),
        None,
    )


async def request_exchange(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    request_id: str,
    item_id: str,
    item_count: int,
    expected_cost_xp: int,
    total_xp: int,
    now: datetime | None = None,
) -> ExchangeRequestResult:
    """オンライン状態と残高を確認し、資源付与待ちの交換を予約する。"""
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    wallet_before = await wallet_for_user(
        session, guild_id=guild_id, user_id=user_id, total_xp=total_xp
    )
    existing = (
        await session.execute(
            select(MinecraftResourceExchange).where(
                MinecraftResourceExchange.event_id == request_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        same_request = (
            existing.guild_id == guild_id
            and existing.user_id == user_id
            and existing.item_id == item_id
            and existing.item_count == item_count
            and existing.cost_xp == expected_cost_xp
        )
        if not same_request or existing.status == "cancelled":
            await session.rollback()
            return ExchangeRequestResult(
                "unavailable",
                None,
                None,
                wallet_before,
                wallet_before,
                "この交換要求は利用できません。交換内容を選び直してください。",
            )
        item_id = cast("ResourceItemId", existing.item_id)
        existing_pack = MinecraftResourcePack(
            item_id=item_id,
            item_name=RESOURCE_ITEM_NAMES[item_id],
            item_count=existing.item_count,
            cost_xp=existing.cost_xp,
        )
        existing_id = existing.id
        wallet_before_existing = Wallet(
            total_xp=wallet_before.total_xp,
            spent_xp=max(0, wallet_before.spent_xp - existing.cost_xp),
        )
        await session.rollback()
        return ExchangeRequestResult(
            "reserved",
            existing_id,
            existing_pack,
            wallet_before_existing,
            wallet_before,
            (
                "この交換要求はすでに受け付け済みです。"
                f"残り {wallet_before.available_xp:,} XPです。"
            ),
        )

    pack = find_pack(item_id, item_count)
    if pack is None:
        await session.rollback()
        return ExchangeRequestResult(
            "unavailable",
            None,
            None,
            wallet_before,
            wallet_before,
            "この交換内容は利用できません。",
        )
    if pack.cost_xp != expected_cost_xp:
        await session.rollback()
        return ExchangeRequestResult(
            "unavailable",
            None,
            None,
            wallet_before,
            wallet_before,
            "交換レートが更新されました。交換内容を選び直してください。",
        )

    presence = (
        await session.execute(
            select(MinecraftVoicePresence).where(
                and_(
                    MinecraftVoicePresence.guild_id == guild_id,
                    MinecraftVoicePresence.user_id == user_id,
                )
            )
        )
    ).scalar_one_or_none()
    observed_now = now or datetime.now(UTC)
    if (
        presence is None
        or presence.last_seen_at < observed_now - ONLINE_PRESENCE_MAX_AGE
    ):
        await session.rollback()
        return ExchangeRequestResult(
            "offline",
            None,
            pack,
            wallet_before,
            wallet_before,
            "Minecraftサーバーに参加してから交換してください。",
        )
    if wallet_before.available_xp < pack.cost_xp:
        await session.rollback()
        shortage = pack.cost_xp - wallet_before.available_xp
        return ExchangeRequestResult(
            "insufficient_xp",
            None,
            pack,
            wallet_before,
            wallet_before,
            (
                f"XPが {shortage:,} 不足しています。"
                f"現在の交換可能XPは {wallet_before.available_xp:,} XP です。"
            ),
        )

    exchange = MinecraftResourceExchange(
        event_id=request_id,
        guild_id=guild_id,
        user_id=user_id,
        minecraft_account_id=presence.minecraft_account_id,
        item_id=pack.item_id,
        item_count=pack.item_count,
        cost_xp=pack.cost_xp,
        status="pending",
        requested_at=observed_now,
    )
    session.add(exchange)
    await session.commit()
    await session.refresh(exchange)
    wallet_after = Wallet(
        total_xp=wallet_before.total_xp,
        spent_xp=wallet_before.spent_xp + pack.cost_xp,
    )
    return ExchangeRequestResult(
        "reserved",
        exchange.id,
        pack,
        wallet_before,
        wallet_after,
        (
            f"サーバーXP {pack.cost_xp:,}を{pack.item_name} "
            f"{pack.item_count:,}個へ交換する要求を受け付けました。"
            "参加状態を再確認して付与します。"
            f"残り {wallet_after.available_xp:,} XPです。"
        ),
    )


async def list_pending_exchanges(
    session: AsyncSession, *, guild_id: str, limit: int
) -> tuple[PendingMinecraftResourceExchange, ...]:
    rows = (
        await session.execute(
            select(MinecraftResourceExchange)
            .where(
                MinecraftResourceExchange.guild_id == guild_id,
                MinecraftResourceExchange.status.in_(("pending", "delivering")),
            )
            .order_by(
                MinecraftResourceExchange.requested_at,
                MinecraftResourceExchange.id,
            )
            .limit(limit)
        )
    ).scalars()
    pending: list[PendingMinecraftResourceExchange] = []
    for row in rows:
        item_id = cast("ResourceItemId", row.item_id)
        pending.append(
            PendingMinecraftResourceExchange(
                id=row.id,
                event_id=row.event_id,
                guild_id=row.guild_id,
                user_id=row.user_id,
                minecraft_account_id=row.minecraft_account_id,
                item_id=item_id,
                item_name=RESOURCE_ITEM_NAMES[item_id],
                item_count=row.item_count,
                cost_xp=row.cost_xp,
                status=cast("Literal['pending', 'delivering']", row.status),
            )
        )
    return tuple(pending)


async def claim_exchange(
    session: AsyncSession, *, guild_id: str, exchange_id: int, claim_token: str
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftResourceExchange)
            .where(
                MinecraftResourceExchange.id == exchange_id,
                MinecraftResourceExchange.guild_id == guild_id,
                MinecraftResourceExchange.status == "pending",
            )
            .values(
                status="delivering",
                claim_token=claim_token,
                claimed_at=datetime.now(UTC),
            )
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftResourceExchange.id).where(
                MinecraftResourceExchange.id == exchange_id,
                MinecraftResourceExchange.guild_id == guild_id,
                MinecraftResourceExchange.status == "delivering",
                MinecraftResourceExchange.claim_token == claim_token,
            )
        )
    ).scalar_one_or_none() is not None


async def complete_exchange(
    session: AsyncSession, *, guild_id: str, exchange_id: int, claim_token: str
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftResourceExchange)
            .where(
                MinecraftResourceExchange.id == exchange_id,
                MinecraftResourceExchange.guild_id == guild_id,
                MinecraftResourceExchange.status == "delivering",
                MinecraftResourceExchange.claim_token == claim_token,
            )
            .values(status="completed", completed_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftResourceExchange.id).where(
                MinecraftResourceExchange.id == exchange_id,
                MinecraftResourceExchange.guild_id == guild_id,
                MinecraftResourceExchange.status == "completed",
                MinecraftResourceExchange.claim_token == claim_token,
            )
        )
    ).scalar_one_or_none() is not None


async def cancel_exchange(
    session: AsyncSession,
    *,
    guild_id: str,
    exchange_id: int,
    claim_token: str | None = None,
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftResourceExchange)
            .where(
                MinecraftResourceExchange.id == exchange_id,
                MinecraftResourceExchange.guild_id == guild_id,
                or_(
                    MinecraftResourceExchange.status == "pending",
                    and_(
                        MinecraftResourceExchange.status == "delivering",
                        MinecraftResourceExchange.claim_token == claim_token,
                    ),
                ),
            )
            .values(status="cancelled", completed_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftResourceExchange.id).where(
                MinecraftResourceExchange.id == exchange_id,
                MinecraftResourceExchange.guild_id == guild_id,
                MinecraftResourceExchange.status == "cancelled",
                or_(
                    MinecraftResourceExchange.claim_token == claim_token,
                    MinecraftResourceExchange.claim_token.is_(None),
                ),
            )
        )
    ).scalar_one_or_none() is not None
