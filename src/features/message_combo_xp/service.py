"""Record idempotent XP awards for itsuka-bot daily message streaks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, MessageComboXpEvent
from src.utils import get_timezone

MESSAGE_COMBO_XP_REWARDS: dict[int, int] = {
    2: 20,
    3: 50,
    5: 100,
    10: 250,
    20: 500,
}


@dataclass(frozen=True)
class MessageComboXpGrantResult:
    event_id: str
    streak_days: int
    awarded_xp: int
    duplicate: bool


async def record_message_combo_xp(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    channel_id: str,
    config_id: str,
    streak_days: int,
    observed_at: datetime,
) -> MessageComboXpGrantResult:
    """Award the server-defined milestone amount exactly once per event ID."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    awarded_xp = MESSAGE_COMBO_XP_REWARDS.get(streak_days)
    if awarded_xp is None:
        raise ValueError("streak_days is not a rewarded milestone")

    await session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(event_id, 0)))
    )
    existing = (
        await session.execute(
            select(MessageComboXpEvent).where(MessageComboXpEvent.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.guild_id != guild_id
            or existing.user_id != user_id
            or existing.channel_id != channel_id
            or existing.config_id != config_id
            or existing.streak_days != streak_days
            or existing.observed_at != observed_at
        ):
            raise ValueError("event_id is already bound to a different event")
        await session.commit()
        return MessageComboXpGrantResult(
            event_id=existing.event_id,
            streak_days=existing.streak_days,
            awarded_xp=existing.awarded_xp,
            duplicate=True,
        )

    stat_date = observed_at.astimezone(get_timezone()).date()
    stmt = pg_insert(DailyStat).values(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        stat_date=stat_date,
        message_count=0,
        message_combo_xp=awarded_xp,
        char_count=0,
        attachment_count=0,
        reactions_received=0,
        reactions_given=0,
        voice_seconds=0,
        minecraft_voice_bonus_seconds=0,
        voice_party_seconds=0,
        tea_festival_seconds=0,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_daily_stat",
            set_={
                "message_combo_xp": DailyStat.message_combo_xp + awarded_xp,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    session.add(
        MessageComboXpEvent(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            channel_id=channel_id,
            config_id=config_id,
            streak_days=streak_days,
            awarded_xp=awarded_xp,
            observed_at=observed_at,
        )
    )
    await session.commit()
    return MessageComboXpGrantResult(
        event_id=event_id,
        streak_days=streak_days,
        awarded_xp=awarded_xp,
        duplicate=False,
    )
