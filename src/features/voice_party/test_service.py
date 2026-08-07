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


async def test_tea_festival_upgrade_and_downgrade_settle_each_tier(
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
    await mark_voice_party_announced(
        db_session,
        guild_id="1001",
        channel_id="2001",
        message_id="9001",
        tier="tea_party",
    )
    upgraded = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13", "14", "15"],
        observed_at=started_at + timedelta(minutes=1),
    )
    await mark_voice_party_announced(
        db_session,
        guild_id="1001",
        channel_id="2001",
        message_id="9002",
        tier="tea_festival",
    )
    downgraded = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13", "14"],
        observed_at=started_at + timedelta(minutes=2),
    )

    assert upgraded.transition == "upgraded"
    assert upgraded.tier == "tea_festival"
    assert upgraded.previous_tier == "tea_party"
    assert upgraded.previous_announced
    assert not upgraded.announced
    assert downgraded.transition == "downgraded"
    assert downgraded.tier == "tea_party"
    assert downgraded.previous_tier == "tea_festival"
    assert downgraded.previous_announced
    assert not downgraded.announced

    rows = (
        await db_session.execute(select(DailyStat).order_by(DailyStat.user_id.asc()))
    ).scalars()
    assert [
        (row.user_id, row.voice_party_seconds, row.tea_festival_seconds) for row in rows
    ] == [
        ("11", 120, 60),
        ("12", 120, 60),
        ("13", 120, 60),
        ("14", 60, 60),
        ("15", 60, 60),
    ]


async def test_five_members_start_directly_at_tea_festival(
    db_session: AsyncSession,
) -> None:
    result = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13", "14", "15"],
        observed_at=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
    )

    assert result.transition == "started"
    assert result.tier == "tea_festival"
    assert result.previous_tier == "inactive"


async def test_tea_carnival_upgrade_and_downgrade_settle_each_tier(
    db_session: AsyncSession,
) -> None:
    started_at = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    festival_members = [str(user_id) for user_id in range(11, 16)]
    carnival_members = [str(user_id) for user_id in range(11, 21)]
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=festival_members,
        observed_at=started_at,
    )
    await mark_voice_party_announced(
        db_session,
        guild_id="1001",
        channel_id="2001",
        message_id="9001",
        tier="tea_festival",
    )
    upgraded = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=carnival_members,
        observed_at=started_at + timedelta(minutes=1),
    )
    await mark_voice_party_announced(
        db_session,
        guild_id="1001",
        channel_id="2001",
        message_id="9002",
        tier="tea_carnival",
    )
    downgraded = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=carnival_members[:9],
        observed_at=started_at + timedelta(minutes=2),
    )

    assert upgraded.transition == "upgraded"
    assert upgraded.tier == "tea_carnival"
    assert upgraded.previous_tier == "tea_festival"
    assert downgraded.transition == "downgraded"
    assert downgraded.tier == "tea_festival"
    assert downgraded.previous_tier == "tea_carnival"

    rows = (
        await db_session.execute(select(DailyStat).order_by(DailyStat.user_id.asc()))
    ).scalars()
    bonuses = {
        row.user_id: (
            row.voice_party_seconds,
            row.tea_festival_seconds,
            row.tea_carnival_seconds,
        )
        for row in rows
    }
    assert bonuses["11"] == (120, 120, 60)
    assert bonuses["15"] == (120, 120, 60)
    assert bonuses["16"] == (60, 60, 60)
    assert bonuses["20"] == (60, 60, 60)


async def test_ten_members_start_and_end_directly_as_tea_carnival(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    participants = [str(user_id) for user_id in range(11, 21)]
    started = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=participants,
        observed_at=now,
    )
    await mark_voice_party_announced(
        db_session,
        guild_id="1001",
        channel_id="2001",
        message_id="9001",
        tier="tea_carnival",
    )
    ended = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12"],
        observed_at=now + timedelta(minutes=1),
    )

    assert started.transition == "started"
    assert started.tier == "tea_carnival"
    assert ended.transition == "ended"
    assert ended.previous_tier == "tea_carnival"
    assert ended.previous_announced
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert len(rows) == 10
    assert all(row.voice_party_seconds == 60 for row in rows)
    assert all(row.tea_festival_seconds == 60 for row in rows)
    assert all(row.tea_carnival_seconds == 60 for row in rows)


