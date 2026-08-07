"""VCで1人の確認済み滞在時間に固定XPを付与する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import MAX_VOICE_SESSION_SECONDS
from src.database.models import DailyStat, VoiceZenRewardEvent, VoiceZenState
from src.utils import get_timezone

ZEN_REWARDS: dict[int, int] = {10: 10, 30: 30, 60: 75, 180: 200, 360: 500}

type VoiceZenTransition = Literal[
    "started", "continued", "milestone", "ended", "switched", "inactive"
]


@dataclass(frozen=True)
class VoiceZenAward:
    event_id: str
    user_id: str
    minutes: int
    xp: int


@dataclass(frozen=True)
class VoiceZenResult:
    guild_id: str
    channel_id: str
    transition: VoiceZenTransition
    active: bool
    user_id: str | None
    participant_count: int
    accumulated_seconds: int
    pending_awards: tuple[VoiceZenAward, ...]
    reward_user_id: str | None
    ended_user_id: str | None
    ended_was_announced: bool
    newly_awarded_xp: int = 0


def _normalize_participants(participant_ids: list[str]) -> list[str]:
    if any(not user_id.isdigit() for user_id in participant_ids):
        raise ValueError("participant_ids must contain Discord IDs")
    return sorted(set(participant_ids), key=int)


async def _add_zen_xp(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    user_id: str,
    awarded_at: datetime,
    xp: int,
) -> None:
    stmt = pg_insert(DailyStat).values(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        stat_date=awarded_at.astimezone(get_timezone()).date(),
        message_count=0,
        message_combo_xp=0,
        voice_zen_xp=xp,
        char_count=0,
        attachment_count=0,
        reactions_received=0,
        reactions_given=0,
        voice_seconds=0,
        minecraft_voice_bonus_seconds=0,
        voice_party_seconds=0,
        tea_festival_seconds=0,
        tea_carnival_seconds=0,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_daily_stat",
            set_={
                "voice_zen_xp": DailyStat.voice_zen_xp + xp,
                "updated_at": datetime.now(UTC),
            },
        )
    )


async def reconcile_voice_zen(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    participant_ids: list[str],
    observed_at: datetime | None = None,
    accrue_elapsed: bool = True,
) -> VoiceZenResult:
    """1人状態を遷移し、到達した節目を一度だけ加算する。"""
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    participants = _normalize_participants(participant_ids)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:zen_key))"),
        {"zen_key": f"voice-zen:{guild_id}:{channel_id}"},
    )
    state = (
        await session.execute(
            select(VoiceZenState)
            .where(
                VoiceZenState.guild_id == guild_id,
                VoiceZenState.channel_id == channel_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    solo_user_id = participants[0] if len(participants) == 1 else None
    if state is None and solo_user_id is None:
        await session.commit()
        return VoiceZenResult(
            guild_id,
            channel_id,
            "inactive",
            False,
            None,
            len(participants),
            0,
            (),
            None,
            None,
            False,
        )
    if state is None:
        state = VoiceZenState(guild_id=guild_id, channel_id=channel_id)
        session.add(state)
        await session.flush()

    was_active = state.active
    previous_user_id = state.user_id
    previous_announced = state.awarded_minutes >= 10
    previous_seconds = state.accumulated_seconds
    checkpoint_at = state.checkpoint_at
    newly_awarded = False
    newly_awarded_xp = 0
    if was_active and previous_user_id is not None:
        elapsed = 0
        if accrue_elapsed and checkpoint_at is not None:
            elapsed = int((now - checkpoint_at).total_seconds())
            elapsed = max(0, min(elapsed, MAX_VOICE_SESSION_SECONDS))
        new_seconds = previous_seconds + elapsed
        for minutes, xp in ZEN_REWARDS.items():
            if state.awarded_minutes < minutes <= new_seconds // 60:
                crossed_after = minutes * 60 - previous_seconds
                awarded_at = (
                    checkpoint_at + timedelta(seconds=max(0, crossed_after))
                    if checkpoint_at is not None
                    else now
                )
                await _add_zen_xp(
                    session,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=previous_user_id,
                    awarded_at=min(awarded_at, now),
                    xp=xp,
                )
                session_id = state.session_id
                if session_id is None:
                    raise RuntimeError("active voice zen state has no session_id")
                session.add(
                    VoiceZenRewardEvent(
                        event_id=f"{session_id}:{minutes}",
                        session_id=session_id,
                        guild_id=guild_id,
                        channel_id=channel_id,
                        user_id=previous_user_id,
                        minutes=minutes,
                        awarded_xp=xp,
                        awarded_at=min(awarded_at, now),
                    )
                )
                state.awarded_minutes = minutes
                newly_awarded = True
                newly_awarded_xp += xp
        state.accumulated_seconds = new_seconds

    same_solo_user = (
        was_active and previous_user_id is not None and solo_user_id == previous_user_id
    )
    ended_user_id: str | None = None
    ended_was_announced = False
    if solo_user_id is not None and same_solo_user:
        state.checkpoint_at = max(now, checkpoint_at) if checkpoint_at else now
        transition: VoiceZenTransition = "milestone" if newly_awarded else "continued"
    elif solo_user_id is not None:
        if was_active:
            ended_user_id = previous_user_id
            ended_was_announced = previous_announced or state.awarded_minutes >= 10
            transition = "switched"
        else:
            transition = "started"
        state.active = True
        state.user_id = solo_user_id
        state.session_id = str(uuid4())
        state.accumulated_seconds = 0
        state.checkpoint_at = now
        state.awarded_minutes = 0
    else:
        ended_user_id = previous_user_id if was_active else None
        ended_was_announced = previous_announced or state.awarded_minutes >= 10
        transition = "ended" if was_active else "inactive"
        state.active = False
        state.user_id = None
        state.checkpoint_at = None

    state.updated_at = now
    pending_rows = (
        await session.execute(
            select(VoiceZenRewardEvent)
            .where(
                VoiceZenRewardEvent.guild_id == guild_id,
                VoiceZenRewardEvent.channel_id == channel_id,
                VoiceZenRewardEvent.announced_at.is_(None),
            )
            .order_by(VoiceZenRewardEvent.id)
        )
    ).scalars()
    pending = tuple(
        VoiceZenAward(row.event_id, row.user_id, row.minutes, row.awarded_xp)
        for row in pending_rows
    )
    reward_user_id = pending[0].user_id if pending else None
    result_seconds = state.accumulated_seconds
    await session.commit()
    return VoiceZenResult(
        guild_id=guild_id,
        channel_id=channel_id,
        transition=transition,
        active=state.active,
        user_id=state.user_id,
        participant_count=len(participants),
        accumulated_seconds=result_seconds,
        pending_awards=pending,
        reward_user_id=reward_user_id,
        ended_user_id=ended_user_id,
        ended_was_announced=ended_was_announced,
        newly_awarded_xp=newly_awarded_xp,
    )


async def mark_voice_zen_announced(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    event_id: str,
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(VoiceZenRewardEvent)
            .where(
                VoiceZenRewardEvent.guild_id == guild_id,
                VoiceZenRewardEvent.channel_id == channel_id,
                VoiceZenRewardEvent.event_id == event_id,
                VoiceZenRewardEvent.announced_at.is_(None),
            )
            .values(announced_at=datetime.now(UTC))
        ),
    )
    await session.commit()
    return bool(result.rowcount)


async def list_active_voice_zen_channel_ids(
    session: AsyncSession, *, guild_id: str | None = None
) -> tuple[tuple[str, str], ...]:
    state_stmt = select(VoiceZenState.guild_id, VoiceZenState.channel_id).where(
        VoiceZenState.active.is_(True)
    )
    if guild_id is not None:
        state_stmt = state_stmt.where(VoiceZenState.guild_id == guild_id)
    event_stmt = select(
        VoiceZenRewardEvent.guild_id, VoiceZenRewardEvent.channel_id
    ).where(VoiceZenRewardEvent.announced_at.is_(None))
    if guild_id is not None:
        event_stmt = event_stmt.where(VoiceZenRewardEvent.guild_id == guild_id)
    rows = [
        *(await session.execute(state_stmt)).all(),
        *(await session.execute(event_stmt)).all(),
    ]
    return tuple(sorted({(str(row[0]), str(row[1])) for row in rows}))


async def get_active_voice_zen_user_id(
    session: AsyncSession, *, guild_id: str, channel_id: str
) -> str | None:
    return (
        await session.execute(
            select(VoiceZenState.user_id).where(
                VoiceZenState.guild_id == guild_id,
                VoiceZenState.channel_id == channel_id,
                VoiceZenState.active.is_(True),
            )
        )
    ).scalar_one_or_none()
