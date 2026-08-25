from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    CoffeeBeanLot,
    CoffeeMarketGuildConfig,
    CoffeeMarketSale,
    CoffeeMarketXpTransaction,
    DailyStat,
)
from src.features.coffee_market.adapters.level_bot import LEVEL_BOT_DEPENDENCIES
from src.features.coffee_market.contracts import (
    AlreadyPurchasedToday,
    InsufficientXp,
    InvalidQuantity,
    NoSellableBeans,
)
from src.features.coffee_market.domain import MAX_DAILY_QUANTITY, quote_for
from src.features.coffee_market.ports import (
    CoffeeMarketDependencies,
    XpMovementConflict,
    XpMovementResult,
    XpWalletSnapshot,
)
from src.features.coffee_market.service import (
    get_public_activity_version,
    get_user_position,
    list_pending_ledger_entries,
    list_user_history,
    mark_ledger_entry_posted,
    purchase_beans,
    rankings,
    save_ledger_channel,
    save_panel_placement,
    sell_beans,
    settle_expired_lots,
)
from src.features.guilds.service import get_guild_settings, upsert_guild
from src.features.leveling.service import (
    get_level_leaderboard,
    get_user_lifetime_levels,
)

GUILD_ID = "1001"
USER_ID = "2001"
START_DAY = date(2026, 8, 25)


class _Wallet:
    def __init__(self, available_xp: int = 100_000) -> None:
        self.available_xp = available_xp
        self.calls: list[tuple[str, str]] = []
        self.events: dict[str, tuple[str, int]] = {}

    async def get_balance(
        self,
        _session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
    ) -> XpWalletSnapshot:
        self.calls.append((guild_id, user_id))
        return XpWalletSnapshot(
            total_xp=self.available_xp,
            spent_xp=0,
            available_xp=self.available_xp,
        )

    async def debit(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        amount_xp: int,
    ) -> XpMovementResult:
        existing = self.events.get(event_id)
        if existing is not None and existing != ("debit", amount_xp):
            raise XpMovementConflict
        before = self.available_xp
        if existing is not None:
            return XpMovementResult("already_completed", before + amount_xp, before)
        if before < amount_xp:
            return XpMovementResult("insufficient", before, before)
        self.calls.append((guild_id, user_id))
        self.events[event_id] = ("debit", amount_xp)
        self.available_xp -= amount_xp
        return XpMovementResult("completed", before, self.available_xp)

    async def credit(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        guild_id: str,
        user_id: str,
        amount_xp: int,
    ) -> XpMovementResult:
        existing = self.events.get(event_id)
        if existing is not None and existing != ("credit", amount_xp):
            raise XpMovementConflict
        before = self.available_xp
        if existing is not None:
            return XpMovementResult("already_completed", before - amount_xp, before)
        self.calls.append((guild_id, user_id))
        self.events[event_id] = ("credit", amount_xp)
        self.available_xp += amount_xp
        return XpMovementResult("completed", before, self.available_xp)


class _LevelSync:
    def __init__(self) -> None:
        self.guild_ids: list[str] = []

    async def request(self, _session: AsyncSession, *, guild_id: str) -> None:
        self.guild_ids.append(guild_id)


class _FailingLevelSync:
    async def request(self, _session: AsyncSession, *, guild_id: str) -> None:
        raise RuntimeError(f"cannot request level sync for {guild_id}")


def _deps(
    wallet: _Wallet | None = None,
    level_sync: _LevelSync | None = None,
) -> CoffeeMarketDependencies:
    return CoffeeMarketDependencies(
        xp_wallet=wallet or _Wallet(),
        level_sync=level_sync or _LevelSync(),
    )