async def test_tea_festival_can_end_directly_without_downgrade(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    participants = ["11", "12", "13", "14", "15"]
    await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=participants,
        observed_at=now,
    )
    await mark_voice_party_announced(
        db_session,
        guild_id="1001",
        channel_id="2001",
        message_id="9001",
        tier="tea_festival",
    )
    ended = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12"],
        observed_at=now + timedelta(minutes=1),
    )

    assert ended.transition == "ended"
    assert ended.previous_tier == "tea_festival"
    assert ended.previous_announced
    rows = (await db_session.execute(select(DailyStat))).scalars().all()
    assert all(row.voice_party_seconds == 60 for row in rows)
    assert all(row.tea_festival_seconds == 60 for row in rows)


async def test_deploy_upgrades_legacy_tea_announcement_for_five_members(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    db_session.add(
        VoicePartyState(
            guild_id="1001",
            channel_id="2001",
            active=True,
            tier="tea_party",
            participant_ids=["11", "12", "13", "14", "15"],
            activated_at=now - timedelta(minutes=5),
            checkpoint_at=now - timedelta(minutes=1),
            announced=True,
            announced_tier="tea_party",
            announcement_message_id="9001",
        )
    )
    await db_session.commit()

    result = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13", "14", "15"],
        observed_at=now,
        accrue_elapsed=False,
    )

    assert result.transition == "upgraded"
    assert result.tier == "tea_festival"
    assert result.previous_announced
    assert not result.announced
    state = (await db_session.execute(select(VoicePartyState))).scalar_one()
    assert state.announced_tier is None


async def test_deploy_does_not_repeat_legacy_tea_notice_after_drop_to_four(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    db_session.add(
        VoicePartyState(
            guild_id="1001",
            channel_id="2001",
            active=True,
            tier="tea_party",
            participant_ids=["11", "12", "13", "14", "15"],
            activated_at=now - timedelta(minutes=5),
            checkpoint_at=now - timedelta(minutes=1),
            announced=True,
            announced_tier="tea_party",
            announcement_message_id="9001",
        )
    )
    await db_session.commit()

    result = await reconcile_voice_party(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12", "13", "14"],
        observed_at=now,
        accrue_elapsed=False,
    )

    assert result.transition == "continued"
    assert result.tier == "tea_party"
    assert result.announced
    assert result.announcement_message_id == "9001"


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
        tier="tea_party",
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


async def test_all_member_count_boundaries_have_stable_transitions(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    counts_and_expected = [
        (0, "inactive", "inactive"),
        (1, "inactive", "inactive"),
        (2, "inactive", "inactive"),
        (3, "started", "tea_party"),
        (4, "continued", "tea_party"),
        (5, "upgraded", "tea_festival"),
        (9, "continued", "tea_festival"),
        (10, "upgraded", "tea_carnival"),
        (11, "continued", "tea_carnival"),
        (10, "continued", "tea_carnival"),
        (9, "downgraded", "tea_festival"),
        (5, "continued", "tea_festival"),
        (4, "downgraded", "tea_party"),
        (3, "continued", "tea_party"),
        (2, "ended", "inactive"),
        (1, "inactive", "inactive"),
        (0, "inactive", "inactive"),
    ]

    for minute, (count, expected_transition, expected_tier) in enumerate(
        counts_and_expected
    ):
        result = await reconcile_voice_party(
            db_session,
            guild_id="1001",
            channel_id="2001",
            participant_ids=[str(user_id) for user_id in range(11, 11 + count)],
            observed_at=now + timedelta(minutes=minute),
        )
        assert result.transition == expected_transition
        assert result.tier == expected_tier
