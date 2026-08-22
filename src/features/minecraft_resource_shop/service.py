"""Minecraft資源交換の予約・配信状態・消費台帳を扱う。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    MinecraftResourceExchange,
    MinecraftResourceShopCatalog,
    MinecraftResourceShopPack,
    MinecraftVoicePresence,
)
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user
from src.features.minecraft_xp_shop.service import ONLINE_PRESENCE_MAX_AGE

RESOURCE_ITEM_ID_PATTERN = re.compile(r"^minecraft:[a-z0-9_]+$")
MAX_RESOURCE_PACKS = 25
MAX_RESOURCE_COST_XP = 10_000_000


@dataclass(frozen=True)
class MinecraftResourcePack:
    item_id: str
    item_name: str
    item_count: int
    cost_xp: int


DEFAULT_MINECRAFT_RESOURCE_PACKS = (
    MinecraftResourcePack("minecraft:emerald", "エメラルド", 4, 75),
    MinecraftResourcePack("minecraft:emerald", "エメラルド", 16, 250),
    MinecraftResourcePack("minecraft:emerald", "エメラルド", 32, 500),
    MinecraftResourcePack("minecraft:emerald", "エメラルド", 64, 1_000),
    MinecraftResourcePack("minecraft:gunpowder", "火薬", 64, 150),
    MinecraftResourcePack("minecraft:diamond", "ダイヤモンド", 1, 250),
    MinecraftResourcePack("minecraft:diamond", "ダイヤモンド", 3, 750),
    MinecraftResourcePack("minecraft:diamond", "ダイヤモンド", 8, 2_000),
    MinecraftResourcePack("minecraft:diamond", "ダイヤモンド", 16, 4_000),
)
# 既存の表示・テスト向け名称。永続カタログ未作成時だけ使用する既定値であり、
# 購入時の正は必ずDBから取得する。
MINECRAFT_RESOURCE_PACKS = DEFAULT_MINECRAFT_RESOURCE_PACKS


@dataclass(frozen=True)
class MinecraftResourceCatalog:
    guild_id: str
    revision: int
    packs: tuple[MinecraftResourcePack, ...]


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
    item_id: str
    item_name: str
    item_count: int
    cost_xp: int
    status: Literal["pending", "delivering"]


async def get_resource_catalog(
    session: AsyncSession, *, guild_id: str
) -> MinecraftResourceCatalog:
    header = await session.get(MinecraftResourceShopCatalog, guild_id)
    if header is None:
        return MinecraftResourceCatalog(guild_id, 0, DEFAULT_MINECRAFT_RESOURCE_PACKS)
    rows = (
        await session.execute(
            select(MinecraftResourceShopPack)
            .where(MinecraftResourceShopPack.guild_id == guild_id)
            .order_by(
                MinecraftResourceShopPack.sort_order,
                MinecraftResourceShopPack.id,
            )
        )
    ).scalars()
    packs = tuple(
        MinecraftResourcePack(
            item_id=row.item_id,
            item_name=row.item_name,
            item_count=row.item_count,
            cost_xp=row.cost_xp,
        )
        for row in rows
    )
    if not packs:
        raise RuntimeError("resource shop catalog must contain at least one pack")
    return MinecraftResourceCatalog(guild_id, header.revision, packs)


async def find_pack(
    session: AsyncSession, *, guild_id: str, item_id: str, item_count: int
) -> MinecraftResourcePack | None:
    catalog = await get_resource_catalog(session, guild_id=guild_id)
    return next(
        (
            pack
            for pack in catalog.packs
            if pack.item_id == item_id and pack.item_count == item_count
        ),
        None,
    )


def validate_resource_pack(pack: MinecraftResourcePack) -> None:
    if len(pack.item_id) > 64 or not RESOURCE_ITEM_ID_PATTERN.fullmatch(pack.item_id):
        raise ValueError("item_id must be a namespaced vanilla Minecraft item")
    if not pack.item_name.strip() or len(pack.item_name) > 64:
        raise ValueError("item_name must contain between 1 and 64 characters")
    if any(ord(character) < 32 for character in pack.item_name):
        raise ValueError("item_name must not contain control characters")
    if not 1 <= pack.item_count <= 64:
        raise ValueError("item_count must be between 1 and 64")
    if not 1 <= pack.cost_xp <= MAX_RESOURCE_COST_XP:
        raise ValueError(f"cost_xp must be between 1 and {MAX_RESOURCE_COST_XP}")


async def _ensure_persisted_catalog(
    session: AsyncSession, *, guild_id: str, actor_user_id: str
) -> MinecraftResourceShopCatalog:
    now = datetime.now(UTC)
    await session.execute(
        pg_insert(MinecraftResourceShopCatalog)
        .values(
            guild_id=guild_id,
            revision=0,
            updated_by=actor_user_id,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["guild_id"])
    )
    header = (
        await session.execute(
            select(MinecraftResourceShopCatalog)
            .where(MinecraftResourceShopCatalog.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one()
    existing_count = await session.scalar(
        select(func.count(MinecraftResourceShopPack.id)).where(
            MinecraftResourceShopPack.guild_id == guild_id
        )
    )
    if existing_count == 0:
        session.add_all(
            [
                MinecraftResourceShopPack(
                    guild_id=guild_id,
                    item_id=pack.item_id,
                    item_name=pack.item_name,
                    item_count=pack.item_count,
                    cost_xp=pack.cost_xp,
                    sort_order=index,
                )
                for index, pack in enumerate(DEFAULT_MINECRAFT_RESOURCE_PACKS)
            ]
        )
        await session.flush()
    return header


async def upsert_resource_pack(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_user_id: str,
    pack: MinecraftResourcePack,
) -> MinecraftResourceCatalog:
    validate_resource_pack(pack)
    normalized_item_name = pack.item_name.strip()
    header = await _ensure_persisted_catalog(
        session, guild_id=guild_id, actor_user_id=actor_user_id
    )
    row = (
        await session.execute(
            select(MinecraftResourceShopPack).where(
                MinecraftResourceShopPack.guild_id == guild_id,
                MinecraftResourceShopPack.item_id == pack.item_id,
                MinecraftResourceShopPack.item_count == pack.item_count,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        pack_count = cast(
            "int",
            await session.scalar(
                select(func.count(MinecraftResourceShopPack.id)).where(
                    MinecraftResourceShopPack.guild_id == guild_id
                )
            ),
        )
        if pack_count >= MAX_RESOURCE_PACKS:
            await session.rollback()
            raise ValueError(
                f"resource catalog cannot exceed {MAX_RESOURCE_PACKS} packs"
            )
        next_order = cast(
            "int",
            await session.scalar(
                select(
                    func.coalesce(func.max(MinecraftResourceShopPack.sort_order), -1)
                    + 1
                ).where(MinecraftResourceShopPack.guild_id == guild_id)
            ),
        )
        session.add(
            MinecraftResourceShopPack(
                guild_id=guild_id,
                item_id=pack.item_id,
                item_name=normalized_item_name,
                item_count=pack.item_count,
                cost_xp=pack.cost_xp,
                sort_order=next_order,
            )
        )
    else:
        row.cost_xp = pack.cost_xp
    await session.execute(
        update(MinecraftResourceShopPack)
        .where(
            MinecraftResourceShopPack.guild_id == guild_id,
            MinecraftResourceShopPack.item_id == pack.item_id,
        )
        .values(item_name=normalized_item_name)
    )
    header.revision += 1
    header.updated_by = actor_user_id
    header.updated_at = datetime.now(UTC)
    await session.commit()
    return await get_resource_catalog(session, guild_id=guild_id)


async def remove_resource_pack(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_user_id: str,
    item_id: str,
    item_count: int,
) -> MinecraftResourceCatalog | None:
    header = await _ensure_persisted_catalog(
        session, guild_id=guild_id, actor_user_id=actor_user_id
    )
    row = (
        await session.execute(
            select(MinecraftResourceShopPack).where(
                MinecraftResourceShopPack.guild_id == guild_id,
                MinecraftResourceShopPack.item_id == item_id,
                MinecraftResourceShopPack.item_count == item_count,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        await session.rollback()
        return None
    pack_count = cast(
        "int",
        await session.scalar(
            select(func.count(MinecraftResourceShopPack.id)).where(
                MinecraftResourceShopPack.guild_id == guild_id
            )
        ),
    )
    if pack_count <= 1:
        await session.rollback()
        raise ValueError("resource catalog must contain at least one pack")
    await session.execute(
        delete(MinecraftResourceShopPack).where(MinecraftResourceShopPack.id == row.id)
    )
    header.revision += 1
    header.updated_by = actor_user_id
    header.updated_at = datetime.now(UTC)
    await session.commit()
    return await get_resource_catalog(session, guild_id=guild_id)


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
        existing_pack = MinecraftResourcePack(
            item_id=existing.item_id,
            item_name=existing.item_name,
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

    pack = await find_pack(
        session, guild_id=guild_id, item_id=item_id, item_count=item_count
    )
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
        item_name=pack.item_name,
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
        pending.append(
            PendingMinecraftResourceExchange(
                id=row.id,
                event_id=row.event_id,
                guild_id=row.guild_id,
                user_id=row.user_id,
                minecraft_account_id=row.minecraft_account_id,
                item_id=row.item_id,
                item_name=row.item_name,
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
