"""Record idempotent XP awards for marimo-bot watering events."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MarimoItemSpend, MarimoXpEvent, MarimoXpSpend
from src.features.cafe_gacha.service import list_collection
from src.features.color_role_shop.service import lock_wallet
from src.features.leveling.service import get_user_lifetime_levels

MARIMO_REVIVAL_COST_XP = 1000


@dataclass(frozen=True)
class MarimoXpGrantResult:
    event_id: str
    awarded_xp: int
    duplicate: bool


@dataclass(frozen=True)
class MarimoRevivalSpendResult:
    event_id: str
    status: Literal["charged", "insufficient_xp"]
    cost_xp: int
    remaining_xp: int
    duplicate: bool


@dataclass(frozen=True)
class MarimoRevivalItemSpendResult:
    event_id: str
    status: Literal["consumed", "insufficient_item"]
    card_key: Literal["moss-cola"]
    remaining_count: int
    duplicate: bool


async def _lock_spend_event(session: AsyncSession, event_id: str) -> None:
    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(event_id, 0)))
    )


async def record_marimo_xp(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    channel_id: str,
    awarded_xp: int,
    observed_at: datetime,
) -> MarimoXpGrantResult:
    """Record a trusted marimo watering award exactly once per event ID."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    if not 1 <= awarded_xp <= 1000:
        raise ValueError("awarded_xp must be between 1 and 1000")

    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(event_id, 0)))
    )
    existing = (
        await session.execute(
            select(MarimoXpEvent).where(MarimoXpEvent.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.guild_id != guild_id
            or existing.user_id != user_id
            or existing.channel_id != channel_id
            or existing.awarded_xp != awarded_xp
            or existing.observed_at != observed_at
        ):
            raise ValueError("event_id is already bound to a different event")
        await session.commit()
        return MarimoXpGrantResult(
            event_id=existing.event_id,
            awarded_xp=existing.awarded_xp,
            duplicate=True,
        )

    session.add(
        MarimoXpEvent(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            channel_id=channel_id,
            awarded_xp=awarded_xp,
            observed_at=observed_at,
        )
    )
    await session.commit()
    return MarimoXpGrantResult(
        event_id=event_id,
        awarded_xp=awarded_xp,
        duplicate=False,
    )


async def spend_marimo_revival_xp(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    channel_id: str,
    observed_at: datetime,
) -> MarimoRevivalSpendResult:
    """復活費用を現在XPから、同じイベントにつき一度だけ確定する。"""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")

    await _lock_spend_event(session, event_id)
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    item_spend = (
        await session.execute(
            select(MarimoItemSpend).where(MarimoItemSpend.event_id == event_id)
        )
    ).scalar_one_or_none()
    if item_spend is not None:
        raise ValueError("event_id is already bound to an item spend")
    existing = (
        await session.execute(
            select(MarimoXpSpend).where(MarimoXpSpend.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.guild_id != guild_id
            or existing.user_id != user_id
            or existing.channel_id != channel_id
            or existing.observed_at != observed_at
        ):
            raise ValueError("event_id is already bound to a different event")
        levels = await get_user_lifetime_levels(session, guild_id, user_id)
        await session.commit()
        return MarimoRevivalSpendResult(
            event_id=event_id,
            status=("charged" if existing.status == "charged" else "insufficient_xp"),
            cost_xp=existing.cost_xp,
            remaining_xp=0 if levels is None else levels.total.xp,
            duplicate=True,
        )

    levels = await get_user_lifetime_levels(session, guild_id, user_id)
    available_xp = 0 if levels is None else levels.total.xp
    if available_xp < MARIMO_REVIVAL_COST_XP:
        session.add(
            MarimoXpSpend(
                event_id=event_id,
                guild_id=guild_id,
                user_id=user_id,
                channel_id=channel_id,
                cost_xp=MARIMO_REVIVAL_COST_XP,
                status="declined",
                observed_at=observed_at,
            )
        )
        await session.commit()
        return MarimoRevivalSpendResult(
            event_id=event_id,
            status="insufficient_xp",
            cost_xp=MARIMO_REVIVAL_COST_XP,
            remaining_xp=available_xp,
            duplicate=False,
        )

    session.add(
        MarimoXpSpend(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            channel_id=channel_id,
            cost_xp=MARIMO_REVIVAL_COST_XP,
            status="charged",
            observed_at=observed_at,
        )
    )
    await session.commit()
    return MarimoRevivalSpendResult(
        event_id=event_id,
        status="charged",
        cost_xp=MARIMO_REVIVAL_COST_XP,
        remaining_xp=available_xp - MARIMO_REVIVAL_COST_XP,
        duplicate=False,
    )


async def spend_marimo_revival_item(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    channel_id: str,
    card_key: Literal["moss-cola"],
    observed_at: datetime,
) -> MarimoRevivalItemSpendResult:
    """重複の苔コーラ1枚を、同じ復活イベントにつき一度だけ消費する。"""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    if card_key != "moss-cola":
        raise ValueError("card_key must be moss-cola")

    await _lock_spend_event(session, event_id)
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    xp_spend = (
        await session.execute(
            select(MarimoXpSpend).where(MarimoXpSpend.event_id == event_id)
        )
    ).scalar_one_or_none()
    if xp_spend is not None:
        raise ValueError("event_id is already bound to an XP spend")

    existing = (
        await session.execute(
            select(MarimoItemSpend).where(MarimoItemSpend.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.guild_id != guild_id
            or existing.user_id != user_id
            or existing.channel_id != channel_id
            or existing.card_key != card_key
            or existing.observed_at != observed_at
        ):
            raise ValueError("event_id is already bound to a different event")
        await session.commit()
        return MarimoRevivalItemSpendResult(
            event_id=existing.event_id,
            status=(
                "consumed" if existing.status == "consumed" else "insufficient_item"
            ),
            card_key="moss-cola",
            remaining_count=existing.remaining_count,
            duplicate=True,
        )

    collection = {
        item.card.key: item
        for item in await list_collection(session, guild_id=guild_id, user_id=user_id)
    }
    moss_cola = collection[card_key]
    status: Literal["consumed", "insufficient_item"] = (
        "consumed" if moss_cola.redeemable_count >= 1 else "insufficient_item"
    )
    remaining_count = moss_cola.count - (1 if status == "consumed" else 0)
    session.add(
        MarimoItemSpend(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            channel_id=channel_id,
            card_key=card_key,
            quantity=1,
            status=status,
            remaining_count=remaining_count,
            observed_at=observed_at,
        )
    )
    await session.commit()
    return MarimoRevivalItemSpendResult(
        event_id=event_id,
        status=status,
        card_key="moss-cola",
        remaining_count=remaining_count,
        duplicate=False,
    )