async def test_public_panels_and_ledger_channel_are_saved_independently(
    db_session: AsyncSession,
) -> None:
    await save_ledger_channel(
        db_session,
        guild_id=GUILD_ID,
        channel_id="3001",
    )
    await save_panel_placement(
        db_session,
        guild_id=GUILD_ID,
        panel_kind="market",
        channel_id="3002",
        message_id="4002",
    )
    await save_panel_placement(
        db_session,
        guild_id=GUILD_ID,
        panel_kind="ranking",
        channel_id="3003",
        message_id="4003",
    )

    config = (
        await db_session.execute(
            select(CoffeeMarketGuildConfig).where(
                CoffeeMarketGuildConfig.guild_id == GUILD_ID
            )
        )
    ).scalar_one()
    assert (config.panel_channel_id, config.panel_message_id) == ("3002", "4002")
    assert config.ledger_channel_id == "3001"
    assert (config.ranking_channel_id, config.ranking_message_id) == (
        "3003",
        "4003",
    )


async def test_purchase_is_once_per_day_and_idempotent(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    result = await purchase_beans(
        db_session,
        event_id="buy-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=10,
        market_day=START_DAY,
        dependencies=dependencies,
    )

    assert result.status == "completed"
    assert result.quantity == 10
    assert result.cost_xp == result.unit_price_xp * 10
    assert result.sellable_on == START_DAY + timedelta(days=1)
    assert result.expires_on == START_DAY + timedelta(days=7)

    replay = await purchase_beans(
        db_session,
        event_id="buy-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=10,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    assert replay.status == "already_completed"

    with pytest.raises(AlreadyPurchasedToday):
        await purchase_beans(
            db_session,
            event_id="buy-2",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            quantity=1,
            market_day=START_DAY,
            dependencies=dependencies,
        )


async def test_purchase_validates_quantity_and_available_xp(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(InvalidQuantity):
        await purchase_beans(
            db_session,
            event_id="invalid-zero",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            quantity=0,
            market_day=START_DAY,
            dependencies=_deps(),
        )
    with pytest.raises(InvalidQuantity):
        await purchase_beans(
            db_session,
            event_id="invalid-max",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            quantity=MAX_DAILY_QUANTITY + 1,
            market_day=START_DAY,
            dependencies=_deps(),
        )
    with pytest.raises(InsufficientXp) as error:
        await purchase_beans(
            db_session,
            event_id="poor",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            quantity=1,
            market_day=START_DAY,
            dependencies=_deps(_Wallet(available_xp=1)),
        )
    assert error.value.available_xp == 1


async def test_same_day_purchase_cannot_be_sold_and_next_day_uses_fifo(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    first = await purchase_beans(
        db_session,
        event_id="buy-first",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=10,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    with pytest.raises(NoSellableBeans):
        await sell_beans(
            db_session,
            event_id="sell-too-soon",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            quantity=1,
            market_day=START_DAY,
            dependencies=dependencies,
        )

    second_day = START_DAY + timedelta(days=1)
    await purchase_beans(
        db_session,
        event_id="buy-second",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=5,
        market_day=second_day,
        dependencies=dependencies,
    )
    sale = await sell_beans(
        db_session,
        event_id="sell-next-day",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=6,
        market_day=second_day,
        dependencies=dependencies,
    )

    assert sale.quantity == 6
    assert sale.cost_basis_xp == first.unit_price_xp * 6
    lots = tuple(
        (
            await db_session.execute(
                select(CoffeeBeanLot).order_by(CoffeeBeanLot.purchased_on.asc())
            )
        ).scalars()
    )
    assert [row.remaining_quantity for row in lots] == [4, 5]


async def test_manual_sale_can_exceed_the_daily_purchase_limit(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    for offset in range(2):
        await purchase_beans(
            db_session,
            event_id=f"bulk-buy-{offset}",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            quantity=10,
            market_day=START_DAY + timedelta(days=offset),
            dependencies=dependencies,
        )

    sale = await sell_beans(
        db_session,
        event_id="bulk-sale",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=15,
        market_day=START_DAY + timedelta(days=2),
        dependencies=dependencies,
    )

    assert sale.quantity == 15


async def test_expiry_forces_sale_at_that_days_quote_once(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    purchase = await purchase_beans(
        db_session,
        event_id="expiring-buy",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=8,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    expiry_day = START_DAY + timedelta(days=7)

    settled = await settle_expired_lots(
        db_session,
        guild_id=GUILD_ID,
        market_day=expiry_day,
        dependencies=dependencies,
    )

    expected_quote = quote_for(GUILD_ID, expiry_day)
    assert len(settled) == 1
    assert settled[0].sale_kind == "expired"
    assert settled[0].quantity == 8
    assert settled[0].unit_price_xp == expected_quote.sell_price_xp
    assert settled[0].payout_xp == expected_quote.sell_price_xp * 8
    assert settled[0].cost_basis_xp == purchase.cost_xp
    assert (
        await db_session.execute(select(CoffeeBeanLot.remaining_quantity))
    ).scalar_one() == 0

    replay = await settle_expired_lots(
        db_session,
        guild_id=GUILD_ID,
        market_day=expiry_day,
        dependencies=dependencies,
    )
    assert replay == ()
    assert (
        len((await db_session.execute(select(CoffeeMarketSale))).scalars().all()) == 1
    )


async def test_late_expiry_processing_keeps_the_original_expiry_day_price(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    await purchase_beans(
        db_session,
        event_id="offline-buy",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=3,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    expiry_day = START_DAY + timedelta(days=7)
    recovery_day = expiry_day + timedelta(days=3)

    settled = await settle_expired_lots(
        db_session,
        guild_id=GUILD_ID,
        market_day=recovery_day,
        dependencies=dependencies,
    )

    assert settled[0].market_day == expiry_day
    assert settled[0].unit_price_xp == quote_for(GUILD_ID, expiry_day).sell_price_xp


async def test_position_history_and_rankings(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    await purchase_beans(
        db_session,
        event_id="position-buy",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=10,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    sale_day = START_DAY + timedelta(days=1)
    sale = await sell_beans(
        db_session,
        event_id="position-sale",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=4,
        market_day=sale_day,
        dependencies=dependencies,
    )

    _quote, position = await get_user_position(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        market_day=sale_day,
        dependencies=dependencies,
    )
    assert position.quantity == 6
    assert position.sellable_quantity == 6
    assert position.evaluation_xp > 0

    history = await list_user_history(db_session, guild_id=GUILD_ID, user_id=USER_ID)
    assert {row.kind for row in history} == {"buy", "manual"}

    snapshot = await rankings(db_session, guild_id=GUILD_ID, market_day=sale_day)
    assert snapshot.daily[0].user_id == USER_ID
    assert snapshot.daily[0].profit_xp == sale.profit_xp
    assert snapshot.last_five_days == snapshot.daily
    assert snapshot.cumulative == snapshot.daily


async def test_rankings_split_daily_last_five_days_and_cumulative_by_market_day(
    db_session: AsyncSession,
) -> None:
    ranking_day = date(2026, 8, 26)

    def sale(
        event_id: str,
        user_id: str,
        market_day: date,
        payout_xp: int,
        cost_basis_xp: int,
        *,
        guild_id: str = GUILD_ID,
    ) -> CoffeeMarketSale:
        return CoffeeMarketSale(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            market_day=market_day,
            sale_kind="manual",
            quantity=1,
            sell_price_xp=payout_xp,
            payout_xp=payout_xp,
            cost_basis_xp=cost_basis_xp,
        )

    db_session.add_all(
        (
            sale("recent-boundary-2001", "2001", date(2026, 8, 22), 200, 100),
            sale("recent-2001", "2001", date(2026, 8, 25), 120, 100),
            sale("daily-2001", "2001", ranking_day, 110, 100),
            sale("daily-2002", "2002", ranking_day, 150, 100),
            sale("before-recent-2003", "2003", date(2026, 8, 21), 300, 100),
            sale("future", "2004", date(2026, 8, 27), 999, 100),
            sale(
                "other-guild",
                "2005",
                ranking_day,
                999,
                100,
                guild_id="1002",
            ),
        )
    )
    await db_session.commit()

    snapshot = await rankings(
        db_session,
        guild_id=GUILD_ID,
        market_day=ranking_day,
    )

    assert snapshot.market_day == ranking_day
    assert [(row.user_id, row.profit_xp) for row in snapshot.daily] == [
        ("2002", 50),
        ("2001", 10),
    ]
    assert [(row.user_id, row.profit_xp) for row in snapshot.last_five_days] == [
        ("2001", 130),
        ("2002", 50),
    ]
    assert [(row.user_id, row.profit_xp) for row in snapshot.cumulative] == [
        ("2003", 200),
        ("2001", 130),
        ("2002", 50),
    ]


async def test_pending_ledger_contains_every_unposted_purchase_and_sale(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    assert await get_public_activity_version(db_session, guild_id=GUILD_ID) == (0, 0)
    await purchase_beans(
        db_session,
        event_id="ledger-buy-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=3,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    await purchase_beans(
        db_session,
        event_id="ledger-buy-2",
        guild_id=GUILD_ID,
        user_id="2002",
        quantity=4,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    await sell_beans(
        db_session,
        event_id="ledger-sale-2",
        guild_id=GUILD_ID,
        user_id="2002",
        quantity=2,
        market_day=START_DAY + timedelta(days=1),
        dependencies=dependencies,
    )

    ledger = await list_pending_ledger_entries(db_session, guild_id=GUILD_ID)
    latest_lot_id, latest_sale_id = await get_public_activity_version(
        db_session, guild_id=GUILD_ID
    )

    assert {(entry.user_id, entry.kind, entry.quantity) for entry in ledger} == {
        (USER_ID, "buy", 3),
        ("2002", "buy", 4),
        ("2002", "manual", 2),
    }
    assert latest_lot_id > 0
    assert latest_sale_id > 0

    purchase_entry = next(
        entry for entry in ledger if entry.user_id == USER_ID and entry.kind == "buy"
    )
    assert await mark_ledger_entry_posted(
        db_session,
        guild_id=GUILD_ID,
        kind=purchase_entry.kind,
        record_id=purchase_entry.record_id,
        message_id="9001",
    )
    assert not await mark_ledger_entry_posted(
        db_session,
        guild_id=GUILD_ID,
        kind=purchase_entry.kind,
        record_id=purchase_entry.record_id,
        message_id="9002",
    )
    remaining = await list_pending_ledger_entries(db_session, guild_id=GUILD_ID)
    assert (USER_ID, "buy", 3) not in {
        (entry.user_id, entry.kind, entry.quantity) for entry in remaining
    }


async def test_ledger_channel_backfills_transactions_created_before_configuration(
    db_session: AsyncSession,
) -> None:
    await purchase_beans(
        db_session,
        event_id="ledger-before-config",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=2,
        market_day=START_DAY,
        dependencies=_deps(),
    )

    await save_ledger_channel(db_session, guild_id=GUILD_ID, channel_id="3001")
    pending = await list_pending_ledger_entries(db_session, guild_id=GUILD_ID)

    assert [(entry.kind, entry.quantity) for entry in pending] == [("buy", 2)]


async def test_pending_ledger_order_is_stable_and_chronological_when_timestamps_match(
    db_session: AsyncSession,
) -> None:
    dependencies = _deps()
    await purchase_beans(
        db_session,
        event_id="stable-buy-1",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=3,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    await purchase_beans(
        db_session,
        event_id="stable-buy-2",
        guild_id=GUILD_ID,
        user_id="2002",
        quantity=4,
        market_day=START_DAY,
        dependencies=dependencies,
    )
    await sell_beans(
        db_session,
        event_id="stable-sale",
        guild_id=GUILD_ID,
        user_id="2002",
        quantity=2,
        market_day=START_DAY + timedelta(days=1),
        dependencies=dependencies,
    )
    same_time = datetime(2026, 8, 27, tzinfo=UTC)
    for lot in (await db_session.execute(select(CoffeeBeanLot))).scalars():
        lot.created_at = same_time
    for sale in (await db_session.execute(select(CoffeeMarketSale))).scalars():
        sale.created_at = same_time
    await db_session.commit()

    first = await list_pending_ledger_entries(db_session, guild_id=GUILD_ID)
    second = await list_pending_ledger_entries(db_session, guild_id=GUILD_ID)
    first_history = await list_user_history(
        db_session, guild_id=GUILD_ID, user_id="2002"
    )
    second_history = await list_user_history(
        db_session, guild_id=GUILD_ID, user_id="2002"
    )

    first_keys = [(row.kind, row.record_id) for row in first]
    assert first_keys == [(row.kind, row.record_id) for row in second]
    assert first_keys == sorted(
        first_keys,
        key=lambda row: (row[0] != "buy", row[1]),
    )
    history_keys = [(row.kind, row.record_id) for row in first_history]
    assert history_keys == [(row.kind, row.record_id) for row in second_history]
    assert history_keys == sorted(
        history_keys,
        key=lambda row: (row[0] != "buy", row[1]),
        reverse=True,
    )


async def test_level_bot_adapter_lowers_level_on_buy_and_credits_sale(
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="Coffee test guild",
        icon_url=None,
        member_count=2,
    )
    db_session.add(
        DailyStat(
            guild_id=GUILD_ID,
            user_id=USER_ID,
            channel_id="3001",
            stat_date=START_DAY,
            message_count=1_000,
        )
    )
    await db_session.commit()

    purchase = await purchase_beans(
        db_session,
        event_id="wired-buy",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=10,
        market_day=START_DAY,
        dependencies=LEVEL_BOT_DEPENDENCIES,
    )
    after_buy = await get_user_lifetime_levels(
        db_session, GUILD_ID, USER_ID, include_live_voice=False
    )
    assert after_buy is not None
    assert after_buy.total.xp == 3_000 - purchase.cost_xp

    sale = await sell_beans(
        db_session,
        event_id="wired-sale",
        guild_id=GUILD_ID,
        user_id=USER_ID,
        quantity=None,
        market_day=START_DAY + timedelta(days=1),
        dependencies=LEVEL_BOT_DEPENDENCIES,
    )
    after_sale = await get_user_lifetime_levels(
        db_session, GUILD_ID, USER_ID, include_live_voice=False
    )
    assert after_sale is not None
    expected_xp = 3_000 - purchase.cost_xp + sale.payout_xp
    assert after_sale.total.xp == expected_xp

    xp_transactions = tuple(
        (
            await db_session.execute(
                select(CoffeeMarketXpTransaction).order_by(
                    CoffeeMarketXpTransaction.id.asc()
                )
            )
        ).scalars()
    )
    assert [(row.direction, row.amount_xp) for row in xp_transactions] == [
        ("debit", purchase.cost_xp),
        ("credit", sale.payout_xp),
    ]

    leaderboard = await get_level_leaderboard(db_session, GUILD_ID, axis="total")
    assert {entry.user_id: entry.xp for entry in leaderboard}[USER_ID] == expected_xp
    settings = await get_guild_settings(db_session, GUILD_ID)
    assert settings is not None
    assert settings.level_role_sync_requested_at is not None


async def test_level_sync_failure_rolls_back_trade_and_xp_together(
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="Coffee rollback guild",
        icon_url=None,
        member_count=2,
    )
    db_session.add(
        DailyStat(
            guild_id=GUILD_ID,
            user_id=USER_ID,
            channel_id="3001",
            stat_date=START_DAY,
            message_count=1_000,
        )
    )
    await db_session.commit()
    dependencies = CoffeeMarketDependencies(
        xp_wallet=LEVEL_BOT_DEPENDENCIES.xp_wallet,
        level_sync=_FailingLevelSync(),
    )

    with pytest.raises(RuntimeError, match="cannot request level sync"):
        await purchase_beans(
            db_session,
            event_id="rollback-buy",
            guild_id=GUILD_ID,
            user_id=USER_ID,
            quantity=10,
            market_day=START_DAY,
            dependencies=dependencies,
        )
    await db_session.rollback()

    assert (await db_session.execute(select(CoffeeBeanLot))).scalars().all() == []
    assert (
        await db_session.execute(select(CoffeeMarketXpTransaction))
    ).scalars().all() == []
    levels = await get_user_lifetime_levels(
        db_session, GUILD_ID, USER_ID, include_live_voice=False
    )
    assert levels is not None
    assert levels.total.xp == 3_000
