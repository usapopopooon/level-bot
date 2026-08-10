"""カフェガチャのDB境界。抽選・消費・交換を原子的に確定する。"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    CafeGachaDraw,
    CafeGachaGuildConfig,
    CafeGachaRedemption,
    CafeGachaRedemptionItem,
    CafeGachaUserState,
)
from src.features.cafe_gacha.catalog import (
    CARDS,
    CARDS_BY_KEY,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
    CafeCard,
    select_card,
)
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user

TOKYO = ZoneInfo("Asia/Tokyo")
type DrawStatus = Literal[
    "drawn", "confirmation_required", "insufficient_xp", "hourly_limit", "conflict"
]
type RedemptionStatus = Literal["redeemed", "unavailable"]


@dataclass(frozen=True)
class DrawResult:
    status: DrawStatus
    draw: CafeGachaDraw | None
    wallet_before: Wallet
    wallet_after: Wallet


@dataclass(frozen=True)
class CollectionCard:
    card: CafeCard
    count: int
    redeemable_count: int


@dataclass(frozen=True)
class RedemptionResult:
    status: RedemptionStatus
    redemption: CafeGachaRedemption | None
    items: tuple[CafeGachaRedemptionItem, ...]


async def get_guild_config(
    session: AsyncSession, guild_id: str
) -> CafeGachaGuildConfig | None:
    return (
        await session.execute(
            select(CafeGachaGuildConfig).where(
                CafeGachaGuildConfig.guild_id == guild_id
            )
        )
    ).scalar_one_or_none()


async def save_guild_config(
    session: AsyncSession,
    *,
    guild_id: str,
    counter_channel_id: str,
    ledger_channel_id: str,
    panel_message_id: str | None,
) -> CafeGachaGuildConfig:
    row = await get_guild_config(session, guild_id)
    if row is None:
        row = CafeGachaGuildConfig(
            guild_id=guild_id,
            counter_channel_id=counter_channel_id,
            ledger_channel_id=ledger_channel_id,
            panel_message_id=panel_message_id,
        )
        session.add(row)
    else:
        row.counter_channel_id = counter_channel_id
        row.ledger_channel_id = ledger_channel_id
        row.panel_message_id = panel_message_id
    await session.commit()
    await session.refresh(row)
    return row


async def _locked_user_state(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> CafeGachaUserState:
    await session.execute(
        insert(CafeGachaUserState)
        .values(guild_id=guild_id, user_id=user_id, hourly_draw_count=0)
        .on_conflict_do_nothing(index_elements=["guild_id", "user_id"])
    )
    return (
        await session.execute(
            select(CafeGachaUserState)
            .where(
                CafeGachaUserState.guild_id == guild_id,
                CafeGachaUserState.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one()


async def draw_card(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    display_name: str,
    earned_xp: int,
    allow_paid: bool,
    today: date | None = None,
    now: datetime | None = None,
    random_value: int | None = None,
) -> DrawResult:
    """無料分または呼び出し元が許可した20 XPで、1枚を重複排除して引く。"""
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    existing = (
        await session.execute(
            select(CafeGachaDraw).where(CafeGachaDraw.event_id == event_id)
        )
    ).scalar_one_or_none()
    wallet = await wallet_for_user(
        session, guild_id=guild_id, user_id=user_id, total_xp=earned_xp
    )
    if existing is not None:
        if existing.guild_id != guild_id or existing.user_id != user_id:
            await session.rollback()
            return DrawResult("conflict", None, wallet, wallet)
        return DrawResult("drawn", existing, wallet, wallet)

    state = await _locked_user_state(session, guild_id=guild_id, user_id=user_id)
    if now is not None:
        local_now = now.astimezone(TOKYO)
    elif today is not None:
        local_now = datetime.combine(today, time.min, tzinfo=TOKYO)
    else:
        local_now = datetime.now(TOKYO)
    local_today = today or local_now.date()
    hour_started_at = local_now.replace(minute=0, second=0, microsecond=0).astimezone(
        UTC
    )
    if state.draw_count_hour_started_at != hour_started_at:
        state.draw_count_hour_started_at = hour_started_at
        state.hourly_draw_count = 0
    if state.hourly_draw_count >= MAX_HOURLY_DRAWS:
        await session.rollback()
        return DrawResult("hourly_limit", None, wallet, wallet)
    is_free = state.last_free_draw_on != local_today
    if not is_free and not allow_paid:
        await session.rollback()
        return DrawResult("confirmation_required", None, wallet, wallet)
    cost_xp = 0 if is_free else PAID_DRAW_COST_XP
    if wallet.available_xp < cost_xp:
        await session.rollback()
        return DrawResult("insufficient_xp", None, wallet, wallet)

    value = random_value if random_value is not None else secrets.randbelow(10_000)
    card = select_card(value)
    prior_count = int(
        (
            await session.execute(
                select(func.count(CafeGachaDraw.id)).where(
                    CafeGachaDraw.guild_id == guild_id,
                    CafeGachaDraw.user_id == user_id,
                    CafeGachaDraw.reward_key == card.key,
                )
            )
        ).scalar_one()
    )
    prior_redeemed_count = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(CafeGachaRedemptionItem.quantity), 0))
                .join(
                    CafeGachaRedemption,
                    CafeGachaRedemption.id == CafeGachaRedemptionItem.redemption_id,
                )
                .where(
                    CafeGachaRedemption.guild_id == guild_id,
                    CafeGachaRedemption.user_id == user_id,
                    CafeGachaRedemptionItem.reward_key == card.key,
                )
            )
        ).scalar_one()
    )
    prior_collected_count = int(
        (
            await session.execute(
                select(func.count(func.distinct(CafeGachaDraw.reward_key))).where(
                    CafeGachaDraw.guild_id == guild_id,
                    CafeGachaDraw.user_id == user_id,
                )
            )
        ).scalar_one()
    )
    draw = CafeGachaDraw(
        event_id=event_id,
        guild_id=guild_id,
        user_id=user_id,
        display_name=display_name.strip()[:80] or user_id,
        draw_type="free" if is_free else "paid",
        cost_xp=cost_xp,
        reward_xp=card.draw_reward_xp,
        reward_key=card.key,
        reward_name=card.name,
        reward_description=card.description,
        rarity=card.rarity,
        image_filename=card.image_filename,
        exchange_xp=card.exchange_xp,
        was_duplicate=prior_count > 0,
        owned_count=prior_count - prior_redeemed_count + 1,
        collected_count=prior_collected_count + (1 if prior_count == 0 else 0),
    )
    session.add(draw)
    if is_free:
        state.last_free_draw_on = local_today
    state.hourly_draw_count += 1
    await session.commit()
    await session.refresh(draw)
    wallet_after = Wallet(
        wallet.total_xp + draw.reward_xp,
        wallet.spent_xp + cost_xp,
    )
    return DrawResult("drawn", draw, wallet, wallet_after)


async def list_collection(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> tuple[CollectionCard, ...]:
    draw_rows = (
        await session.execute(
            select(CafeGachaDraw.reward_key, func.count(CafeGachaDraw.id))
            .where(
                CafeGachaDraw.guild_id == guild_id,
                CafeGachaDraw.user_id == user_id,
            )
            .group_by(CafeGachaDraw.reward_key)
        )
    ).all()
    redeemed_rows = (
        await session.execute(
            select(
                CafeGachaRedemptionItem.reward_key,
                func.sum(CafeGachaRedemptionItem.quantity),
            )
            .join(
                CafeGachaRedemption,
                CafeGachaRedemption.id == CafeGachaRedemptionItem.redemption_id,
            )
            .where(
                CafeGachaRedemption.guild_id == guild_id,
                CafeGachaRedemption.user_id == user_id,
            )
            .group_by(CafeGachaRedemptionItem.reward_key)
        )
    ).all()
    drawn = {str(key): int(count) for key, count in draw_rows}
    redeemed = {str(key): int(count) for key, count in redeemed_rows}
    return tuple(
        CollectionCard(
            card=card,
            count=max(0, drawn.get(card.key, 0) - redeemed.get(card.key, 0)),
            redeemable_count=max(
                0, drawn.get(card.key, 0) - redeemed.get(card.key, 0) - 1
            ),
        )
        for card in CARDS
    )


async def favorite_card(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> CafeCard | None:
    state = (
        await session.execute(
            select(CafeGachaUserState).where(
                CafeGachaUserState.guild_id == guild_id,
                CafeGachaUserState.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if state is None or state.favorite_reward_key is None:
        return None
    return CARDS_BY_KEY.get(state.favorite_reward_key)


async def set_favorite_card(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    reward_key: str,
) -> CafeCard | None:
    card = CARDS_BY_KEY.get(reward_key)
    if card is None:
        return None
    state = await _locked_user_state(session, guild_id=guild_id, user_id=user_id)
    collection = {
        item.card.key: item
        for item in await list_collection(session, guild_id=guild_id, user_id=user_id)
    }
    if collection[reward_key].count <= 0:
        await session.rollback()
        return None
    state.favorite_reward_key = reward_key
    await session.commit()
    return card


async def redeem_cards(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    display_name: str,
    quantities: dict[str, int],
) -> RedemptionResult:
    """指定された重複だけを交換する。各カードの最初の1枚は常に保護する。"""
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    requested = {key: qty for key, qty in quantities.items() if qty > 0}
    existing = (
        await session.execute(
            select(CafeGachaRedemption).where(CafeGachaRedemption.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing_items = (
            (
                await session.execute(
                    select(CafeGachaRedemptionItem).where(
                        CafeGachaRedemptionItem.redemption_id == existing.id
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_quantities = {
            item.reward_key: item.quantity for item in existing_items
        }
        if (
            existing.guild_id != guild_id
            or existing.user_id != user_id
            or existing_quantities != requested
        ):
            await session.rollback()
            return RedemptionResult("unavailable", None, ())
        return RedemptionResult("redeemed", existing, tuple(existing_items))

    if not requested or any(key not in CARDS_BY_KEY for key in requested):
        await session.rollback()
        return RedemptionResult("unavailable", None, ())
    collection = {
        item.card.key: item
        for item in await list_collection(session, guild_id=guild_id, user_id=user_id)
    }
    if any(
        collection[key].redeemable_count < quantity
        for key, quantity in requested.items()
    ):
        await session.rollback()
        return RedemptionResult("unavailable", None, ())

    reward_xp = sum(
        CARDS_BY_KEY[key].exchange_xp * quantity for key, quantity in requested.items()
    )
    redemption = CafeGachaRedemption(
        event_id=event_id,
        guild_id=guild_id,
        user_id=user_id,
        display_name=display_name.strip()[:80] or user_id,
        reward_xp=reward_xp,
    )
    session.add(redemption)
    await session.flush()
    items: list[CafeGachaRedemptionItem] = []
    for key, quantity in requested.items():
        card = CARDS_BY_KEY[key]
        item = CafeGachaRedemptionItem(
            redemption_id=redemption.id,
            reward_key=key,
            reward_name=card.name,
            rarity=card.rarity,
            quantity=quantity,
            xp_per_card=card.exchange_xp,
            reward_xp=card.exchange_xp * quantity,
        )
        session.add(item)
        items.append(item)
    await session.commit()
    await session.refresh(redemption)
    return RedemptionResult("redeemed", redemption, tuple(items))
