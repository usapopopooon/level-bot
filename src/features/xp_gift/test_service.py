import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.database.models import DailyStat, VoiceSession, XpGiftTransfer
from src.features.color_role_shop.service import wallet_for_user
from src.features.leveling.service import (
    earned_total_xp,
    get_level_leaderboard,
    get_user_lifetime_levels,
)
from src.features.xp_gift.service import (
    MAX_GIFT_XP,
    calculate_gift_tax,
    create_xp_gift,
    rearm_failed_notifications,
    transfer_day,
    wallet_for_xp_gift,
)

GUILD_ID = "1001"
SENDER_ID = "2001"
RECIPIENT_ID = "2002"


def _activity(user_id: str, *, messages: int) -> DailyStat:
    return DailyStat(
        guild_id=GUILD_ID,
        user_id=user_id,
        channel_id="3001",
        stat_date=date(2026, 8, 24),
        message_count=messages,
    )


def test_tax_is_per_transfer_and_only_applies_above_exemption() -> None:
    assert calculate_gift_tax(1) == 0
    assert calculate_gift_tax(1_000) == 0
    assert calculate_gift_tax(1_001) == 1
    assert calculate_gift_tax(1_500) == 50
    assert calculate_gift_tax(MAX_GIFT_XP) == 200


def test_transfer_day_resets_at_midnight_in_japan() -> None:
    assert transfer_day(datetime(2026, 8, 24, 14, 59, 59, tzinfo=UTC)) == date(
        2026, 8, 24
    )
    assert transfer_day(datetime(2026, 8, 24, 15, 0, tzinfo=UTC)) == date(2026, 8, 25)


async def test_same_event_retry_remains_idempotent_across_jst_midnight(
    db_session: AsyncSession,
) -> None:
    db_session.add(_activity(SENDER_ID, messages=1_000))
    await db_session.commit()
    common: dict[str, Any] = {
        "event_id": "gift-cross-midnight-retry",
        "guild_id": GUILD_ID,
        "sender_user_id": SENDER_ID,
        "sender_display_name": "送信者",
        "recipient_user_id": RECIPIENT_ID,
        "recipient_display_name": "受取人",
        "gift_xp": 100,
    }

    first = await create_xp_gift(
        db_session,
        now=datetime(2026, 8, 24, 14, 59, 59, tzinfo=UTC),
        **common,
    )
    retry = await create_xp_gift(
        db_session,
        now=datetime(2026, 8, 24, 15, 0, tzinfo=UTC),
        **common,
    )

    assert first.status == "completed"
    assert retry.status == "completed"
    assert first.transfer is not None and retry.transfer is not None
    assert retry.transfer.id == first.transfer.id


