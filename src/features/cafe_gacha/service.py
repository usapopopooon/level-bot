"""カフェガチャのDB境界。抽選・消費・交換を原子的に確定する。"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    CafeGachaCosmeticUnlock,
    CafeGachaDraw,
    CafeGachaGuildConfig,
    CafeGachaMedalRedemption,
    CafeGachaMedalRedemptionItem,
    CafeGachaRedemption,
    CafeGachaRedemptionItem,
    CafeGachaUserState,
)
from src.features.cafe_gacha.catalog import (
    CARDS,
    CARDS_BY_KEY,
    ENDGAME_PITY_DUPLICATE_DRAWS,
    ENDGAME_PITY_MIN_COLLECTED,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
    CafeCard,
    select_card_for_collection,
    select_unowned_card,
)
from src.features.cafe_gacha.medals import (
    COSMETICS_BY_KEY,
    MEDALS_BY_RARITY,
    CafeCosmetic,
)
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user

TOKYO = ZoneInfo("Asia/Tokyo")
type DrawStatus = Literal[
    "drawn",
    "confirmation_required",
    "insufficient_xp",
    "hourly_limit",
    "conflict",
]
type RedemptionStatus = Literal["redeemed", "unavailable"]


@dataclass(frozen=True)
class DrawResult:
    status: DrawStatus
    draw: CafeGachaDraw | None
    wallet_before: Wallet
    wallet_after: Wallet


@dataclass(frozen=True)
class DrawBatchResult:
    status: DrawStatus
    draws: tuple[CafeGachaDraw, ...]
    wallet_before: Wallet
    wallet_after: Wallet


@dataclass(frozen=True)
class DrawAvailability:
    wallet: Wallet
    has_free_draw: bool
    hourly_remaining: int

    @property
    def available_count(self) -> int:
        return self.hourly_remaining

    def cost_for(self, count: int) -> int:
        free_count = 1 if self.has_free_draw and count > 0 else 0
        return max(0, count - free_count) * PAID_DRAW_COST_XP


@dataclass(frozen=True)
class CollectionCard:
    card: CafeCard
    count: int
    redeemable_count: int
    lifetime_count: int = 0


@dataclass(frozen=True)
class RedemptionResult:
    status: RedemptionStatus
    redemption: CafeGachaRedemption | None
    items: tuple[CafeGachaRedemptionItem, ...]


@dataclass(frozen=True)
class MedalRedemptionResult:
    status: RedemptionStatus
    redemption: CafeGachaMedalRedemption | None
    items: tuple[CafeGachaMedalRedemptionItem, ...]


@dataclass(frozen=True)
class CosmeticResult:
    status: Literal["equipped", "insufficient", "unavailable"]
    cosmetic: CafeCosmetic | None
    balance: int


@dataclass(frozen=True)
class GuildAnalytics:
    draws_today: int
    draws_7d: int
    total_draws: int
    active_today: int
    active_7d: int
    total_users: int
    new_7d: int
    duplicate_7d: int
    rarity_7d: tuple[tuple[str, int], ...]
    spent_xp_7d: int
    draw_reward_xp_7d: int
    redemption_xp_7d: int
    completed_users: int


async def guild_analytics(
    session: AsyncSession,
    *,
    guild_id: str,
    now: datetime | None = None,
) -> GuildAnalytics:
    """管理画面用に、JSTの日界を使った集計を返す。"""
    local_now = (now or datetime.now(TOKYO)).astimezone(TOKYO)
    today_started_at = datetime.combine(
        local_now.date(), time.min, tzinfo=TOKYO
    ).astimezone(UTC)
    week_started_at = today_started_at - timedelta(days=6)

    async def draw_summary(since: datetime | None) -> tuple[int, int, int, int, int]:
        filters = [CafeGachaDraw.guild_id == guild_id]
        if since is not None:
            filters.append(CafeGachaDraw.created_at >= since)
        row = (
            await session.execute(
                select(
                    func.count(CafeGachaDraw.id),
                    func.count(func.distinct(CafeGachaDraw.user_id)),
                    func.coalesce(func.sum(CafeGachaDraw.cost_xp), 0),
                    func.coalesce(func.sum(CafeGachaDraw.reward_xp), 0),
                    func.count(CafeGachaDraw.id).filter(
                        CafeGachaDraw.was_duplicate.is_(False)
                    ),
                ).where(*filters)
            )
        ).one()
        return (
            int(row[0]),
            int(row[1]),
            int(row[2]),
            int(row[3]),
            int(row[4]),
        )

    today = await draw_summary(today_started_at)
    week = await draw_summary(week_started_at)
    total = await draw_summary(None)
    rarity_rows = (
        await session.execute(
            select(CafeGachaDraw.rarity, func.count(CafeGachaDraw.id))
            .where(
                CafeGachaDraw.guild_id == guild_id,
                CafeGachaDraw.created_at >= week_started_at,
            )
            .group_by(CafeGachaDraw.rarity)
        )
    ).all()
    redemption_xp = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(CafeGachaRedemption.reward_xp), 0)).where(
                    CafeGachaRedemption.guild_id == guild_id,
                    CafeGachaRedemption.created_at >= week_started_at,
                )
            )
        ).scalar_one()
    )
    completed = (
        select(CafeGachaDraw.user_id)
        .where(CafeGachaDraw.guild_id == guild_id)
        .group_by(CafeGachaDraw.user_id)
        .having(func.count(func.distinct(CafeGachaDraw.reward_key)) >= len(CARDS))
        .subquery()
    )
    completed_users = int(
        (
            await session.execute(select(func.count()).select_from(completed))
        ).scalar_one()
    )
    return GuildAnalytics(
        draws_today=today[0],
        draws_7d=week[0],
        total_draws=total[0],
        active_today=today[1],
        active_7d=week[1],
        total_users=total[1],
        new_7d=week[4],
        duplicate_7d=week[0] - week[4],
        rarity_7d=tuple(sorted((str(key), int(count)) for key, count in rarity_rows)),
        spent_xp_7d=week[2],
        draw_reward_xp_7d=week[3],
        redemption_xp_7d=redemption_xp,
        completed_users=completed_users,
    )


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


def _local_draw_time(now: datetime | None = None) -> datetime:
    return now.astimezone(TOKYO) if now is not None else datetime.now(TOKYO)


async def draw_availability(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    earned_xp: int,
    now: datetime | None = None,
) -> DrawAvailability:
    """現在の無料枠・時間枠とウォレットを表示用に返す。"""
    local_now = _local_draw_time(now)
    local_today = local_now.date()
    hour_started_at = local_now.replace(minute=0, second=0, microsecond=0).astimezone(
        UTC
    )
    state = (
        await session.execute(
            select(CafeGachaUserState).where(
                CafeGachaUserState.guild_id == guild_id,
                CafeGachaUserState.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    is_current_day = state is not None and state.last_free_draw_on == local_today
    hourly_used = (
        state.hourly_draw_count
        if state is not None and state.draw_count_hour_started_at == hour_started_at
        else 0
    )
    wallet = await wallet_for_user(
        session, guild_id=guild_id, user_id=user_id, total_xp=earned_xp
    )
    return DrawAvailability(
        wallet=wallet,
        has_free_draw=not is_current_day,
        hourly_remaining=max(0, MAX_HOURLY_DRAWS - hourly_used),
    )


async def draw_card(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    display_name: str,
    earned_xp: int,
    allow_paid: bool,
    expected_cost_xp: int | None = None,
    today: date | None = None,
    now: datetime | None = None,
    random_value: int | None = None,
) -> DrawResult:
    """無料分または呼び出し元が許可した20 XPで、1枚を重複排除して引く。"""
    result = await draw_cards(
        session,
        event_id=event_id,
        guild_id=guild_id,
        user_id=user_id,
        display_name=display_name,
        earned_xp=earned_xp,
        count=1,
        allow_paid=allow_paid,
        expected_cost_xp=expected_cost_xp,
        today=today,
        now=now,
        random_values=None if random_value is None else (random_value,),
    )
    return DrawResult(
        result.status,
        result.draws[0] if result.draws else None,
        result.wallet_before,
        result.wallet_after,
    )


async def draw_cards(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    display_name: str,
    earned_xp: int,
    count: int,
    allow_paid: bool = True,
    expected_cost_xp: int | None = None,
    today: date | None = None,
    now: datetime | None = None,
    random_values: Sequence[int] | None = None,
) -> DrawBatchResult:
    """1〜10枚を一つの操作として原子的かつ冪等に抽選する。"""
    if not 1 <= count <= MAX_HOURLY_DRAWS:
        msg = f"count must be between 1 and {MAX_HOURLY_DRAWS}"
        raise ValueError(msg)
    if not event_id or len(event_id) > 64:
        raise ValueError("event_id must contain between 1 and 64 characters")
    if random_values is not None and len(random_values) != count:
        raise ValueError("random_values length must match count")

    draw_event_ids = tuple(
        event_id if count == 1 else f"{event_id}:{position}"
        for position in range(1, count + 1)
    )
    if any(len(draw_event_id) > 64 for draw_event_id in draw_event_ids):
        raise ValueError("derived draw event_id exceeds 64 characters")

    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    existing_batch = await session.execute(
        select(CafeGachaDraw)
        .where(CafeGachaDraw.batch_id == event_id)
        .order_by(CafeGachaDraw.batch_position.asc())
    )
    existing_draws = tuple(existing_batch.scalars().all())
    wallet = await wallet_for_user(
        session, guild_id=guild_id, user_id=user_id, total_xp=earned_xp
    )
    if existing_draws:
        valid_retry = len(existing_draws) == count and all(
            draw.guild_id == guild_id
            and draw.user_id == user_id
            and draw.batch_position == position
            and draw.event_id == draw_event_ids[position - 1]
            for position, draw in enumerate(existing_draws, start=1)
        )
        if not valid_retry:
            await session.rollback()
            return DrawBatchResult("conflict", (), wallet, wallet)
        return DrawBatchResult("drawn", existing_draws, wallet, wallet)

    event_collision = (
        await session.execute(
            select(CafeGachaDraw.id).where(CafeGachaDraw.event_id.in_(draw_event_ids))
        )
    ).first()
    if event_collision is not None:
        await session.rollback()
        return DrawBatchResult("conflict", (), wallet, wallet)

    state = await _locked_user_state(session, guild_id=guild_id, user_id=user_id)
    if now is not None:
        local_now = _local_draw_time(now)
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
    if state.hourly_draw_count + count > MAX_HOURLY_DRAWS:
        await session.rollback()
        return DrawBatchResult("hourly_limit", (), wallet, wallet)
    has_free_draw = state.last_free_draw_on != local_today
    paid_draw_count = count - (1 if has_free_draw else 0)
    actual_cost_xp = paid_draw_count * PAID_DRAW_COST_XP
    if expected_cost_xp is not None and expected_cost_xp != actual_cost_xp:
        await session.rollback()
        return DrawBatchResult("confirmation_required", (), wallet, wallet)
    if paid_draw_count > 0 and not allow_paid:
        await session.rollback()
        return DrawBatchResult("confirmation_required", (), wallet, wallet)

    drawn_rows = (
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
    medal_redeemed_rows = (
        await session.execute(
            select(
                CafeGachaMedalRedemptionItem.reward_key,
                func.sum(CafeGachaMedalRedemptionItem.quantity),
            )
            .join(
                CafeGachaMedalRedemption,
                CafeGachaMedalRedemption.id
                == CafeGachaMedalRedemptionItem.redemption_id,
            )
            .where(
                CafeGachaMedalRedemption.guild_id == guild_id,
                CafeGachaMedalRedemption.user_id == user_id,
            )
            .group_by(CafeGachaMedalRedemptionItem.reward_key)
        )
    ).all()
    drawn_counts = {str(key): int(value) for key, value in drawn_rows}
    redeemed_counts = {str(key): int(value) for key, value in redeemed_rows}
    for key, value in medal_redeemed_rows:
        redeemed_counts[str(key)] = redeemed_counts.get(str(key), 0) + int(value)
    collected_count = len(drawn_counts)
    recent_duplicate_rows = (
        await session.execute(
            select(CafeGachaDraw.was_duplicate)
            .where(
                CafeGachaDraw.guild_id == guild_id,
                CafeGachaDraw.user_id == user_id,
            )
            .order_by(CafeGachaDraw.id.desc())
            .limit(ENDGAME_PITY_DUPLICATE_DRAWS)
        )
    ).scalars()
    duplicate_streak = 0
    for was_duplicate in recent_duplicate_rows:
        if not was_duplicate:
            break
        duplicate_streak += 1
    running_total_xp = wallet.total_xp
    running_spent_xp = wallet.spent_xp
    draws: list[CafeGachaDraw] = []

    for index, draw_event_id in enumerate(draw_event_ids):
        is_free = has_free_draw and index == 0
        cost_xp = 0 if is_free else PAID_DRAW_COST_XP
        if max(0, running_total_xp - running_spent_xp) < cost_xp:
            await session.rollback()
            return DrawBatchResult("insufficient_xp", (), wallet, wallet)

        value = (
            random_values[index]
            if random_values is not None
            else secrets.randbelow(10_000)
        )
        pity_ready = (
            collected_count >= ENDGAME_PITY_MIN_COLLECTED
            and collected_count < len(CARDS)
            and duplicate_streak >= ENDGAME_PITY_DUPLICATE_DRAWS
        )
        card = (
            select_unowned_card(value, drawn_counts.keys())
            if pity_ready
            else select_card_for_collection(value, drawn_counts.keys())
        )
        prior_count = drawn_counts.get(card.key, 0)
        if prior_count == 0:
            collected_count += 1
        draw = CafeGachaDraw(
            event_id=draw_event_id,
            batch_id=event_id,
            batch_position=index + 1,
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
            owned_count=prior_count - redeemed_counts.get(card.key, 0) + 1,
            collected_count=collected_count,
        )
        session.add(draw)
        draws.append(draw)
        drawn_counts[card.key] = prior_count + 1
        duplicate_streak = duplicate_streak + 1 if prior_count > 0 else 0
        running_total_xp += draw.reward_xp
        running_spent_xp += cost_xp

    if has_free_draw:
        state.last_free_draw_on = local_today
    state.hourly_draw_count += count
    await session.commit()
    for draw in draws:
        await session.refresh(draw)
    wallet_after = Wallet(running_total_xp, running_spent_xp)
    return DrawBatchResult("drawn", tuple(draws), wallet, wallet_after)


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
    medal_redeemed_rows = (
        await session.execute(
            select(
                CafeGachaMedalRedemptionItem.reward_key,
                func.sum(CafeGachaMedalRedemptionItem.quantity),
            )
            .join(
                CafeGachaMedalRedemption,
                CafeGachaMedalRedemption.id
                == CafeGachaMedalRedemptionItem.redemption_id,
            )
            .where(
                CafeGachaMedalRedemption.guild_id == guild_id,
                CafeGachaMedalRedemption.user_id == user_id,
            )
            .group_by(CafeGachaMedalRedemptionItem.reward_key)
        )
    ).all()
    drawn = {str(key): int(count) for key, count in draw_rows}
    redeemed = {str(key): int(count) for key, count in redeemed_rows}
    for key, count in medal_redeemed_rows:
        redeemed[str(key)] = redeemed.get(str(key), 0) + int(count)
    return tuple(
        CollectionCard(
            card=card,
            count=max(0, drawn.get(card.key, 0) - redeemed.get(card.key, 0)),
            redeemable_count=max(
                0, drawn.get(card.key, 0) - redeemed.get(card.key, 0) - 1
            ),
            lifetime_count=drawn.get(card.key, 0),
        )
        for card in CARDS
    )


async def duplicate_draw_streak(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> int:
    """直近から連続している重複抽選数を返す。"""
    rows = (
        await session.execute(
            select(CafeGachaDraw.was_duplicate)
            .where(
                CafeGachaDraw.guild_id == guild_id,
                CafeGachaDraw.user_id == user_id,
            )
            .order_by(CafeGachaDraw.id.desc())
            .limit(ENDGAME_PITY_DUPLICATE_DRAWS)
        )
    ).scalars()
    streak = 0
    for was_duplicate in rows:
        if not was_duplicate:
            break
        streak += 1
    return streak


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


async def cafe_medal_balance(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> int:
    earned = await session.scalar(
        select(
            func.coalesce(func.sum(CafeGachaMedalRedemption.reward_medals), 0)
        ).where(
            CafeGachaMedalRedemption.guild_id == guild_id,
            CafeGachaMedalRedemption.user_id == user_id,
        )
    )
    spent = await session.scalar(
        select(func.coalesce(func.sum(CafeGachaCosmeticUnlock.cost_medals), 0)).where(
            CafeGachaCosmeticUnlock.guild_id == guild_id,
            CafeGachaCosmeticUnlock.user_id == user_id,
        )
    )
    return int(earned or 0) - int(spent or 0)


async def redeem_cards_for_medals(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    user_id: str,
    quantities: dict[str, int],
) -> MedalRedemptionResult:
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    requested = {key: qty for key, qty in quantities.items() if qty > 0}
    if not requested or any(key not in CARDS_BY_KEY for key in requested):
        await session.rollback()
        return MedalRedemptionResult("unavailable", None, ())
    existing = await session.scalar(
        select(CafeGachaMedalRedemption).where(
            CafeGachaMedalRedemption.event_id == event_id
        )
    )
    if existing is not None:
        existing_items = tuple(
            (
                await session.execute(
                    select(CafeGachaMedalRedemptionItem).where(
                        CafeGachaMedalRedemptionItem.redemption_id == existing.id
                    )
                )
            ).scalars()
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
            return MedalRedemptionResult("unavailable", None, ())
        return MedalRedemptionResult("redeemed", existing, existing_items)
    collection = {
        item.card.key: item
        for item in await list_collection(session, guild_id=guild_id, user_id=user_id)
    }
    if any(collection[key].redeemable_count < qty for key, qty in requested.items()):
        await session.rollback()
        return MedalRedemptionResult("unavailable", None, ())
    reward = sum(
        MEDALS_BY_RARITY[CARDS_BY_KEY[key].rarity] * qty
        for key, qty in requested.items()
    )
    redemption = CafeGachaMedalRedemption(
        event_id=event_id,
        guild_id=guild_id,
        user_id=user_id,
        reward_medals=reward,
    )
    session.add(redemption)
    await session.flush()
    items: list[CafeGachaMedalRedemptionItem] = []
    for key, quantity in requested.items():
        card = CARDS_BY_KEY[key]
        rate = MEDALS_BY_RARITY[card.rarity]
        item = CafeGachaMedalRedemptionItem(
            redemption_id=redemption.id,
            reward_key=key,
            rarity=card.rarity,
            quantity=quantity,
            medals_per_card=rate,
            reward_medals=rate * quantity,
        )
        session.add(item)
        items.append(item)
    await session.commit()
    await session.refresh(redemption)
    return MedalRedemptionResult("redeemed", redemption, tuple(items))


async def unlock_or_equip_cosmetic(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    cosmetic_key: str,
) -> CosmeticResult:
    cosmetic = COSMETICS_BY_KEY.get(cosmetic_key)
    if cosmetic is None:
        return CosmeticResult("unavailable", None, 0)
    await lock_wallet(session, guild_id=guild_id, user_id=user_id)
    unlock = await session.scalar(
        select(CafeGachaCosmeticUnlock).where(
            CafeGachaCosmeticUnlock.guild_id == guild_id,
            CafeGachaCosmeticUnlock.user_id == user_id,
            CafeGachaCosmeticUnlock.cosmetic_key == cosmetic_key,
        )
    )
    balance = await cafe_medal_balance(session, guild_id=guild_id, user_id=user_id)
    if unlock is None:
        if balance < cosmetic.cost_medals:
            await session.rollback()
            return CosmeticResult("insufficient", cosmetic, balance)
        unlock = CafeGachaCosmeticUnlock(
            guild_id=guild_id,
            user_id=user_id,
            cosmetic_key=cosmetic_key,
            cost_medals=cosmetic.cost_medals,
        )
        session.add(unlock)
        balance -= cosmetic.cost_medals
    rows = (
        await session.execute(
            select(CafeGachaCosmeticUnlock).where(
                CafeGachaCosmeticUnlock.guild_id == guild_id,
                CafeGachaCosmeticUnlock.user_id == user_id,
            )
        )
    ).scalars()
    for row in rows:
        row.equipped = row is unlock
    unlock.equipped = True
    await session.commit()
    return CosmeticResult("equipped", cosmetic, balance)


async def active_cosmetic(
    session: AsyncSession, *, guild_id: str, user_id: str
) -> CafeCosmetic | None:
    key = await session.scalar(
        select(CafeGachaCosmeticUnlock.cosmetic_key).where(
            CafeGachaCosmeticUnlock.guild_id == guild_id,
            CafeGachaCosmeticUnlock.user_id == user_id,
            CafeGachaCosmeticUnlock.equipped.is_(True),
        )
    )
    return COSMETICS_BY_KEY.get(key) if key is not None else None
