"""Minecraft XP交換の予約・配信状態・消費台帳を扱う。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftVoicePresence, MinecraftXpExchange
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user

ONLINE_PRESENCE_MAX_AGE = timedelta(seconds=75)


@dataclass(frozen=True)
class MinecraftXpPack:
    cost_xp: int
    reward_xp: int


MINECRAFT_XP_PACKS = (
    MinecraftXpPack(cost_xp=10, reward_xp=50),
    MinecraftXpPack(cost_xp=50, reward_xp=250),
    MinecraftXpPack(cost_xp=100, reward_xp=500),
)

type ExchangeRequestStatus = Literal[
    "reserved", "offline", "insufficient_xp", "unavailable"
]


@dataclass(frozen=True)
class ExchangeRequestResult:
    status: ExchangeRequestStatus
    exchange_id: int | None
    pack: MinecraftXpPack | None
    wallet_before: Wallet
    wallet_after: Wallet
    message: str


@dataclass(frozen=True)
class PendingMinecraftXpExchange:
    id: int
    event_id: str
    guild_id: str
    user_id: str
    minecraft_account_id: str
    cost_xp: int
    reward_xp: int
    status: Literal["pending", "delivering"]


def find_pack(cost_xp: int) -> MinecraftXpPack | None:
    return next((pack for pack in MINECRAFT_XP_PACKS if pack.cost_xp == cost_xp), None)


async def request_exchange(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    request_id: str,
    cost_xp: int,
    expected_reward_xp: int,
    total_xp: int,
    now: datetime | None = None,
) -> ExchangeRequestResult:
    """オンライン状態と残高を確認し、付与待ちの交換を予約する。"""
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    wallet_before = await wallet_for_user(
        session, guild_id=guild_id, user_id=user_id, total_xp=total_xp
    )
    existing = (
        await session.execute(
            select(MinecraftXpExchange).where(
                MinecraftXpExchange.event_id == request_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        same_request = (
            existing.guild_id == guild_id
            and existing.user_id == user_id
            and existing.cost_xp == cost_xp
            and existing.reward_xp == expected_reward_xp
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
        existing_pack = MinecraftXpPack(
            cost_xp=existing.cost_xp,
            reward_xp=existing.reward_xp,
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

    pack = find_pack(cost_xp)
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
    if pack.reward_xp != expected_reward_xp:
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
    online_since = observed_now - ONLINE_PRESENCE_MAX_AGE
    if presence is None or presence.last_seen_at < online_since:
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

    exchange = MinecraftXpExchange(
        event_id=request_id,
        guild_id=guild_id,
        user_id=user_id,
        minecraft_account_id=presence.minecraft_account_id,
        cost_xp=pack.cost_xp,
        reward_xp=pack.reward_xp,
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
            f"サーバーXP {pack.cost_xp:,}をMinecraft内の "
            f"{pack.reward_xp:,} XPへ交換する要求を受け付けました。"
            "参加状態を再確認して付与します。"
            f"残り {wallet_after.available_xp:,} XPです。"
        ),
    )


async def list_pending_exchanges(
    session: AsyncSession, *, guild_id: str, limit: int
) -> tuple[PendingMinecraftXpExchange, ...]:
    rows = (
        await session.execute(
            select(MinecraftXpExchange)
            .where(
                MinecraftXpExchange.guild_id == guild_id,
                MinecraftXpExchange.status.in_(("pending", "delivering")),
            )
            .order_by(MinecraftXpExchange.requested_at, MinecraftXpExchange.id)
            .limit(limit)
        )
    ).scalars()
    return tuple(
        PendingMinecraftXpExchange(
            id=row.id,
            event_id=row.event_id,
            guild_id=row.guild_id,
            user_id=row.user_id,
            minecraft_account_id=row.minecraft_account_id,
            cost_xp=row.cost_xp,
            reward_xp=row.reward_xp,
            status=cast("Literal['pending', 'delivering']", row.status),
        )
        for row in rows
    )


async def claim_exchange(
    session: AsyncSession,
    *,
    guild_id: str,
    exchange_id: int,
    claim_token: str,
) -> bool:
    """claim tokenの所有者だけが同じclaimを安全に再試行できる。"""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftXpExchange)
            .where(
                MinecraftXpExchange.id == exchange_id,
                MinecraftXpExchange.guild_id == guild_id,
                MinecraftXpExchange.status == "pending",
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
            select(MinecraftXpExchange.id).where(
                MinecraftXpExchange.id == exchange_id,
                MinecraftXpExchange.guild_id == guild_id,
                MinecraftXpExchange.status == "delivering",
                MinecraftXpExchange.claim_token == claim_token,
            )
        )
    ).scalar_one_or_none() is not None


async def complete_exchange(
    session: AsyncSession,
    *,
    guild_id: str,
    exchange_id: int,
    claim_token: str,
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftXpExchange)
            .where(
                MinecraftXpExchange.id == exchange_id,
                MinecraftXpExchange.guild_id == guild_id,
                MinecraftXpExchange.status == "delivering",
                MinecraftXpExchange.claim_token == claim_token,
            )
            .values(status="completed", completed_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftXpExchange.id).where(
                MinecraftXpExchange.id == exchange_id,
                MinecraftXpExchange.guild_id == guild_id,
                MinecraftXpExchange.status == "completed",
                MinecraftXpExchange.claim_token == claim_token,
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
            update(MinecraftXpExchange)
            .where(
                MinecraftXpExchange.id == exchange_id,
                MinecraftXpExchange.guild_id == guild_id,
                or_(
                    MinecraftXpExchange.status == "pending",
                    and_(
                        MinecraftXpExchange.status == "delivering",
                        MinecraftXpExchange.claim_token == claim_token,
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
            select(MinecraftXpExchange.id).where(
                MinecraftXpExchange.id == exchange_id,
                MinecraftXpExchange.guild_id == guild_id,
                MinecraftXpExchange.status == "cancelled",
                or_(
                    MinecraftXpExchange.claim_token == claim_token,
                    MinecraftXpExchange.claim_token.is_(None),
                ),
            )
        )
    ).scalar_one_or_none() is not None
