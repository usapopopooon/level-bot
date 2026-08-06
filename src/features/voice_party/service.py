"""同一VCの人数に応じた段階制ボーナス時間を安全に集計する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import MAX_VOICE_SESSION_SECONDS
from src.database.models import DailyStat, VoicePartyState
from src.features.tracking.service import split_interval_by_local_hour
from src.utils import get_timezone

VOICE_PARTY_MIN_MEMBERS = 3
VOICE_PARTY_MULTIPLIER = 1.5
TEA_FESTIVAL_MIN_MEMBERS = 5
TEA_FESTIVAL_MULTIPLIER = 2.0

type VoicePartyTier = Literal["inactive", "tea_party", "tea_festival"]
type VoicePartyTransition = Literal[
    "started", "continued", "upgraded", "downgraded", "ended", "inactive"
]


@dataclass(frozen=True)
class VoicePartyResult:
    guild_id: str
    channel_id: str
    transition: VoicePartyTransition
    active: bool
    participant_count: int
    announced: bool
    announcement_message_id: str | None
    previous_announced: bool
    tier: VoicePartyTier
    previous_tier: VoicePartyTier


def _normalize_participants(participant_ids: list[str]) -> list[str]:
    if any(not user_id.isdigit() for user_id in participant_ids):
        msg = "participant_ids must contain Discord IDs"
        raise ValueError(msg)
    return sorted(set(participant_ids), key=int)


def _tier_for_count(participant_count: int) -> VoicePartyTier:
    if participant_count >= TEA_FESTIVAL_MIN_MEMBERS:
        return "tea_festival"
    if participant_count >= VOICE_PARTY_MIN_MEMBERS:
        return "tea_party"
    return "inactive"


async def _add_party_seconds(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    user_id: str,
    started_at: datetime,
    ended_at: datetime,
    tier: VoicePartyTier,
) -> None:
    for day, _hour, seconds in split_interval_by_local_hour(
        started_at,
        ended_at,
        tz=get_timezone(),
    ):
        if seconds <= 0:
            continue
        stmt = pg_insert(DailyStat).values(
            guild_id=guild_id,
            user_id=user_id,
            channel_id=channel_id,
            stat_date=day,
            message_count=0,
            char_count=0,
            attachment_count=0,
            reactions_received=0,
            reactions_given=0,
            voice_seconds=0,
            minecraft_voice_bonus_seconds=0,
            voice_party_seconds=seconds,
            tea_festival_seconds=(seconds if tier == "tea_festival" else 0),
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_daily_stat",
            set_={
                "voice_party_seconds": DailyStat.voice_party_seconds + seconds,
                "tea_festival_seconds": (
                    DailyStat.tea_festival_seconds
                    + (seconds if tier == "tea_festival" else 0)
                ),
                "updated_at": datetime.now(UTC),
            },
        )
        await session.execute(stmt)


async def reconcile_voice_party(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    participant_ids: list[str],
    observed_at: datetime | None = None,
    accrue_elapsed: bool = True,
) -> VoicePartyResult:
    """現在人数へ状態を遷移し、前回checkpointまでの対象時間を確定する。"""
    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        msg = "observed_at must include a timezone"
        raise ValueError(msg)
    participants = _normalize_participants(participant_ids)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:party_key))"),
        {"party_key": f"voice-party:{guild_id}:{channel_id}"},
    )
    state = (
        await session.execute(
            select(VoicePartyState)
            .where(
                VoicePartyState.guild_id == guild_id,
                VoicePartyState.channel_id == channel_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    new_tier = _tier_for_count(len(participants))
    new_active = new_tier != "inactive"
    if state is None and not new_active:
        # advisory lock をこのサービス呼び出し内で確実に解放する。
        await session.commit()
        return VoicePartyResult(
            guild_id,
            channel_id,
            "inactive",
            False,
            len(participants),
            False,
            None,
            False,
            "inactive",
            "inactive",
        )
    if state is None:
        state = VoicePartyState(
            guild_id=guild_id,
            channel_id=channel_id,
            active=False,
            tier="inactive",
            participant_ids=[],
            announced=False,
        )
        session.add(state)
        await session.flush()

    was_active = state.active
    was_announced = state.announced
    announcement_message_id = state.announcement_message_id
    announced_tier = cast("VoicePartyTier | None", state.announced_tier)
    checkpoint_at = state.checkpoint_at
    previous_participants = list(state.participant_ids)
    previous_tier: VoicePartyTier = "inactive"
    if was_active:
        previous_tier = (
            cast("VoicePartyTier", state.tier)
            if state.tier in {"tea_party", "tea_festival"}
            else _tier_for_count(len(previous_participants))
        )

    if (
        accrue_elapsed
        and was_active
        and previous_tier != "inactive"
        and checkpoint_at is not None
    ):
        elapsed = int((now - checkpoint_at).total_seconds())
        if 0 < elapsed <= MAX_VOICE_SESSION_SECONDS:
            effective_end = checkpoint_at + timedelta(seconds=elapsed)
            for user_id in previous_participants:
                await _add_party_seconds(
                    session,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=user_id,
                    started_at=checkpoint_at,
                    ended_at=effective_end,
                    tier=previous_tier,
                )

    if new_active:
        state.active = True
        state.tier = new_tier
        state.participant_ids = participants
        # OS 時刻が一時的に巻き戻っても、次回に同じ区間を二重加算しない。
        state.checkpoint_at = max(now, checkpoint_at) if checkpoint_at else now
        if not was_active:
            state.activated_at = now
            state.announced = False
            state.announced_tier = None
            state.announcement_message_id = None
            transition: VoicePartyTransition = "started"
        elif previous_tier != new_tier or (
            was_announced and announced_tier != new_tier
        ):
            state.announced = False
            state.announced_tier = None
            state.announcement_message_id = None
            transition = "upgraded" if new_tier == "tea_festival" else "downgraded"
        else:
            transition = "continued"
    else:
        state.active = False
        state.tier = "inactive"
        state.participant_ids = []
        state.activated_at = None
        state.checkpoint_at = None
        state.announced = False
        state.announced_tier = None
        state.announcement_message_id = None
        transition = "ended" if was_active else "inactive"
    state.updated_at = now
    await session.commit()
    return VoicePartyResult(
        guild_id=guild_id,
        channel_id=channel_id,
        transition=transition,
        active=state.active,
        participant_count=len(participants),
        announced=state.announced,
        announcement_message_id=(
            state.announcement_message_id if state.active else announcement_message_id
        ),
        previous_announced=was_announced,
        tier=new_tier,
        previous_tier=previous_tier,
    )


async def mark_voice_party_announced(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
    message_id: str,
    tier: VoicePartyTier,
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(VoicePartyState)
            .where(
                VoicePartyState.guild_id == guild_id,
                VoicePartyState.channel_id == channel_id,
                VoicePartyState.active.is_(True),
                VoicePartyState.tier == tier,
            )
            .values(
                announced=True,
                announced_tier=tier,
                announcement_message_id=message_id,
                updated_at=datetime.now(UTC),
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)


async def mark_voice_party_unannounced(
    session: AsyncSession,
    *,
    guild_id: str,
    channel_id: str,
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(VoicePartyState)
            .where(
                VoicePartyState.guild_id == guild_id,
                VoicePartyState.channel_id == channel_id,
                VoicePartyState.active.is_(True),
            )
            .values(
                announced=False,
                announced_tier=None,
                announcement_message_id=None,
                updated_at=datetime.now(UTC),
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)


async def list_active_voice_party_channel_ids(
    session: AsyncSession, *, guild_id: str | None = None
) -> tuple[tuple[str, str], ...]:
    stmt = select(VoicePartyState.guild_id, VoicePartyState.channel_id).where(
        VoicePartyState.active.is_(True)
    )
    if guild_id is not None:
        stmt = stmt.where(VoicePartyState.guild_id == guild_id)
    rows = (await session.execute(stmt)).all()
    return tuple((str(row[0]), str(row[1])) for row in rows)
