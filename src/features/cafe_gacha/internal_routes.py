"""Trusted transactional API used by the separately deployed Cafe bot."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import CARDS
from src.features.cafe_gacha.internal_schemas import (
    CafeActorIn,
    CafeAvailabilityIn,
    CafeAvailabilityOut,
    CafeCapabilitiesOut,
    CafeCollectionCardOut,
    CafeCollectionIn,
    CafeCollectionOut,
    CafeDrawBatchOut,
    CafeDrawIn,
    CafeDrawOut,
    CafeWalletOut,
)
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


async def _earned_xp(db: AsyncSession, actor: CafeActorIn) -> int:
    levels = await get_user_lifetime_levels(db, actor.guild_id, actor.user_id)
    return earned_total_xp(levels) if levels is not None else 0


@router.get("/capabilities", response_model=CafeCapabilitiesOut)
async def capabilities() -> CafeCapabilitiesOut:
    manifest = ASSET_MANIFEST_PATH.read_bytes()
    return CafeCapabilitiesOut(
        api_version=1,
        catalog_size=len(CARDS),
        asset_count=len(tuple(ASSET_DIR.glob("*.jpg"))),
        asset_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
    )


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
        draws=[
            CafeDrawOut(
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
            for draw in result.draws
        ],
        wallet_before=_wallet_out(result.wallet_before),
        wallet_after=_wallet_out(result.wallet_after),
    )
    if result.status == "drawn":
        try:
            await request_level_role_sync(db, payload.actor.guild_id)
        except SQLAlchemyError:
            # The draw is already committed by draw_cards(). Role reconciliation is
            # best-effort and must not turn a successful, charged draw into a 500.
            logger.exception(
                "Failed to request level-role sync for guild %s",
                payload.actor.guild_id,
            )
            try:
                await db.rollback()
            except SQLAlchemyError:
                logger.exception(
                    "Failed to roll back level-role sync transaction for guild %s",
                    payload.actor.guild_id,
                )
    return response


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
            )
            for item in cards
        ]
    )
