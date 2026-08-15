"""Minecraftアイテムガチャの冪等なXP予約・確定を扱う。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftItemGachaSpend, MinecraftVoicePresence
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user
from src.features.minecraft_xp_shop.service import ONLINE_PRESENCE_MAX_AGE

ITEM_GACHA_NORMAL_COST_XP = 100
ITEM_GACHA_PREMIUM_COST_XP = 1_000
ITEM_GACHA_DAILY_LIMIT = 3
ITEM_GACHA_COSTS = frozenset({ITEM_GACHA_NORMAL_COST_XP, ITEM_GACHA_PREMIUM_COST_XP})
# 旧mc-botとの段階デプロイ中も通常ガチャを利用できるように残す。
ITEM_GACHA_COST_XP = ITEM_GACHA_NORMAL_COST_XP

type SpendRequestStatus = Literal[
    "reserved", "completed", "offline", "insufficient_xp", "unavailable"
]


@dataclass(frozen=True)
class SpendRequestResult:
    status: SpendRequestStatus
    cost_xp: int
    wallet_before: Wallet
    wallet_after: Wallet
    message: str


def _wallet_before_existing(wallet_after: Wallet, cost_xp: int) -> Wallet:
    return Wallet(
        total_xp=wallet_after.total_xp,
        spent_xp=max(0, wallet_after.spent_xp - cost_xp),
    )


async def request_spend(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    request_id: str,
    minecraft_account_id: str,
    draw_day: date,
    expected_cost_xp: int,
    total_xp: int,
    now: datetime | None = None,
) -> SpendRequestResult:
    """残高とオンライン状態を確認し、1日3回までのガチャ費用を予約する。"""
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    wallet_before = await wallet_for_user(
        session, guild_id=guild_id, user_id=user_id, total_xp=total_xp
    )
    if expected_cost_xp not in ITEM_GACHA_COSTS:
        await session.rollback()
        return SpendRequestResult(
            "unavailable",
            ITEM_GACHA_NORMAL_COST_XP,
            wallet_before,
            wallet_before,
            "ガチャ価格が更新されました。パネルから開き直してください。",
        )

    existing = (
        await session.execute(
            select(MinecraftItemGachaSpend).where(
                MinecraftItemGachaSpend.event_id == request_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        same_request = (
            existing.guild_id == guild_id
            and existing.user_id == user_id
            and existing.minecraft_account_id == minecraft_account_id
            and existing.draw_day == draw_day
            and existing.cost_xp == expected_cost_xp
        )
        if not same_request:
            await session.rollback()
            return SpendRequestResult(
                "unavailable",
                expected_cost_xp,
                wallet_before,
                wallet_before,
                "この抽選要求は利用できません。",
            )
        if existing.status in {"pending", "completed"}:
            status: SpendRequestStatus = (
                "completed" if existing.status == "completed" else "reserved"
            )
            existing_cost_xp = existing.cost_xp
            before_existing = _wallet_before_existing(wallet_before, existing_cost_xp)
            await session.rollback()
            return SpendRequestResult(
                status,
                existing_cost_xp,
                before_existing,
                wallet_before,
                "この抽選のXP決済はすでに受け付け済みです。",
            )

    daily_count = int(
        (
            await session.execute(
                select(func.count(MinecraftItemGachaSpend.id)).where(
                    MinecraftItemGachaSpend.guild_id == guild_id,
                    MinecraftItemGachaSpend.user_id == user_id,
                    MinecraftItemGachaSpend.draw_day == draw_day,
                    MinecraftItemGachaSpend.status.in_(("pending", "completed")),
                )
            )
        ).scalar_one()
    )
    if daily_count >= ITEM_GACHA_DAILY_LIMIT:
        await session.rollback()
        return SpendRequestResult(
            "unavailable",
            expected_cost_xp,
            wallet_before,
            wallet_before,
            f"本日のアイテムガチャは{ITEM_GACHA_DAILY_LIMIT}回すべて処理済みです。",
        )

    observed_now = now or datetime.now(UTC)
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
    if (
        presence is None
        or presence.minecraft_account_id != minecraft_account_id
        or presence.last_seen_at < observed_now - ONLINE_PRESENCE_MAX_AGE
    ):
        await session.rollback()
        return SpendRequestResult(
            "offline",
            expected_cost_xp,
            wallet_before,
            wallet_before,
            "連携したMinecraftアカウントで参加してから引いてください。",
        )
    if wallet_before.available_xp < expected_cost_xp:
        shortage = expected_cost_xp - wallet_before.available_xp
        await session.rollback()
        return SpendRequestResult(
            "insufficient_xp",
            expected_cost_xp,
            wallet_before,
            wallet_before,
            f"XPが {shortage:,} XP不足しています。",
        )

    if existing is None:
        session.add(
            MinecraftItemGachaSpend(
                event_id=request_id,
                guild_id=guild_id,
                user_id=user_id,
                minecraft_account_id=minecraft_account_id,
                draw_day=draw_day,
                cost_xp=expected_cost_xp,
                status="pending",
                requested_at=observed_now,
            )
        )
    else:
        existing.status = "pending"
        existing.requested_at = observed_now
        existing.completed_at = None
    await session.commit()
    wallet_after = Wallet(
        total_xp=wallet_before.total_xp,
        spent_xp=wallet_before.spent_xp + expected_cost_xp,
    )
    return SpendRequestResult(
        "reserved",
        expected_cost_xp,
        wallet_before,
        wallet_after,
        (
            f"サーバーXP {expected_cost_xp:,}を予約しました。"
            f"残り {wallet_after.available_xp:,} XPです。"
        ),
    )


async def complete_spend(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    request_id: str,
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftItemGachaSpend)
            .where(
                MinecraftItemGachaSpend.event_id == request_id,
                MinecraftItemGachaSpend.guild_id == guild_id,
                MinecraftItemGachaSpend.user_id == user_id,
                MinecraftItemGachaSpend.status == "pending",
            )
            .values(status="completed", completed_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftItemGachaSpend.id).where(
                MinecraftItemGachaSpend.event_id == request_id,
                MinecraftItemGachaSpend.guild_id == guild_id,
                MinecraftItemGachaSpend.user_id == user_id,
                MinecraftItemGachaSpend.status == "completed",
            )
        )
    ).scalar_one_or_none() is not None


async def cancel_spend(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    request_id: str,
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftItemGachaSpend)
            .where(
                MinecraftItemGachaSpend.event_id == request_id,
                MinecraftItemGachaSpend.guild_id == guild_id,
                MinecraftItemGachaSpend.user_id == user_id,
                MinecraftItemGachaSpend.status == "pending",
            )
            .values(status="cancelled", completed_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftItemGachaSpend.id).where(
                MinecraftItemGachaSpend.event_id == request_id,
                MinecraftItemGachaSpend.guild_id == guild_id,
                MinecraftItemGachaSpend.user_id == user_id,
                MinecraftItemGachaSpend.status == "cancelled",
            )
        )
    ).scalar_one_or_none() is not None
