"""Minecraft資源売却のレート・日次上限・冪等なXP確定を扱う。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal, cast

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftMaterialBuyback
from src.features.color_role_shop.service import lock_wallet
from src.utils import get_timezone

MATERIAL_BUYBACK_DAILY_LIMIT_XP = 3_000
MATERIAL_BUYBACK_STACK_SIZE = 64
MATERIAL_BUYBACK_MAX_ITEM_COUNT = 36 * MATERIAL_BUYBACK_STACK_SIZE


@dataclass(frozen=True)
class MaterialBuybackRate:
    item_id: str
    item_name: str
    reward_xp_per_stack: int


MATERIAL_BUYBACK_RATES = (
    MaterialBuybackRate("minecraft:emerald", "エメラルド", 500),
    MaterialBuybackRate("minecraft:dirt", "土", 30),
    MaterialBuybackRate("minecraft:sand", "砂", 40),
    MaterialBuybackRate("minecraft:sandstone", "砂岩", 50),
    MaterialBuybackRate("minecraft:deepslate", "深層岩", 35),
    MaterialBuybackRate("minecraft:cobbled_deepslate", "深層岩の丸石", 35),
    MaterialBuybackRate("minecraft:tuff", "凝灰岩", 40),
)

type BuybackRequestStatus = Literal[
    "reserved", "completed", "daily_limit", "unavailable", "conflict"
]


@dataclass(frozen=True)
class MaterialBuybackRequestResult:
    status: BuybackRequestStatus
    request_id: str | None
    item_id: str | None
    item_name: str | None
    item_count: int
    reward_xp: int
    reward_day: date
    daily_reserved_xp: int
    daily_limit_xp: int
    message: str
    duplicate: bool = False


def find_rate(item_id: str) -> MaterialBuybackRate | None:
    return next(
        (rate for rate in MATERIAL_BUYBACK_RATES if rate.item_id == item_id),
        None,
    )


def reward_for(item_id: str, item_count: int) -> int | None:
    rate = find_rate(item_id)
    if (
        rate is None
        or item_count < MATERIAL_BUYBACK_STACK_SIZE
        or item_count > MATERIAL_BUYBACK_MAX_ITEM_COUNT
        or item_count % MATERIAL_BUYBACK_STACK_SIZE != 0
    ):
        return None
    return item_count // MATERIAL_BUYBACK_STACK_SIZE * rate.reward_xp_per_stack


async def _daily_reserved_xp(
    session: AsyncSession, *, guild_id: str, user_id: str, reward_day: date
) -> int:
    return int(
        (
            await session.execute(
                select(
                    func.coalesce(func.sum(MinecraftMaterialBuyback.reward_xp), 0)
                ).where(
                    MinecraftMaterialBuyback.guild_id == guild_id,
                    MinecraftMaterialBuyback.user_id == user_id,
                    MinecraftMaterialBuyback.reward_day == reward_day,
                    MinecraftMaterialBuyback.status.in_(("pending", "completed")),
                )
            )
        ).scalar_one()
    )


async def request_buyback(
    session: AsyncSession,
    *,
    request_id: str,
    guild_id: str,
    user_id: str,
    minecraft_account_id: str,
    item_id: str,
    item_count: int,
    expected_reward_xp: int,
    now: datetime | None = None,
) -> MaterialBuybackRequestResult:
    """現行レートとJST日次枠を確認し、資源回収前のXPを予約する。"""
    observed_now = now or datetime.now(UTC)
    reward_day = observed_now.astimezone(get_timezone()).date()
    rate = find_rate(item_id)
    current_reward = reward_for(item_id, item_count)

    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    existing = (
        await session.execute(
            select(MinecraftMaterialBuyback).where(
                MinecraftMaterialBuyback.event_id == request_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        same = (
            existing.guild_id == guild_id
            and existing.user_id == user_id
            and existing.minecraft_account_id == minecraft_account_id
            and existing.item_id == item_id
            and existing.item_count == item_count
            and existing.reward_xp == expected_reward_xp
        )
        daily_reserved = await _daily_reserved_xp(
            session,
            guild_id=existing.guild_id,
            user_id=existing.user_id,
            reward_day=existing.reward_day,
        )
        if not same or existing.status == "cancelled":
            result = MaterialBuybackRequestResult(
                "conflict",
                None,
                None,
                None,
                0,
                0,
                existing.reward_day,
                daily_reserved,
                MATERIAL_BUYBACK_DAILY_LIMIT_XP,
                "同じ操作IDが別の資源売却に使用されています。",
            )
            await session.rollback()
            return result
        status: BuybackRequestStatus = (
            "completed" if existing.status == "completed" else "reserved"
        )
        result = MaterialBuybackRequestResult(
            status,
            existing.event_id,
            existing.item_id,
            existing.item_name,
            existing.item_count,
            existing.reward_xp,
            existing.reward_day,
            daily_reserved,
            MATERIAL_BUYBACK_DAILY_LIMIT_XP,
            (
                "この資源売却は完了済みです。"
                if status == "completed"
                else "この資源売却は受付済みです。回収処理を再開します。"
            ),
            duplicate=True,
        )
        await session.rollback()
        return result

    daily_reserved = await _daily_reserved_xp(
        session, guild_id=guild_id, user_id=user_id, reward_day=reward_day
    )
    if rate is None or current_reward is None or current_reward != expected_reward_xp:
        await session.rollback()
        return MaterialBuybackRequestResult(
            "unavailable",
            None,
            None,
            None,
            0,
            0,
            reward_day,
            daily_reserved,
            MATERIAL_BUYBACK_DAILY_LIMIT_XP,
            "売却レートが更新されました。交換内容を選び直してください。",
        )
    if daily_reserved + current_reward > MATERIAL_BUYBACK_DAILY_LIMIT_XP:
        remaining = max(0, MATERIAL_BUYBACK_DAILY_LIMIT_XP - daily_reserved)
        await session.rollback()
        return MaterialBuybackRequestResult(
            "daily_limit",
            None,
            rate.item_id,
            rate.item_name,
            item_count,
            current_reward,
            reward_day,
            daily_reserved,
            MATERIAL_BUYBACK_DAILY_LIMIT_XP,
            (
                "本日の資源売却上限を超えます。"
                f"本日の残り売却枠は {remaining:,} サーバーXPです。"
            ),
        )

    buyback = MinecraftMaterialBuyback(
        event_id=request_id,
        guild_id=guild_id,
        user_id=user_id,
        minecraft_account_id=minecraft_account_id,
        item_id=rate.item_id,
        item_name=rate.item_name,
        item_count=item_count,
        reward_xp=current_reward,
        reward_day=reward_day,
        status="pending",
        requested_at=observed_now,
    )
    session.add(buyback)
    await session.commit()
    return MaterialBuybackRequestResult(
        "reserved",
        request_id,
        rate.item_id,
        rate.item_name,
        item_count,
        current_reward,
        reward_day,
        daily_reserved + current_reward,
        MATERIAL_BUYBACK_DAILY_LIMIT_XP,
        (
            f"{rate.item_name} x{item_count:,} の売却を受け付けました。"
            f"回収後に {current_reward:,} サーバーXPを付与します。"
        ),
    )


async def update_buyback(
    session: AsyncSession,
    *,
    request_id: str,
    guild_id: str,
    user_id: str,
    action: Literal["complete", "cancel"],
) -> bool:
    target = "completed" if action == "complete" else "cancelled"
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(MinecraftMaterialBuyback)
            .where(
                MinecraftMaterialBuyback.event_id == request_id,
                MinecraftMaterialBuyback.guild_id == guild_id,
                MinecraftMaterialBuyback.user_id == user_id,
                MinecraftMaterialBuyback.status == "pending",
            )
            .values(status=target, completed_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    if result.rowcount:
        return True
    return (
        await session.execute(
            select(MinecraftMaterialBuyback.id).where(
                and_(
                    MinecraftMaterialBuyback.event_id == request_id,
                    MinecraftMaterialBuyback.guild_id == guild_id,
                    MinecraftMaterialBuyback.user_id == user_id,
                    MinecraftMaterialBuyback.status == target,
                )
            )
        )
    ).scalar_one_or_none() is not None
