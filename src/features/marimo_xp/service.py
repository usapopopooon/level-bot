"""Record idempotent XP awards for marimo-bot watering events."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MarimoXpEvent


@dataclass(frozen=True)
class MarimoXpGrantResult:
    event_id: str
    awarded_xp: int
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
