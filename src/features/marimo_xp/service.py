"""Record idempotent XP awards for marimo-bot watering events."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MarimoXpEvent, MarimoXpSpend
from src.features.color_role_shop.service import lock_wallet
from src.features.leveling.service import get_user_lifetime_levels

MARIMO_REVIVAL_COST_XP = 3000


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

    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
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
            or existing.cost_xp != MARIMO_REVIVAL_COST_XP
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
