"""Trusted transactional API used by the separately deployed Cafe bot."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    CafeGachaDraw,
    CafeGachaRedemption,
    CafeGachaRedemptionItem,
)
from src.features.cafe_gacha import bot_layout, service
from src.features.cafe_gacha.catalog import (
    CARDS,
    CARDS_BY_KEY,
    DRAW_REWARD_XP_BY_RARITY,
    ENDGAME_PITY_DUPLICATE_DRAWS,
    ENDGAME_PITY_MIN_COLLECTED,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
)
from src.features.cafe_gacha.internal_schemas import (
    CafeAccessRoleMutationIn,
    CafeAccessRolesIn,
    CafeAccessRolesOut,
    CafeActorIn,
    CafeAnalyticsIn,
    CafeAnalyticsOut,
    CafeAvailabilityIn,
    CafeAvailabilityOut,
    CafeCapabilitiesOut,
    CafeCardSettingIn,
    CafeCardSettingOut,
    CafeCollectionCardOut,
    CafeCollectionIn,
    CafeCollectionOut,
    CafeCosmeticIn,
    CafeCosmeticOut,
    CafeCosmeticResultOut,
    CafeDrawBatchOut,
    CafeDrawIn,
    CafeDrawOut,
    CafeLayoutIn,
    CafeLayoutOut,
    CafeLedgerDeliveredIn,
    CafeLedgerDeliveredOut,
    CafeLedgerDrawBatchOut,
    CafeLedgerPendingIn,
    CafeLedgerPendingOut,
    CafeLedgerRedemptionOut,
    CafeMasterySummaryOut,
    CafePlacementIn,
    CafeProtectionIn,
    CafeRankingCategoryOut,
    CafeRankingEntryOut,
    CafeRankingIn,
    CafeRankingsOut,
    CafeRedemptionIn,
    CafeRedemptionItemOut,
    CafeRedemptionOut,
    CafeSetOut,
    CafeWalletOut,
)
from src.features.cafe_gacha.leaderboard import (
    CAFE_LEADERBOARD_CATEGORIES,
    CafeLeaderboardEntry,
    cafe_leaderboard_snapshot,
    rank_cafe_leaderboard,
)
from src.features.cafe_gacha.mastery import MASTERY_TIERS, mastery_tier
from src.features.cafe_gacha.medals import COSMETICS, MEDALS_BY_RARITY, CafeCosmetic
from src.features.cafe_gacha.sets import SETS, completed_set_keys
from src.features.economy.service import Wallet
from src.features.feature_access import service as feature_access_service
from src.features.guilds.service import request_level_role_sync
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels
from src.web.deps import get_db

ASSET_DIR = Path(__file__).parent / "assets"
ASSET_MANIFEST_PATH = ASSET_DIR / "manifest.json"
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/integrations/cafe-collection",
    tags=["cafe-collection-internal"],
)


def _wallet_out(wallet: Wallet) -> CafeWalletOut:
    return CafeWalletOut(
        total_xp=wallet.total_xp,
        spent_xp=wallet.spent_xp,
        available_xp=wallet.available_xp,
    )


async def _ensure_access(db: AsyncSession, actor: CafeActorIn) -> None:
    allowed_role_ids = await feature_access_service.list_access_role_ids(
        db,
        guild_id=actor.guild_id,
        feature=feature_access_service.CAFE_GACHA,
    )
    if not feature_access_service.member_has_access(
        allowed_role_ids=allowed_role_ids,
        member_role_ids=set(actor.role_ids),
        can_manage_guild=actor.can_manage_guild,
    ):
        raise HTTPException(status_code=403, detail="Cafe Collection access denied")


def _ensure_manage_guild(actor: CafeActorIn) -> None:
    if not actor.can_manage_guild:
        raise HTTPException(status_code=403, detail="Manage Guild permission required")


def _layout_out(layout: object | None) -> CafeLayoutOut:
    return CafeLayoutOut(
        panel_channel_id=getattr(layout, "panel_channel_id", None),
        panel_message_id=getattr(layout, "panel_message_id", None),
        ledger_channel_id=getattr(layout, "ledger_channel_id", None),
        ledger_message_id=getattr(layout, "ledger_message_id", None),
        ranking_channel_id=getattr(layout, "ranking_channel_id", None),
        ranking_message_id=getattr(layout, "ranking_message_id", None),
    )


def _ranking_entry_out(entry: CafeLeaderboardEntry) -> CafeRankingEntryOut:
    return CafeRankingEntryOut(
        rank=entry.rank,
        user_id=entry.user_id,
        collection_count=entry.collection_count,
        mastery_score=entry.mastery_score,
        signature_cards=entry.signature_cards,
        completed_sets=entry.completed_sets,
        rare_collection_count=entry.rare_collection_count,
        treasure_collection_count=entry.treasure_collection_count,
        n_mastery_score=entry.n_mastery_score,
        coffee_mastery_score=entry.coffee_mastery_score,
        tea_mastery_score=entry.tea_mastery_score,
        sweets_mastery_score=entry.sweets_mastery_score,
        culture_mastery_score=entry.culture_mastery_score,
    )


def _cosmetic_out(cosmetic: CafeCosmetic) -> CafeCosmeticOut:
    return CafeCosmeticOut(
        key=cosmetic.key,
        name=cosmetic.name,
        cost_medals=cosmetic.cost_medals,
        color=cosmetic.color,
        decoration=cosmetic.decoration,
    )


def _draw_out(draw: CafeGachaDraw) -> CafeDrawOut:
    return CafeDrawOut(
        event_id=draw.event_id,
        batch_position=draw.batch_position,
        reward_key=draw.reward_key,
        reward_name=draw.reward_name,
        reward_description=draw.reward_description,
        rarity=draw.rarity,
        image_filename=draw.image_filename,
        draw_type=draw.draw_type,
        cost_xp=draw.cost_xp,
        reward_xp=draw.reward_xp,
        exchange_xp=draw.exchange_xp,
        was_duplicate=draw.was_duplicate,
        owned_count=draw.owned_count,
        collected_count=draw.collected_count,
    )


def _redemption_item_out(item: CafeGachaRedemptionItem) -> CafeRedemptionItemOut:
    return CafeRedemptionItemOut(
        reward_key=item.reward_key,
        reward_name=item.reward_name,
        rarity=item.rarity,
        quantity=item.quantity,
        reward_per_card=item.xp_per_card,
        reward_total=item.reward_xp,
    )


def _endgame_pity_active(cards: tuple[service.CollectionCard, ...]) -> bool:
    owned = sum(item.count > 0 for item in cards)
    return ENDGAME_PITY_MIN_COLLECTED <= owned < len(cards)


async def _request_role_sync_after_commit(db: AsyncSession, guild_id: str) -> None:
    """Best-effort role reconciliation after a committed XP mutation."""
    try:
        await request_level_role_sync(db, guild_id)
    except SQLAlchemyError:
        logger.exception("Failed to request level-role sync for guild %s", guild_id)
        try:
            await db.rollback()
        except SQLAlchemyError:
            logger.exception(
                "Failed to roll back level-role sync transaction for guild %s",
                guild_id,
            )


async def _earned_xp(db: AsyncSession, actor: CafeActorIn) -> int:
    levels = await get_user_lifetime_levels(db, actor.guild_id, actor.user_id)
    return earned_total_xp(levels) if levels is not None else 0


@router.get("/capabilities", response_model=CafeCapabilitiesOut)
async def capabilities() -> CafeCapabilitiesOut:
    manifest = ASSET_MANIFEST_PATH.read_bytes()
    return CafeCapabilitiesOut(
        api_version=3,
        catalog_size=len(CARDS),
        asset_count=len(tuple(ASSET_DIR.glob("*.jpg"))),
        asset_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        paid_draw_cost_xp=PAID_DRAW_COST_XP,
        hourly_draw_limit=MAX_HOURLY_DRAWS,
        minimum_draw_reward_xp=min(DRAW_REWARD_XP_BY_RARITY.values()),
        maximum_draw_reward_xp=max(DRAW_REWARD_XP_BY_RARITY.values()),
    )


@router.post("/discord-layout", response_model=CafeLayoutOut)
async def discord_layout(
    payload: CafeLayoutIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeLayoutOut:
    _ensure_manage_guild(payload.actor)
    return _layout_out(await bot_layout.get_layout(db, guild_id=payload.actor.guild_id))


@router.post("/discord-layout/placements", response_model=CafeLayoutOut)
async def save_discord_placement(
    payload: CafePlacementIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeLayoutOut:
    _ensure_manage_guild(payload.actor)
    layout = await bot_layout.save_placement(
        db,
        guild_id=payload.actor.guild_id,
        placement=payload.placement,
        channel_id=payload.channel_id,
        message_id=payload.message_id,
    )
    return _layout_out(layout)


@router.post("/draw-availability", response_model=CafeAvailabilityOut)
async def draw_availability(
    payload: CafeAvailabilityIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeAvailabilityOut:
    await _ensure_access(db, payload.actor)
    availability = await service.draw_availability(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
        earned_xp=await _earned_xp(db, payload.actor),
    )
    return CafeAvailabilityOut(
        wallet=_wallet_out(availability.wallet),
        has_free_draw=availability.has_free_draw,
        hourly_remaining=availability.hourly_remaining,
        requested_count=payload.count,
        cost_xp=availability.cost_for(payload.count),
    )


@router.post("/draws", response_model=CafeDrawBatchOut)
async def create_draws(
    payload: CafeDrawIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeDrawBatchOut:
    await _ensure_access(db, payload.actor)
    try:
        result = await service.draw_cards(
            db,
            event_id=payload.event_id,
            guild_id=payload.actor.guild_id,
            user_id=payload.actor.user_id,
            display_name=payload.display_name,
            earned_xp=await _earned_xp(db, payload.actor),
            count=payload.count,
            allow_paid=True,
            expected_cost_xp=payload.expected_cost_xp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = CafeDrawBatchOut(
        status=result.status,
        draws=[_draw_out(draw) for draw in result.draws],
        wallet_before=_wallet_out(result.wallet_before),
        wallet_after=_wallet_out(result.wallet_after),
    )
    if result.status == "drawn":
        await _request_role_sync_after_commit(db, payload.actor.guild_id)
    return response


@router.post("/ledger/pending", response_model=CafeLedgerPendingOut)
async def pending_ledger_notifications(
    payload: CafeLedgerPendingIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeLedgerPendingOut:
    """Return transactions not yet posted by the separately deployed bot."""
    layout = await bot_layout.get_layout(db, guild_id=payload.guild_id)
    if (
        layout is None
        or layout.ledger_channel_id is None
        or layout.ledger_configured_at is None
    ):
        return CafeLedgerPendingOut(
            ledger_channel_id=None,
            draw_batches=[],
            redemptions=[],
        )

    batch_id_rows = tuple(
        (
            await db.execute(
                select(
                    CafeGachaDraw.batch_id,
                    func.min(CafeGachaDraw.created_at).label("first_created_at"),
                    func.min(CafeGachaDraw.id).label("first_id"),
                )
                .where(
                    CafeGachaDraw.guild_id == payload.guild_id,
                    CafeGachaDraw.created_at >= layout.ledger_configured_at,
                    CafeGachaDraw.collection_bot_ledger_message_id.is_(None),
                )
                .group_by(CafeGachaDraw.batch_id)
                .order_by(
                    func.min(CafeGachaDraw.created_at).asc(),
                    func.min(CafeGachaDraw.id).asc(),
                )
                .limit(50)
            )
        ).all()
    )
    batch_ids = [row.batch_id for row in batch_id_rows]
    batches: dict[str, list[CafeGachaDraw]] = {batch_id: [] for batch_id in batch_ids}
    if batch_ids:
        draw_rows = tuple(
            (
                await db.execute(
                    select(CafeGachaDraw)
                    .where(
                        CafeGachaDraw.guild_id == payload.guild_id,
                        CafeGachaDraw.batch_id.in_(batch_ids),
                    )
                    .order_by(
                        CafeGachaDraw.batch_id.asc(),
                        CafeGachaDraw.batch_position.asc(),
                        CafeGachaDraw.id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        for draw in draw_rows:
            batches[draw.batch_id].append(draw)

    redemption_rows = tuple(
        (
            await db.execute(
                select(CafeGachaRedemption)
                .where(
                    CafeGachaRedemption.guild_id == payload.guild_id,
                    CafeGachaRedemption.created_at >= layout.ledger_configured_at,
                    CafeGachaRedemption.collection_bot_ledger_message_id.is_(None),
                )
                .order_by(
                    CafeGachaRedemption.created_at.asc(),
                    CafeGachaRedemption.id.asc(),
                )
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    items_by_redemption: dict[int, list[CafeGachaRedemptionItem]] = {
        row.id: [] for row in redemption_rows
    }
    if items_by_redemption:
        item_rows = tuple(
            (
                await db.execute(
                    select(CafeGachaRedemptionItem)
                    .where(
                        CafeGachaRedemptionItem.redemption_id.in_(items_by_redemption)
                    )
                    .order_by(CafeGachaRedemptionItem.id.asc())
                )
            )
            .scalars()
            .all()
        )
        for item in item_rows:
            items_by_redemption[item.redemption_id].append(item)

    return CafeLedgerPendingOut(
        ledger_channel_id=layout.ledger_channel_id,
        draw_batches=[
            CafeLedgerDrawBatchOut(
                event_id=batch_id,
                user_id=draws[0].user_id,
                created_at=draws[0].created_at,
                draws=[_draw_out(draw) for draw in draws],
            )
            for batch_id, draws in batches.items()
        ],
        redemptions=[
            CafeLedgerRedemptionOut(
                event_id=row.event_id,
                user_id=row.user_id,
                created_at=row.created_at,
                reward_xp=row.reward_xp,
                items=[
                    _redemption_item_out(item) for item in items_by_redemption[row.id]
                ],
            )
            for row in redemption_rows
        ],
    )


@router.post("/ledger/delivered", response_model=CafeLedgerDeliveredOut)
async def mark_ledger_notification_delivered(
    payload: CafeLedgerDeliveredIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeLedgerDeliveredOut:
    if payload.record_type == "draw":
        rows = tuple(
            (
                await db.execute(
                    select(CafeGachaDraw)
                    .where(
                        CafeGachaDraw.guild_id == payload.guild_id,
                        CafeGachaDraw.batch_id == payload.event_id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Cafe draw not found")
        for draw_row in rows:
            if draw_row.collection_bot_ledger_message_id not in (
                None,
                payload.message_id,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Cafe draw was delivered by another message",
                )
            draw_row.collection_bot_ledger_message_id = payload.message_id
    else:
        redemption_row = (
            await db.execute(
                select(CafeGachaRedemption)
                .where(
                    CafeGachaRedemption.guild_id == payload.guild_id,
                    CafeGachaRedemption.event_id == payload.event_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if redemption_row is None:
            raise HTTPException(status_code=404, detail="Cafe redemption not found")
        if redemption_row.collection_bot_ledger_message_id not in (
            None,
            payload.message_id,
        ):
            raise HTTPException(
                status_code=409,
                detail="Cafe redemption was delivered by another message",
            )
        redemption_row.collection_bot_ledger_message_id = payload.message_id
    await db.commit()
    return CafeLedgerDeliveredOut(delivered=True)


@router.post("/collection", response_model=CafeCollectionOut)
async def collection(
    payload: CafeCollectionIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeCollectionOut:
    await _ensure_access(db, payload.actor)
    cards = await service.list_collection(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
    )
    favorite = await service.favorite_card(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
    )
    duplicate_streak = await service.duplicate_draw_streak(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
    )
    medal_balance = await service.cafe_medal_balance(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
    )
    active_cosmetic = await service.active_cosmetic(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
    )
    lifetime_owned_keys = {item.card.key for item in cards if item.lifetime_count > 0}
    mastery_counts = {
        tier.name: sum(mastery_tier(item.lifetime_count) == tier for item in cards)
        for tier in MASTERY_TIERS
    }
    completed_sets = completed_set_keys(lifetime_owned_keys)
    return CafeCollectionOut(
        cards=[
            CafeCollectionCardOut(
                key=item.card.key,
                name=item.card.name,
                rarity=item.card.rarity,
                description=item.card.description,
                image_filename=item.card.image_filename,
                count=item.count,
                redeemable_count=item.redeemable_count,
                lifetime_count=item.lifetime_count,
                is_protected=item.is_protected,
                exchangeable_count=item.exchangeable_count,
                exchange_xp=item.card.exchange_xp,
                exchange_medals=MEDALS_BY_RARITY[item.card.rarity],
                mastery_name=(
                    tier.name
                    if (tier := mastery_tier(item.lifetime_count)) is not None
                    else None
                ),
                mastery_emoji=tier.emoji if tier is not None else None,
            )
            for item in cards
        ],
        favorite_reward_key=favorite.key if favorite is not None else None,
        duplicate_draw_streak=duplicate_streak,
        endgame_pity_active=_endgame_pity_active(cards),
        endgame_pity_duplicate_draws=ENDGAME_PITY_DUPLICATE_DRAWS,
        mastery_tiers=[
            CafeMasterySummaryOut(
                name=tier.name,
                emoji=tier.emoji,
                card_count=mastery_counts[tier.name],
            )
            for tier in MASTERY_TIERS
        ],
        medal_balance=medal_balance,
        active_cosmetic=(
            _cosmetic_out(active_cosmetic) if active_cosmetic is not None else None
        ),
        cosmetics=[_cosmetic_out(cosmetic) for cosmetic in COSMETICS],
        sets=[
            CafeSetOut(
                key=item.key,
                name=item.name,
                description=item.description,
                completed=item.key in completed_sets,
                missing_card_names=[
                    CARDS_BY_KEY[key].name
                    for key in item.required_keys
                    if key not in lifetime_owned_keys
                ],
            )
            for item in SETS
        ],
    )


@router.post("/favorite", response_model=CafeCardSettingOut)
async def set_favorite(
    payload: CafeCardSettingIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeCardSettingOut:
    await _ensure_access(db, payload.actor)
    card = await service.set_favorite_card(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
        reward_key=payload.reward_key,
    )
    return CafeCardSettingOut(
        status="updated" if card is not None else "unavailable",
        reward_key=card.key if card is not None else None,
        reward_name=card.name if card is not None else None,
    )


@router.post("/protection", response_model=CafeCardSettingOut)
async def set_protection(
    payload: CafeProtectionIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeCardSettingOut:
    await _ensure_access(db, payload.actor)
    card = await service.set_card_protection(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
        reward_key=payload.reward_key,
        protected=payload.protected,
    )
    return CafeCardSettingOut(
        status="updated" if card is not None else "unavailable",
        reward_key=card.key if card is not None else None,
        reward_name=card.name if card is not None else None,
        protected=payload.protected if card is not None else None,
    )


@router.post("/redemptions/xp", response_model=CafeRedemptionOut)
async def redeem_for_xp(
    payload: CafeRedemptionIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeRedemptionOut:
    await _ensure_access(db, payload.actor)
    result = await service.redeem_cards(
        db,
        event_id=payload.event_id,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
        display_name=payload.display_name,
        quantities=payload.quantities,
    )
    if result.status == "redeemed" and result.redemption is not None:
        await _request_role_sync_after_commit(db, payload.actor.guild_id)
    return CafeRedemptionOut(
        status=result.status,
        reward_xp=(result.redemption.reward_xp if result.redemption is not None else 0),
        reward_medals=0,
        items=[
            CafeRedemptionItemOut(
                reward_key=item.reward_key,
                reward_name=item.reward_name,
                rarity=item.rarity,
                quantity=item.quantity,
                reward_per_card=item.xp_per_card,
                reward_total=item.reward_xp,
            )
            for item in result.items
        ],
    )


@router.post("/redemptions/medals", response_model=CafeRedemptionOut)
async def redeem_for_medals(
    payload: CafeRedemptionIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeRedemptionOut:
    await _ensure_access(db, payload.actor)
    result = await service.redeem_cards_for_medals(
        db,
        event_id=payload.event_id,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
        quantities=payload.quantities,
    )
    return CafeRedemptionOut(
        status=result.status,
        reward_xp=0,
        reward_medals=(
            result.redemption.reward_medals if result.redemption is not None else 0
        ),
        items=[
            CafeRedemptionItemOut(
                reward_key=item.reward_key,
                reward_name=CARDS_BY_KEY[item.reward_key].name,
                rarity=item.rarity,
                quantity=item.quantity,
                reward_per_card=item.medals_per_card,
                reward_total=item.reward_medals,
            )
            for item in result.items
        ],
    )


@router.post("/cosmetics/equip", response_model=CafeCosmeticResultOut)
async def equip_cosmetic(
    payload: CafeCosmeticIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeCosmeticResultOut:
    await _ensure_access(db, payload.actor)
    result = await service.unlock_or_equip_cosmetic(
        db,
        guild_id=payload.actor.guild_id,
        user_id=payload.actor.user_id,
        cosmetic_key=payload.cosmetic_key,
    )
    return CafeCosmeticResultOut(
        status=result.status,
        cosmetic=(
            _cosmetic_out(result.cosmetic) if result.cosmetic is not None else None
        ),
        balance=result.balance,
    )


@router.post("/analytics", response_model=CafeAnalyticsOut)
async def analytics(
    payload: CafeAnalyticsIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeAnalyticsOut:
    _ensure_manage_guild(payload.actor)
    result = await service.guild_analytics(db, guild_id=payload.actor.guild_id)
    return CafeAnalyticsOut(
        draws_today=result.draws_today,
        draws_7d=result.draws_7d,
        total_draws=result.total_draws,
        active_today=result.active_today,
        active_7d=result.active_7d,
        total_users=result.total_users,
        new_7d=result.new_7d,
        duplicate_7d=result.duplicate_7d,
        rarity_7d=dict(result.rarity_7d),
        spent_xp_7d=result.spent_xp_7d,
        draw_reward_xp_7d=result.draw_reward_xp_7d,
        redemption_xp_7d=result.redemption_xp_7d,
        completed_users=result.completed_users,
    )


@router.post("/access-roles", response_model=CafeAccessRolesOut)
async def access_roles(
    payload: CafeAccessRolesIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeAccessRolesOut:
    _ensure_manage_guild(payload.actor)
    role_ids = await feature_access_service.list_access_role_ids(
        db,
        guild_id=payload.actor.guild_id,
        feature=feature_access_service.CAFE_GACHA,
    )
    return CafeAccessRolesOut(role_ids=sorted(role_ids))


@router.post("/access-roles/add", response_model=CafeAccessRolesOut)
async def add_access_role(
    payload: CafeAccessRoleMutationIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeAccessRolesOut:
    _ensure_manage_guild(payload.actor)
    changed = await feature_access_service.add_access_role(
        db,
        guild_id=payload.actor.guild_id,
        feature=feature_access_service.CAFE_GACHA,
        role_id=payload.role_id,
    )
    role_ids = await feature_access_service.list_access_role_ids(
        db,
        guild_id=payload.actor.guild_id,
        feature=feature_access_service.CAFE_GACHA,
    )
    return CafeAccessRolesOut(role_ids=sorted(role_ids), changed=changed)


@router.post("/access-roles/remove", response_model=CafeAccessRolesOut)
async def remove_access_role(
    payload: CafeAccessRoleMutationIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeAccessRolesOut:
    _ensure_manage_guild(payload.actor)
    changed = await feature_access_service.remove_access_role(
        db,
        guild_id=payload.actor.guild_id,
        feature=feature_access_service.CAFE_GACHA,
        role_id=payload.role_id,
    )
    role_ids = await feature_access_service.list_access_role_ids(
        db,
        guild_id=payload.actor.guild_id,
        feature=feature_access_service.CAFE_GACHA,
    )
    return CafeAccessRolesOut(role_ids=sorted(role_ids), changed=changed)


@router.post("/rankings", response_model=CafeRankingsOut)
async def rankings(
    payload: CafeRankingIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeRankingsOut:
    await _ensure_access(db, payload.actor)
    snapshot = await cafe_leaderboard_snapshot(
        db,
        guild_id=payload.actor.guild_id,
    )
    categories: list[CafeRankingCategoryOut] = []
    for category in CAFE_LEADERBOARD_CATEGORIES:
        ranked = rank_cafe_leaderboard(snapshot, category)
        viewer_entry = next(
            (entry for entry in ranked if entry.user_id == payload.actor.user_id),
            None,
        )
        categories.append(
            CafeRankingCategoryOut(
                key=category,
                entries=[_ranking_entry_out(entry) for entry in ranked[:20]],
                viewer_entry=(
                    _ranking_entry_out(viewer_entry)
                    if viewer_entry is not None
                    else None
                ),
            )
        )
    return CafeRankingsOut(
        participant_count=len(snapshot.entries),
        total_draws=sum(entry.total_draws for entry in snapshot.entries),
        captured_at=datetime.now(UTC),
        categories=categories,
    )
