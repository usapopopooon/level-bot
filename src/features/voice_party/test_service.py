from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, VoicePartyState
from src.features.voice_party.service import (
    mark_voice_party_announced,
    reconcile_voice_party,
)


async def test_fewer_than_three_members_stays_inactive_without_state(
    db_session: AsyncSession,
) -> None:
    result = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12"],
        observed_at=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
    )

    assert result.transition == "inactive"
    assert (
        await db_session.execute(select(VoicePartyState))
    ).scalar_one_or_none() is None


async def test_three_members_start_and_receive_half_rate_bonus(
    db_session: AsyncSession,
) -> None:
    started_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    started = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=started_at,
    )
    continued = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=started_at + timedelta(minutes=2),
    )

    assert started.transition == "started"
    assert continued.transition == "continued"
    rows = (
        await db_session.execute(select(DailyStat).order_by(DailyStat.user_id.asc()))
    ).scalars()
    assert [(row.user_id, row.voice_party_seconds) for row in rows] == [
        ("11", 120),
        ("12", 120),
        ("13", 120),
    ]


async def test_member_changes_settle_only_the_previous_participants(
    db_session: AsyncSession,
) -> None:
    started_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=started_at,
    )
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13", "14"],
        observed_at=started_at + timedelta(minutes=1),
    )
    ended = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12"],
        observed_at=started_at + timedelta(minutes=2),
    )

    assert ended.transition == "ended"
    rows = (
        await db_session.execute(select(DailyStat).order_by(DailyStat.user_id.asc()))
    ).scalars()
    assert [(row.user_id, row.voice_party_seconds) for row in rows] == [
        ("11", 120),
        ("12", 120),
        ("13", 120),
        ("14", 60),
    ]


async def test_restart_reconciles_without_awarding_downtime(
    db_session: AsyncSession,
) -> None:
    started_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=started_at,
    )
    restored = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=started_at + timedelta(hours=1),
        accrue_elapsed=False,
    )

    assert restored.active
    assert restored.transition == "continued"
    assert (await db_session.execute(select(DailyStat))).scalar_one_or_none() is None
    state = (await db_session.execute(select(VoicePartyState))).scalar_one()
    assert state.checkpoint_at == started_at + timedelta(hours=1)


async def test_announcement_state_survives_restart_until_party_ends(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=now,
    )
    assert await mark_voice_party_announced(
        db_session,
        guild_id="1001",
        channel_id="2001",
        message_id="9999",
    )
    restored = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=now + timedelta(seconds=30),
        accrue_elapsed=False,
    )
    ended = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12"],
        observed_at=now + timedelta(seconds=60),
    )

    assert restored.announced
    assert restored.announcement_message_id == "9999"
    assert ended.previous_announced
    assert not ended.active


async def test_party_seconds_split_at_local_day_boundary(
    db_session: AsyncSession,
) -> None:
    started_at = datetime(2026, 8, 6, 14, 59, 30, tzinfo=UTC)  # 23:59:30 JST
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=started_at,
    )
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13"],
        observed_at=started_at + timedelta(seconds=60),
    )

    rows = (
        await db_session.execute(
            select(DailyStat)
            .where(DailyStat.user_id == "11")
            .order_by(DailyStat.stat_date)
        )
    ).scalars()
    assert [(row.stat_date, row.voice_party_seconds) for row in rows] == [
        (date(2026, 8, 6), 30),
        (date(2026, 8, 7), 30),
    ]


async def test_clock_rollback_does_not_double_count_elapsed_time(
    db_session: AsyncSession,
) -> None:
    started_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    participants = ["11", "12", "13"]
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=participants,
        observed_at=started_at,
    )
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=participants,
        observed_at=started_at - timedelta(seconds=30),
    )
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=participants,
        observed_at=started_at + timedelta(seconds=60),
    )

    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert {row.user_id: row.voice_party_seconds for row in rows} == {
        "11": 60,
        "12": 60,
        "13": 60,
    }


async def test_invalid_participant_id_is_rejected(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="participant_ids must contain Discord IDs"):
        await reconcile_voice_party(
            db_session,
            guild_id="1001",
            channel_id="2001",
            participant_ids=["11", "not-an-id", "13"],
            observed_at=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
        )
