from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, VoiceZenRewardEvent, VoiceZenState
from src.features.voice_zen.service import (
    ZEN_REWARDS,
    mark_voice_zen_announced,
    reconcile_voice_zen,
)


async def test_ten_minutes_starts_zen_and_awards_once(
    db_session: AsyncSession,
) -> None:
    start = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)
    await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start,
    )
    before = await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(seconds=599),
    )
    reached = await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(seconds=600),
    )
    duplicate = await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(seconds=660),
    )

    assert before.pending_awards == ()
    assert [(award.minutes, award.xp) for award in reached.pending_awards] == [(10, 10)]
    # 未告知イベントは再提示されるが、XP台帳と加算は増えない。
    assert duplicate.pending_awards[0].event_id == reached.pending_awards[0].event_id
    stat = (await db_session.execute(select(DailyStat))).scalar_one()
    events = (await db_session.execute(select(VoiceZenRewardEvent))).scalars().all()
    assert stat.voice_zen_xp == 10
    assert len(events) == 1


async def test_pseudo_oracle_all_milestones_have_exact_rewards(
    db_session: AsyncSession,
) -> None:
    start = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)
    await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start,
    )
    observed: dict[int, int] = {}
    for minutes, expected_xp in ZEN_REWARDS.items():
        result = await reconcile_voice_zen(
            db_session,
            guild_id="1001",
            channel_id="2001",
            participant_ids=["11"],
            observed_at=start + timedelta(minutes=minutes),
        )
        award = next(item for item in result.pending_awards if item.minutes == minutes)
        observed[minutes] = award.xp
        assert award.xp == expected_xp
        assert await mark_voice_zen_announced(
            db_session,
            guild_id="1001",
            channel_id="2001",
            event_id=award.event_id,
        )

    assert observed == ZEN_REWARDS
    stat = (await db_session.execute(select(DailyStat))).scalar_one()
    assert stat.voice_zen_xp == sum(ZEN_REWARDS.values())


async def test_second_participant_ends_zen_and_new_solo_starts_fresh(
    db_session: AsyncSession,
) -> None:
    start = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)
    await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start,
    )
    ended = await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11", "12"],
        observed_at=start + timedelta(minutes=11),
    )
    restarted = await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(minutes=12),
    )

    assert ended.transition == "ended"
    assert ended.ended_user_id == "11"
    assert ended.ended_was_announced
    assert restarted.transition == "started"
    assert restarted.accumulated_seconds == 0


async def test_restart_does_not_count_unobserved_downtime(
    db_session: AsyncSession,
) -> None:
    start = datetime(2026, 8, 7, 1, 0, tzinfo=UTC)
    await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start,
    )
    await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(minutes=5),
    )
    restored = await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(hours=2),
        accrue_elapsed=False,
    )
    after = await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(hours=2, minutes=5),
    )

    assert restored.pending_awards == ()
    assert [(award.minutes, award.xp) for award in after.pending_awards] == [(10, 10)]


async def test_reward_is_booked_on_threshold_local_date(
    db_session: AsyncSession,
) -> None:
    # JST 23:55開始、10分到達は翌日00:05。
    start = datetime(2026, 8, 7, 14, 55, tzinfo=UTC)
    await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start,
    )
    await reconcile_voice_zen(
        db_session,
        guild_id="1001",
        channel_id="2001",
        participant_ids=["11"],
        observed_at=start + timedelta(minutes=10),
    )

    stat = (await db_session.execute(select(DailyStat))).scalar_one()
    state = (await db_session.execute(select(VoiceZenState))).scalar_one()
    assert stat.stat_date == date(2026, 8, 8)
    assert state.accumulated_seconds == 600