async def test_gift_wallet_matches_current_xp_by_including_live_voice(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        VoiceSession(
            guild_id=GUILD_ID,
            user_id=SENDER_ID,
            channel_id="3001",
            joined_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await db_session.commit()

    wallet = await wallet_for_xp_gift(
        db_session,
        guild_id=GUILD_ID,
        user_id=SENDER_ID,
    )

    assert wallet.available_xp >= 9


async def test_completed_gift_moves_xp_once_and_burns_tax(
    db_session: AsyncSession,
) -> None:
    db_session.add(_activity(SENDER_ID, messages=1_000))
    await db_session.commit()

    result = await create_xp_gift(
        db_session,
        event_id="gift-taxed",
        guild_id=GUILD_ID,
        sender_user_id=SENDER_ID,
        sender_display_name="送信者",
        recipient_user_id=RECIPIENT_ID,
        recipient_display_name="受取人",
        gift_xp=1_500,
        now=datetime(2026, 8, 24, 3, tzinfo=UTC),
    )

    assert result.status == "completed"
    assert result.transfer is not None
    assert result.transfer.gift_xp == 1_500
    assert result.transfer.tax_xp == 50
    assert result.transfer.sender_cost_xp == 1_550
    assert result.wallet_before.available_xp == 3_000
    assert result.wallet_after.available_xp == 1_450

    sender_levels = await get_user_lifetime_levels(
        db_session, GUILD_ID, SENDER_ID, include_live_voice=False
    )
    recipient_levels = await get_user_lifetime_levels(
        db_session, GUILD_ID, RECIPIENT_ID, include_live_voice=False
    )
    assert sender_levels is not None
    assert recipient_levels is not None
    assert sender_levels.total.xp == 1_450
    assert recipient_levels.total.xp == 1_500
    assert sender_levels.text.xp == 3_000
    assert recipient_levels.text.xp == 0
    assert sender_levels.total.xp + recipient_levels.total.xp == 2_950

    leaderboard = await get_level_leaderboard(db_session, GUILD_ID, axis="total")
    leaderboard_xp = {entry.user_id: entry.xp for entry in leaderboard}
    assert leaderboard_xp[SENDER_ID] == 1_450
    assert leaderboard_xp[RECIPIENT_ID] == 1_500

    recipient_wallet = await wallet_for_user(
        db_session,
        guild_id=GUILD_ID,
        user_id=RECIPIENT_ID,
        total_xp=earned_total_xp(recipient_levels),
    )
    assert recipient_wallet.available_xp == 1_500


async def test_same_recipient_is_limited_once_per_jst_day(
    db_session: AsyncSession,
) -> None:
    db_session.add(_activity(SENDER_ID, messages=1_000))
    await db_session.commit()
    common: dict[str, Any] = {
        "guild_id": GUILD_ID,
        "sender_user_id": SENDER_ID,
        "sender_display_name": "送信者",
        "gift_xp": 100,
    }

    first = await create_xp_gift(
        db_session,
        event_id="gift-first",
        recipient_user_id=RECIPIENT_ID,
        recipient_display_name="受取人",
        now=datetime(2026, 8, 24, 1, tzinfo=UTC),
        **common,
    )
    same_recipient = await create_xp_gift(
        db_session,
        event_id="gift-same-day",
        recipient_user_id=RECIPIENT_ID,
        recipient_display_name="受取人",
        now=datetime(2026, 8, 24, 2, tzinfo=UTC),
        **common,
    )
    other_recipient = await create_xp_gift(
        db_session,
        event_id="gift-other-recipient",
        recipient_user_id="2003",
        recipient_display_name="別の人",
        now=datetime(2026, 8, 24, 2, tzinfo=UTC),
        **common,
    )
    next_day = await create_xp_gift(
        db_session,
        event_id="gift-next-day",
        recipient_user_id=RECIPIENT_ID,
        recipient_display_name="受取人",
        now=datetime(2026, 8, 24, 15, tzinfo=UTC),
        **common,
    )

    assert first.status == "completed"
    assert same_recipient.status == "already_sent"
    assert same_recipient.transfer is None
    assert other_recipient.status == "completed"
    assert next_day.status == "completed"


async def test_gift_rechecks_balance_and_event_id_is_idempotent(
    db_session: AsyncSession,
) -> None:
    db_session.add(_activity(SENDER_ID, messages=400))
    await db_session.commit()
    kwargs: dict[str, Any] = {
        "event_id": "gift-idempotent",
        "guild_id": GUILD_ID,
        "sender_user_id": SENDER_ID,
        "sender_display_name": "送信者",
        "recipient_user_id": RECIPIENT_ID,
        "recipient_display_name": "受取人",
        "gift_xp": 1_100,
        "now": datetime(2026, 8, 24, 3, tzinfo=UTC),
    }

    first = await create_xp_gift(db_session, **kwargs)
    retry = await create_xp_gift(db_session, **kwargs)
    assert first.status == "completed"
    assert retry.status == "completed"
    assert retry.transfer is not None and first.transfer is not None
    first_transfer_id = first.transfer.id
    retry_transfer_id = retry.transfer.id

    too_much = await create_xp_gift(
        db_session,
        **{
            **kwargs,
            "event_id": "gift-insufficient",
            "recipient_user_id": "2003",
            "gift_xp": 101,
        },
    )

    assert retry_transfer_id == first_transfer_id
    assert too_much.status == "insufficient_xp"

    stat = (
        await db_session.execute(
            select(DailyStat).where(
                DailyStat.guild_id == GUILD_ID,
                DailyStat.user_id == SENDER_ID,
            )
        )
    ).scalar_one()
    stat.message_count = 500
    await db_session.commit()
    retry_after_earning = await create_xp_gift(
        db_session,
        **{
            **kwargs,
            "event_id": "gift-after-insufficient",
            "recipient_user_id": "2003",
            "gift_xp": 101,
        },
    )
    assert retry_after_earning.status == "completed"


async def test_concurrent_gifts_cannot_overspend_sender_wallet(
    db_session: AsyncSession,
) -> None:
    db_session.add(_activity(SENDER_ID, messages=1_000))
    await db_session.commit()
    bind = db_session.bind
    assert isinstance(bind, AsyncEngine)
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)

    async def send(event_id: str, recipient_id: str) -> str:
        async with factory() as session:
            result = await create_xp_gift(
                session,
                event_id=event_id,
                guild_id=GUILD_ID,
                sender_user_id=SENDER_ID,
                sender_display_name="送信者",
                recipient_user_id=recipient_id,
                recipient_display_name=f"受取人{recipient_id}",
                gift_xp=2_000,
                now=datetime(2026, 8, 24, 3, tzinfo=UTC),
            )
            return result.status

    statuses = await asyncio.gather(
        send("gift-concurrent-a", RECIPIENT_ID),
        send("gift-concurrent-b", "2003"),
    )

    assert sorted(statuses) == ["completed", "insufficient_xp"]


async def test_admin_rearm_only_resets_capped_undelivered_notifications(
    db_session: AsyncSession,
) -> None:
    def transfer(
        *,
        event_id: str,
        guild_id: str = GUILD_ID,
        recipient_id: str,
        attempts: int,
        message_id: str | None = None,
    ) -> XpGiftTransfer:
        return XpGiftTransfer(
            event_id=event_id,
            guild_id=guild_id,
            sender_user_id=SENDER_ID,
            sender_display_name="送信者",
            recipient_user_id=recipient_id,
            recipient_display_name="受取人",
            gift_xp=100,
            tax_xp=0,
            sender_cost_xp=100,
            transfer_day=date(2026, 8, 24),
            ledger_message_id=message_id,
            notification_attempts=attempts,
        )

    capped = transfer(event_id="gift-capped", recipient_id="2002", attempts=5)
    still_pending = transfer(event_id="gift-pending", recipient_id="2003", attempts=4)
    delivered = transfer(
        event_id="gift-delivered",
        recipient_id="2004",
        attempts=5,
        message_id="9001",
    )
    other_guild = transfer(
        event_id="gift-other-guild",
        guild_id="1002",
        recipient_id="2002",
        attempts=5,
    )
    db_session.add_all((capped, still_pending, delivered, other_guild))
    await db_session.commit()

    rearmed_ids = await rearm_failed_notifications(
        db_session,
        guild_id=GUILD_ID,
    )

    assert rearmed_ids == (capped.id,)
    await db_session.refresh(capped)
    await db_session.refresh(still_pending)
    await db_session.refresh(delivered)
    await db_session.refresh(other_guild)
    assert capped.notification_attempts == 0
    assert still_pending.notification_attempts == 4
    assert delivered.notification_attempts == 5
    assert other_guild.notification_attempts == 5
