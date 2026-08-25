"""コーヒー豆相場の永続化と取引ユースケース。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    CoffeeBeanLot,
    CoffeeMarketGuildConfig,
    CoffeeMarketQuote,
    CoffeeMarketSale,
)
from src.features.coffee_market.contracts import (
    AlreadyPurchasedToday,
    IdempotencyConflict,
    InsufficientBeans,
    InsufficientXp,
    InvalidQuantity,
    MarketQuote,
    NoSellableBeans,
    PanelKind,
    PublicTradeEntry,
    PurchaseResult,
    RankingEntry,
    SaleResult,
    TradeHistoryEntry,
    UserPosition,
)
from src.features.coffee_market.domain import (
    LOT_LIFETIME_DAYS,
    MAX_DAILY_QUANTITY,
    MAX_SELL_QUANTITY,
    QuoteSpec,
    quote_for,
)
from src.features.coffee_market.ports import (
    CoffeeMarketDependencies,
    XpMovementConflict,
)


def _quote_view(row: CoffeeMarketQuote) -> MarketQuote:
    return MarketQuote(
        market_day=row.market_day,
        buy_price_xp=row.buy_price_xp,
        sell_price_xp=row.sell_price_xp,
        previous_sell_price_xp=row.previous_sell_price_xp,
        news=row.news,
    )


async def _lock_inventory(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:inventory_key))"),
        {"inventory_key": f"coffee-market:{guild_id}:{user_id}"},
    )


async def ensure_quote(
    session: AsyncSession,
    *,
    guild_id: str,
    market_day: date,
) -> CoffeeMarketQuote:
    spec: QuoteSpec = quote_for(guild_id, market_day)
    previous_sell_price = (
        await session.execute(
            select(CoffeeMarketQuote.sell_price_xp).where(
                CoffeeMarketQuote.guild_id == guild_id,
                CoffeeMarketQuote.market_day == market_day - timedelta(days=1),
            )
        )
    ).scalar_one_or_none()
    await session.execute(
        insert(CoffeeMarketQuote)
        .values(
            guild_id=guild_id,
            market_day=market_day,
            buy_price_xp=spec.buy_price_xp,
            sell_price_xp=spec.sell_price_xp,
            previous_sell_price_xp=(
                spec.previous_sell_price_xp
                if previous_sell_price is None
                else int(previous_sell_price)
            ),
            news=spec.news,
        )
        .on_conflict_do_nothing(index_elements=["guild_id", "market_day"])
    )
    return (
        await session.execute(
            select(CoffeeMarketQuote).where(
                CoffeeMarketQuote.guild_id == guild_id,
                CoffeeMarketQuote.market_day == market_day,
            )
        )
    ).scalar_one()


async def get_quote(
    session: AsyncSession,
    *,
    guild_id: str,
    market_day: date,
) -> MarketQuote:
    row = await ensure_quote(session, guild_id=guild_id, market_day=market_day)
    await session.commit()
    return _quote_view(row)


async def save_panel_placement(
    session: AsyncSession,
    *,
    guild_id: str,
    panel_kind: PanelKind,
    channel_id: str,
    message_id: str,
) -> CoffeeMarketGuildConfig:
    columns = {
        "market": ("panel_channel_id", "panel_message_id"),
        "ledger": ("ledger_channel_id", "ledger_message_id"),
        "ranking": ("ranking_channel_id", "ranking_message_id"),
    }
    channel_column, message_column = columns[panel_kind]
    placement = {
        channel_column: channel_id,
        message_column: message_id,
    }
    await session.execute(
        insert(CoffeeMarketGuildConfig)
        .values(
            guild_id=guild_id,
            **placement,
        )
        .on_conflict_do_update(
            index_elements=["guild_id"],
            set_={
                **placement,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    await session.commit()
    return (
        await session.execute(
            select(CoffeeMarketGuildConfig).where(
                CoffeeMarketGuildConfig.guild_id == guild_id
            )
        )
    ).scalar_one()


async def get_guild_config(
    session: AsyncSession, *, guild_id: str
) -> CoffeeMarketGuildConfig | None:
    return (
        await session.execute(
            select(CoffeeMarketGuildConfig).where(
                CoffeeMarketGuildConfig.guild_id == guild_id
            )
        )
    ).scalar_one_or_none()


async def list_guild_configs(
    session: AsyncSession,
) -> tuple[CoffeeMarketGuildConfig, ...]:
    rows = await session.execute(
        select(CoffeeMarketGuildConfig).order_by(CoffeeMarketGuildConfig.id.asc())
    )
    return tuple(rows.scalars().all())


def _validate_purchase_quantity(quantity: int) -> None:
    if not 1 <= quantity <= MAX_DAILY_QUANTITY:
        raise InvalidQuantity(maximum=MAX_DAILY_QUANTITY)


def _validate_sell_quantity(quantity: int) -> None:
    if not 1 <= quantity <= MAX_SELL_QUANTITY:
        raise InvalidQuantity(maximum=MAX_SELL_QUANTITY)


async def _wallet_after_existing_purchase(
    session: AsyncSession,
    *,
    dependencies: CoffeeMarketDependencies,
    row: CoffeeBeanLot,
) -> PurchaseResult:
    wallet = await dependencies.xp_wallet.get_balance(
        session, guild_id=row.guild_id, user_id=row.user_id
    )
    return PurchaseResult(
        status="already_completed",
        market_day=row.purchased_on,
        quantity=row.quantity,
        unit_price_xp=row.buy_price_xp,
        cost_xp=row.cost_xp,
        sellable_on=row.sellable_on,
        expires_on=row.expires_on,
        available_xp_after=wallet.available_xp,
    )


async def purchase_beans(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    quantity: int,
    market_day: date,
    dependencies: CoffeeMarketDependencies,
) -> PurchaseResult:
    _validate_purchase_quantity(quantity)
    await _lock_inventory(session, guild_id=guild_id, user_id=user_id)

    existing = (
        await session.execute(
            select(CoffeeBeanLot).where(CoffeeBeanLot.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.guild_id != guild_id
            or existing.user_id != user_id
            or existing.quantity != quantity
        ):
            raise IdempotencyConflict
        return await _wallet_after_existing_purchase(
            session, dependencies=dependencies, row=existing
        )

    purchased_today = (
        await session.execute(
            select(CoffeeBeanLot.id).where(
                CoffeeBeanLot.guild_id == guild_id,
                CoffeeBeanLot.user_id == user_id,
                CoffeeBeanLot.purchased_on == market_day,
            )
        )
    ).scalar_one_or_none()
    if purchased_today is not None:
        raise AlreadyPurchasedToday

    quote = await ensure_quote(session, guild_id=guild_id, market_day=market_day)
    cost_xp = quote.buy_price_xp * quantity
    try:
        movement = await dependencies.xp_wallet.debit(
            session,
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            amount_xp=cost_xp,
        )
    except XpMovementConflict as error:
        raise IdempotencyConflict from error
    if movement.status == "insufficient":
        raise InsufficientXp(
            required_xp=cost_xp,
            available_xp=movement.available_xp_after,
        )
    sellable_on = market_day + timedelta(days=1)
    expires_on = market_day + timedelta(days=LOT_LIFETIME_DAYS)
    session.add(
        CoffeeBeanLot(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            purchased_on=market_day,
            sellable_on=sellable_on,
            expires_on=expires_on,
            quantity=quantity,
            remaining_quantity=quantity,
            buy_price_xp=quote.buy_price_xp,
            cost_xp=cost_xp,
        )
    )
    await dependencies.level_sync.request(session, guild_id=guild_id)
    await session.commit()
    return PurchaseResult(
        status="completed",
        market_day=market_day,
        quantity=quantity,
        unit_price_xp=quote.buy_price_xp,
        cost_xp=cost_xp,
        sellable_on=sellable_on,
        expires_on=expires_on,
        available_xp_after=movement.available_xp_after,
    )


async def _existing_sale_result(
    session: AsyncSession,
    *,
    row: CoffeeMarketSale,
    requested_quantity: int | None,
    dependencies: CoffeeMarketDependencies,
) -> SaleResult:
    if requested_quantity is not None and row.quantity != requested_quantity:
        raise IdempotencyConflict
    wallet = await dependencies.xp_wallet.get_balance(
        session, guild_id=row.guild_id, user_id=row.user_id
    )
    return SaleResult(
        status="already_completed",
        market_day=row.market_day,
        sale_kind=row.sale_kind,
        quantity=row.quantity,
        unit_price_xp=row.sell_price_xp,
        payout_xp=row.payout_xp,
        cost_basis_xp=row.cost_basis_xp,
        available_xp_after=wallet.available_xp,
    )


async def sell_beans(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    quantity: int | None,
    market_day: date,
    dependencies: CoffeeMarketDependencies,
) -> SaleResult:
    if quantity is not None:
        _validate_sell_quantity(quantity)
    await _lock_inventory(session, guild_id=guild_id, user_id=user_id)

    existing = (
        await session.execute(
            select(CoffeeMarketSale).where(CoffeeMarketSale.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.guild_id != guild_id or existing.user_id != user_id:
            raise IdempotencyConflict
        return await _existing_sale_result(
            session,
            row=existing,
            requested_quantity=quantity,
            dependencies=dependencies,
        )

    quote = await ensure_quote(session, guild_id=guild_id, market_day=market_day)
    lots = tuple(
        (
            await session.execute(
                select(CoffeeBeanLot)
                .where(
                    CoffeeBeanLot.guild_id == guild_id,
                    CoffeeBeanLot.user_id == user_id,
                    CoffeeBeanLot.remaining_quantity > 0,
                    CoffeeBeanLot.sellable_on <= market_day,
                    CoffeeBeanLot.expires_on > market_day,
                )
                .order_by(CoffeeBeanLot.expires_on.asc(), CoffeeBeanLot.id.asc())
                .with_for_update()
            )
        ).scalars()
    )
    sellable = sum(row.remaining_quantity for row in lots)
    if sellable <= 0:
        raise NoSellableBeans
    sell_quantity = sellable if quantity is None else quantity
    if sell_quantity > sellable:
        raise InsufficientBeans(requested=sell_quantity, available=sellable)

    remaining_to_sell = sell_quantity
    cost_basis_xp = 0
    for lot in lots:
        consumed = min(lot.remaining_quantity, remaining_to_sell)
        lot.remaining_quantity -= consumed
        cost_basis_xp += consumed * lot.buy_price_xp
        remaining_to_sell -= consumed
        if remaining_to_sell == 0:
            break

    payout_xp = sell_quantity * quote.sell_price_xp
    try:
        movement = await dependencies.xp_wallet.credit(
            session,
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            amount_xp=payout_xp,
        )
    except XpMovementConflict as error:
        raise IdempotencyConflict from error
    session.add(
        CoffeeMarketSale(
            event_id=event_id,
            guild_id=guild_id,
            user_id=user_id,
            market_day=market_day,
            sale_kind="manual",
            quantity=sell_quantity,
            sell_price_xp=quote.sell_price_xp,
            payout_xp=payout_xp,
            cost_basis_xp=cost_basis_xp,
        )
    )
    await dependencies.level_sync.request(session, guild_id=guild_id)
    await session.commit()
    return SaleResult(
        status="completed",
        market_day=market_day,
        sale_kind="manual",
        quantity=sell_quantity,
        unit_price_xp=quote.sell_price_xp,
        payout_xp=payout_xp,
        cost_basis_xp=cost_basis_xp,
        available_xp_after=movement.available_xp_after,
    )


async def settle_expired_lots(
    session: AsyncSession,
    *,
    guild_id: str,
    market_day: date,
    dependencies: CoffeeMarketDependencies,
) -> tuple[SaleResult, ...]:
    """期限に達した全ロットを当日の売値で一度だけ強制売却する。"""
    expiring_user_ids = tuple(
        (
            await session.execute(
                select(CoffeeBeanLot.user_id)
                .where(
                    CoffeeBeanLot.guild_id == guild_id,
                    CoffeeBeanLot.remaining_quantity > 0,
                    CoffeeBeanLot.expires_on <= market_day,
                )
                .group_by(CoffeeBeanLot.user_id)
                .order_by(CoffeeBeanLot.user_id.asc())
            )
        ).scalars()
    )
    for user_id in expiring_user_ids:
        await _lock_inventory(session, guild_id=guild_id, user_id=user_id)
    lots = tuple(
        (
            await session.execute(
                select(CoffeeBeanLot)
                .where(
                    CoffeeBeanLot.guild_id == guild_id,
                    CoffeeBeanLot.remaining_quantity > 0,
                    CoffeeBeanLot.expires_on <= market_day,
                )
                .order_by(CoffeeBeanLot.user_id.asc(), CoffeeBeanLot.id.asc())
                .with_for_update()
            )
        ).scalars()
    )
    results: list[SaleResult] = []
    for lot in lots:
        expiry_quote = await ensure_quote(
            session, guild_id=guild_id, market_day=lot.expires_on
        )
        quantity = lot.remaining_quantity
        payout_xp = quantity * expiry_quote.sell_price_xp
        cost_basis_xp = quantity * lot.buy_price_xp
        event_id = f"coffee-expiry:{lot.id}:{lot.expires_on.isoformat()}"
        try:
            movement = await dependencies.xp_wallet.credit(
                session,
                event_id=event_id,
                guild_id=guild_id,
                user_id=lot.user_id,
                amount_xp=payout_xp,
            )
        except XpMovementConflict as error:
            raise IdempotencyConflict from error
        lot.remaining_quantity = 0
        session.add(
            CoffeeMarketSale(
                event_id=event_id,
                guild_id=guild_id,
                user_id=lot.user_id,
                market_day=lot.expires_on,
                sale_kind="expired",
                quantity=quantity,
                sell_price_xp=expiry_quote.sell_price_xp,
                payout_xp=payout_xp,
                cost_basis_xp=cost_basis_xp,
            )
        )
        results.append(
            SaleResult(
                status="completed",
                market_day=lot.expires_on,
                sale_kind="expired",
                quantity=quantity,
                unit_price_xp=expiry_quote.sell_price_xp,
                payout_xp=payout_xp,
                cost_basis_xp=cost_basis_xp,
                available_xp_after=movement.available_xp_after,
            )
        )
    if results:
        await dependencies.level_sync.request(session, guild_id=guild_id)
    await session.commit()
    return tuple(results)


async def get_user_position(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    market_day: date,
    dependencies: CoffeeMarketDependencies,
) -> tuple[MarketQuote, UserPosition]:
    quote = await ensure_quote(session, guild_id=guild_id, market_day=market_day)
    wallet = await dependencies.xp_wallet.get_balance(
        session, guild_id=guild_id, user_id=user_id
    )
    lots = tuple(
        (
            await session.execute(
                select(CoffeeBeanLot).where(
                    CoffeeBeanLot.guild_id == guild_id,
                    CoffeeBeanLot.user_id == user_id,
                    CoffeeBeanLot.remaining_quantity > 0,
                    CoffeeBeanLot.expires_on > market_day,
                )
            )
        ).scalars()
    )
    quantity = sum(row.remaining_quantity for row in lots)
    cost_basis = sum(row.remaining_quantity * row.buy_price_xp for row in lots)
    average_buy_price = round(cost_basis / quantity) if quantity else 0
    sellable_quantity = sum(
        row.remaining_quantity for row in lots if row.sellable_on <= market_day
    )
    evaluation = quantity * quote.sell_price_xp
    await session.commit()
    return _quote_view(quote), UserPosition(
        quantity=quantity,
        sellable_quantity=sellable_quantity,
        average_buy_price_xp=average_buy_price,
        evaluation_xp=evaluation,
        unrealized_profit_xp=evaluation - cost_basis,
        earliest_expiry=min((row.expires_on for row in lots), default=None),
        purchased_today=any(row.purchased_on == market_day for row in lots),
        available_xp=wallet.available_xp,
    )


async def list_user_history(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    limit: int = 10,
) -> tuple[TradeHistoryEntry, ...]:
    lots = (
        await session.execute(
            select(CoffeeBeanLot)
            .where(
                CoffeeBeanLot.guild_id == guild_id,
                CoffeeBeanLot.user_id == user_id,
            )
            .order_by(CoffeeBeanLot.created_at.desc(), CoffeeBeanLot.id.desc())
            .limit(limit)
        )
    ).scalars()
    sales = (
        await session.execute(
            select(CoffeeMarketSale)
            .where(
                CoffeeMarketSale.guild_id == guild_id,
                CoffeeMarketSale.user_id == user_id,
            )
            .order_by(CoffeeMarketSale.created_at.desc(), CoffeeMarketSale.id.desc())
            .limit(limit)
        )
    ).scalars()
    entries = [
        TradeHistoryEntry(
            kind="buy",
            market_day=row.purchased_on,
            quantity=row.quantity,
            unit_price_xp=row.buy_price_xp,
            total_xp=row.cost_xp,
            profit_xp=None,
            created_at=row.created_at,
            record_id=row.id,
        )
        for row in lots
    ]
    entries.extend(
        TradeHistoryEntry(
            kind=row.sale_kind,
            market_day=row.market_day,
            quantity=row.quantity,
            unit_price_xp=row.sell_price_xp,
            total_xp=row.payout_xp,
            profit_xp=row.payout_xp - row.cost_basis_xp,
            created_at=row.created_at,
            record_id=row.id,
        )
        for row in sales
    )
    entries.sort(
        key=lambda row: (row.created_at, row.kind != "buy", row.record_id),
        reverse=True,
    )
    return tuple(entries[:limit])


async def list_public_ledger(
    session: AsyncSession,
    *,
    guild_id: str,
    limit: int = 15,
) -> tuple[PublicTradeEntry, ...]:
    lots = (
        await session.execute(
            select(CoffeeBeanLot)
            .where(CoffeeBeanLot.guild_id == guild_id)
            .order_by(CoffeeBeanLot.created_at.desc(), CoffeeBeanLot.id.desc())
            .limit(limit)
        )
    ).scalars()
    sales = (
        await session.execute(
            select(CoffeeMarketSale)
            .where(CoffeeMarketSale.guild_id == guild_id)
            .order_by(CoffeeMarketSale.created_at.desc(), CoffeeMarketSale.id.desc())
            .limit(limit)
        )
    ).scalars()
    entries = [
        PublicTradeEntry(
            user_id=row.user_id,
            kind="buy",
            market_day=row.purchased_on,
            quantity=row.quantity,
            unit_price_xp=row.buy_price_xp,
            total_xp=row.cost_xp,
            profit_xp=None,
            created_at=row.created_at,
            record_id=row.id,
        )
        for row in lots
    ]
    entries.extend(
        PublicTradeEntry(
            user_id=row.user_id,
            kind=row.sale_kind,
            market_day=row.market_day,
            quantity=row.quantity,
            unit_price_xp=row.sell_price_xp,
            total_xp=row.payout_xp,
            profit_xp=row.payout_xp - row.cost_basis_xp,
            created_at=row.created_at,
            record_id=row.id,
        )
        for row in sales
    )
    entries.sort(
        key=lambda row: (row.created_at, row.kind != "buy", row.record_id),
        reverse=True,
    )
    return tuple(entries[:limit])


async def get_public_activity_version(
    session: AsyncSession, *, guild_id: str
) -> tuple[int, int]:
    latest_lot_id = (
        await session.execute(
            select(func.coalesce(func.max(CoffeeBeanLot.id), 0)).where(
                CoffeeBeanLot.guild_id == guild_id
            )
        )
    ).scalar_one()
    latest_sale_id = (
        await session.execute(
            select(func.coalesce(func.max(CoffeeMarketSale.id), 0)).where(
                CoffeeMarketSale.guild_id == guild_id
            )
        )
    ).scalar_one()
    return int(latest_lot_id), int(latest_sale_id)


async def weekly_ranking(
    session: AsyncSession,
    *,
    guild_id: str,
    market_day: date,
    limit: int = 10,
) -> tuple[RankingEntry, ...]:
    week_start = market_day - timedelta(days=market_day.weekday())
    rows = await session.execute(
        select(
            CoffeeMarketSale.user_id,
            func.sum(CoffeeMarketSale.payout_xp),
            func.sum(CoffeeMarketSale.cost_basis_xp),
        )
        .where(
            CoffeeMarketSale.guild_id == guild_id,
            CoffeeMarketSale.market_day >= week_start,
            CoffeeMarketSale.market_day <= market_day,
        )
        .group_by(CoffeeMarketSale.user_id)
        .order_by(
            (
                func.sum(CoffeeMarketSale.payout_xp)
                - func.sum(CoffeeMarketSale.cost_basis_xp)
            ).desc(),
            CoffeeMarketSale.user_id.asc(),
        )
        .limit(limit)
    )
    return tuple(
        RankingEntry(
            user_id=str(user_id),
            payout_xp=int(payout_xp),
            cost_basis_xp=int(cost_basis_xp),
            profit_xp=int(payout_xp) - int(cost_basis_xp),
        )
        for user_id, payout_xp, cost_basis_xp in rows
    )
