"""Persist idempotent Minecraft fishing combo reward audit events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftFishingComboEvent


@dataclass(frozen=True)
class FishingComboRecordResult:
    event_id: str
    catch_count: int
    combo_count: int
    reward_xp: int
    duplicate: bool


async def record_fishing_combo_event(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    minecraft_account_id: str,
    catch_count: int,
    combo_count: int,
    reward_xp: int,
    observed_at: datetime,
) -> FishingComboRecordResult:
    """Record a Minecraft-only reward exactly once without awarding server XP."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")

    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(event_id, 0)))
    )
    existing = (
        await session.execute(
            select(MinecraftFishingComboEvent).where(
                MinecraftFishingComboEvent.event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.guild_id != guild_id
            or existing.user_id != user_id
            or existing.minecraft_account_id != minecraft_account_id
            or existing.catch_count != catch_count
            or existing.combo_count != combo_count
            or existing.reward_xp != reward_xp
            or existing.observed_at != observed_at
        ):
            raise ValueError("event_id is already bound to a different event")
        await session.commit()
        return FishingComboRecordResult(
            event_id=existing.event_id,
            catch_count=existing.catch_count,
            combo_count=existing.combo_count,
            reward_xp=existing.reward_xp,
            duplicate=True,
        )

    session.add(
        MinecraftFishingComboEvent(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            minecraft_account_id=minecraft_account_id,
            catch_count=catch_count,
            combo_count=combo_count,
            reward_xp=reward_xp,
            observed_at=observed_at,
        )
    )
    await session.commit()
    return FishingComboRecordResult(
        event_id=event_id,
        catch_count=catch_count,
        combo_count=combo_count,
        reward_xp=reward_xp,
        duplicate=False,
    )
