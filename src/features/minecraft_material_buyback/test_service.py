from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MinecraftMaterialBuyback
from src.features.leveling.service import (
    earned_total_xp,
    get_level_leaderboard,
    get_user_lifetime_levels,
)
from src.features.minecraft_material_buyback.service import (
    MATERIAL_BUYBACK_DAILY_LIMIT_XP,
    MaterialBuybackRequestResult,
    request_buyback,
    reward_for,
    update_buyback,
)

GUILD_ID = "1001"
USER_ID = "2001"
REQUEST_ID = "00000000-0000-4000-8000-000000000051"


async def _request(
    db_session: AsyncSession,
    *,
    request_id: str = REQUEST_ID,
    item_id: str = "minecraft:sand",
    item_count: int = 256,
    expected_reward_xp: int = 160,
    now: datetime | None = None,
) -> MaterialBuybackRequestResult:
    return await request_buyback(
        db_session,
        request_id=request_id,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        minecraft_account_id="mc-bot:1",
        item_id=item_id,
        item_count=item_count,
        expected_reward_xp=expected_reward_xp,
        now=now,
    )


def test_material_rates_require_whole_stacks() -> None:
    assert reward_for("minecraft:emerald", 64) == 500
    assert reward_for("minecraft:emerald", 192) == 1_500
    assert reward_for("minecraft:emerald", 384) == 3_000
    assert reward_for("minecraft:dirt", 64) == 30
    assert reward_for("minecraft:sand", 64) == 40
    assert reward_for("minecraft:sandstone", 64) == 50
    assert reward_for("minecraft:deepslate", 64) == 35
    assert reward_for("minecraft:cobbled_deepslate", 64) == 35
    assert reward_for("minecraft:tuff", 64) == 40
    assert reward_for("minecraft:sand", 256) == 160
    assert reward_for("minecraft:sand", 63) is None
    assert reward_for("minecraft:sand", 2_368) is None
    assert reward_for("minecraft:diamond", 64) is None


async def test_buyback_reserves_once_and_only_completed_reward_increases_xp(
    db_session: AsyncSession,
) -> None:
    first = await _request(db_session)
    duplicate = await _request(db_session)

    assert first.status == "reserved"
    assert first.daily_reserved_xp == 160
    assert duplicate.status == "reserved"
    assert duplicate.duplicate is True
    stored = (
        (await db_session.execute(select(MinecraftMaterialBuyback))).scalars().all()
    )
    assert len(stored) == 1
    assert await get_user_lifetime_levels(db_session, GUILD_ID, USER_ID) is None

    assert await update_buyback(
        db_session,
        request_id=REQUEST_ID,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        action="complete",
    )
    assert await update_buyback(
        db_session,
        request_id=REQUEST_ID,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        action="complete",
    )
    levels = await get_user_lifetime_levels(db_session, GUILD_ID, USER_ID)
    assert levels is not None
    assert earned_total_xp(levels) == 160
    leaderboard = await get_level_leaderboard(db_session, GUILD_ID, axis="total")
    assert [(entry.user_id, entry.xp) for entry in leaderboard] == [(USER_ID, 160)]

    completed = await _request(db_session)
    assert completed.status == "completed"
    assert completed.duplicate is True


async def test_daily_limit_counts_pending_and_cancel_releases_the_slot(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)  # JST 8/21 00:00
    full = await _request(
        db_session,
        item_id="minecraft:emerald",
        item_count=384,
        expected_reward_xp=MATERIAL_BUYBACK_DAILY_LIMIT_XP,
        now=now,
    )
    blocked = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000052",
        item_id="minecraft:dirt",
        item_count=64,
        expected_reward_xp=30,
        now=now,
    )

    assert full.status == "reserved"
    assert full.reward_day.isoformat() == "2026-08-21"
    assert blocked.status == "daily_limit"
    assert "残り売却枠は 0" in blocked.message

    assert await update_buyback(
        db_session,
        request_id=REQUEST_ID,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        action="cancel",
    )
    retried = await _request(
        db_session,
        request_id="00000000-0000-4000-8000-000000000052",
        item_id="minecraft:dirt",
        item_count=64,
        expected_reward_xp=30,
        now=now,
    )
    assert retried.status == "reserved"
    assert retried.daily_reserved_xp == 30


async def test_stale_rate_and_reused_request_id_are_rejected(
    db_session: AsyncSession,
) -> None:
    stale = await _request(db_session, expected_reward_xp=159)
    assert stale.status == "unavailable"

    assert (await _request(db_session)).status == "reserved"
    conflict = await _request(
        db_session,
        item_id="minecraft:dirt",
        item_count=64,
        expected_reward_xp=30,
    )
    assert conflict.status == "conflict"
