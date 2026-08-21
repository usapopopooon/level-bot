from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.color_role_shop.service import Wallet, wallet_for_user
from src.features.guilds.service import request_level_role_sync
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels
from src.features.minecraft_item_gacha.service import (
    ITEM_GACHA_DAILY_LIMIT,
    ITEM_GACHA_NORMAL_COST_XP,
    ITEM_GACHA_PREMIUM_COST_XP,
)
from src.features.minecraft_item_gacha.service import (
    cancel_spend as cancel_item_gacha_spend,
)
from src.features.minecraft_item_gacha.service import (
    complete_spend as complete_item_gacha_spend,
)
from src.features.minecraft_item_gacha.service import (
    request_spend as request_item_gacha_spend,
)
from src.features.minecraft_market.service import (
    list_pending_purchases as list_pending_market_purchases,
)
from src.features.minecraft_market.service import (
    request_purchase as request_market_purchase,
)
from src.features.minecraft_market.service import (
    update_purchase as update_market_purchase,
)
from src.features.minecraft_material_buyback.service import (
    request_buyback as request_material_buyback,
)
from src.features.minecraft_material_buyback.service import (
    update_buyback as update_material_buyback,
)
from src.features.minecraft_resource_shop.service import (
    MINECRAFT_RESOURCE_PACKS,
)
from src.features.minecraft_resource_shop.service import (
    cancel_exchange as cancel_resource_exchange,
)
from src.features.minecraft_resource_shop.service import (
    claim_exchange as claim_resource_exchange,
)
from src.features.minecraft_resource_shop.service import (
    complete_exchange as complete_resource_exchange,
)
from src.features.minecraft_resource_shop.service import (
    list_pending_exchanges as list_pending_resource_exchanges,
)
from src.features.minecraft_resource_shop.service import (
    request_exchange as request_resource_exchange,
)
from src.features.minecraft_xp.schemas import (
    MinecraftItemGachaOut,
    MinecraftItemGachaSpendActionIn,
    MinecraftItemGachaSpendIn,
    MinecraftItemGachaSpendOut,
    MinecraftLevelUpAckIn,
    MinecraftLevelUpEventOut,
    MinecraftMarketPendingPurchaseOut,
    MinecraftMarketPurchaseActionIn,
    MinecraftMarketPurchaseIn,
    MinecraftMarketPurchaseRequestOut,
    MinecraftMarketWalletOut,
    MinecraftMaterialBuybackActionIn,
    MinecraftMaterialBuybackIn,
    MinecraftMaterialBuybackOut,
    MinecraftResourceExchangeOut,
    MinecraftResourcePackOut,
    MinecraftResourceShopExchangeIn,
    MinecraftResourceShopExchangeOut,
    MinecraftResourceShopOut,
    MinecraftVoiceHeartbeatIn,
    MinecraftVoiceHeartbeatOut,
    MinecraftXpEventIn,
    MinecraftXpEventOut,
    MinecraftXpExchangeActionIn,
    MinecraftXpExchangeOut,
    MinecraftXpShopExchangeIn,
    MinecraftXpShopExchangeOut,
    MinecraftXpShopOut,
    MinecraftXpShopPackOut,
    MinecraftXpShopWalletOut,
)
from src.features.minecraft_xp.service import (
    acknowledge_minecraft_level_up,
    enqueue_minecraft_level_up_from_meta,
    list_pending_minecraft_level_ups,
    record_minecraft_voice_heartbeat,
    record_minecraft_xp,
)
from src.features.minecraft_xp_shop.service import (
    MINECRAFT_XP_PACKS,
    cancel_exchange,
    claim_exchange,
    complete_exchange,
    list_pending_exchanges,
    request_exchange,
)
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1/integrations/minecraft", tags=["minecraft-xp"])


async def _shop_wallet(db: AsyncSession, *, guild_id: str, user_id: str) -> Wallet:
    levels = await get_user_lifetime_levels(db, guild_id, user_id)
    total_xp = 0
    if levels is not None:
        total_xp = earned_total_xp(levels)
    return await wallet_for_user(
        db,
        guild_id=guild_id,
        user_id=user_id,
        total_xp=total_xp,
    )


def _wallet_out(wallet: Wallet) -> MinecraftXpShopWalletOut:
    return MinecraftXpShopWalletOut(
        total_xp=wallet.total_xp,
        spent_xp=wallet.spent_xp,
        available_xp=wallet.available_xp,
    )


@router.get("/market/wallet", response_model=MinecraftMarketWalletOut)
async def get_minecraft_market_wallet(
    guild_id: str = Query(pattern=r"^\d+$"),
    user_id: str = Query(pattern=r"^\d+$"),
    db: AsyncSession = Depends(get_db),
) -> MinecraftMarketWalletOut:
    return MinecraftMarketWalletOut(
        wallet=_wallet_out(await _shop_wallet(db, guild_id=guild_id, user_id=user_id))
    )


@router.post(
    "/market/purchases",
    response_model=MinecraftMarketPurchaseRequestOut,
    responses={409: {"model": MinecraftMarketPurchaseRequestOut}},
)
async def create_minecraft_market_purchase(
    payload: MinecraftMarketPurchaseIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MinecraftMarketPurchaseRequestOut:
    wallet = await _shop_wallet(
        db, guild_id=payload.guild_id, user_id=payload.buyer_user_id
    )
    result = await request_market_purchase(
        db,
        event_id=payload.request_id,
        guild_id=payload.guild_id,
        listing_id=payload.listing_id,
        buyer_user_id=payload.buyer_user_id,
        seller_user_id=payload.seller_user_id,
        buyer_minecraft_account_id=payload.buyer_minecraft_account_id,
        seller_minecraft_account_id=payload.seller_minecraft_account_id,
        cost_xp=payload.expected_cost_xp,
        buyer_total_xp=wallet.total_xp,
    )
    if result.duplicate or result.status == "conflict":
        response.status_code = 409
    return MinecraftMarketPurchaseRequestOut(
        status=result.status,
        message=result.message,
        request_id=result.request_id,
        wallet_before=_wallet_out(result.wallet_before),
        wallet_after=_wallet_out(result.wallet_after),
        duplicate=result.duplicate,
    )


@router.get("/market/purchases", response_model=list[MinecraftMarketPendingPurchaseOut])
async def get_minecraft_market_purchases(
    guild_id: str = Query(pattern=r"^\d+$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[MinecraftMarketPendingPurchaseOut]:
    purchases = await list_pending_market_purchases(db, guild_id=guild_id, limit=limit)
    return [
        MinecraftMarketPendingPurchaseOut(
            request_id=purchase.event_id,
            guild_id=purchase.guild_id,
            listing_id=purchase.listing_id,
            buyer_user_id=purchase.buyer_user_id,
            seller_user_id=purchase.seller_user_id,
            buyer_minecraft_account_id=purchase.buyer_minecraft_account_id,
            seller_minecraft_account_id=purchase.seller_minecraft_account_id,
            cost_xp=purchase.cost_xp,
        )
        for purchase in purchases
    ]


async def _market_purchase_action(
    action: Literal["complete", "cancel"],
    request_id: str,
    payload: MinecraftMarketPurchaseActionIn,
    db: AsyncSession,
) -> Response:
    changed = await update_market_purchase(
        db,
        event_id=request_id,
        guild_id=payload.guild_id,
        action=action,
    )
    if not changed:
        raise HTTPException(status_code=409, detail="Market purchase state changed")
    if action == "complete":
        await request_level_role_sync(db, payload.guild_id)
    return Response(status_code=204)


@router.post("/market/purchases/{request_id}/complete", status_code=204)
async def complete_minecraft_market_purchase(
    request_id: str,
    payload: MinecraftMarketPurchaseActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _market_purchase_action("complete", request_id, payload, db)


@router.post("/market/purchases/{request_id}/cancel", status_code=204)
async def cancel_minecraft_market_purchase(
    request_id: str,
    payload: MinecraftMarketPurchaseActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _market_purchase_action("cancel", request_id, payload, db)


@router.post(
    "/material-buybacks",
    response_model=MinecraftMaterialBuybackOut,
    responses={409: {"model": MinecraftMaterialBuybackOut}},
)
async def create_minecraft_material_buyback(
    payload: MinecraftMaterialBuybackIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MinecraftMaterialBuybackOut:
    result = await request_material_buyback(
        db,
        request_id=payload.request_id,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        minecraft_account_id=payload.minecraft_account_id,
        item_id=payload.item_id,
        item_count=payload.item_count,
        expected_reward_xp=payload.expected_reward_xp,
    )
    if result.duplicate or result.status == "conflict":
        response.status_code = 409
    return MinecraftMaterialBuybackOut(
        status=result.status,
        message=result.message,
        request_id=result.request_id,
        item_id=result.item_id,
        item_name=result.item_name,
        item_count=result.item_count,
        reward_xp=result.reward_xp,
        reward_day=result.reward_day,
        daily_reserved_xp=result.daily_reserved_xp,
        daily_limit_xp=result.daily_limit_xp,
        duplicate=result.duplicate,
    )


async def _material_buyback_action(
    action: Literal["complete", "cancel"],
    request_id: str,
    payload: MinecraftMaterialBuybackActionIn,
    db: AsyncSession,
) -> Response:
    changed = await update_material_buyback(
        db,
        request_id=request_id,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        action=action,
    )
    if not changed:
        raise HTTPException(status_code=409, detail="Material buyback state changed")
    if action == "complete":
        await request_level_role_sync(db, payload.guild_id)
    return Response(status_code=204)


@router.post("/material-buybacks/{request_id}/complete", status_code=204)
async def complete_minecraft_material_buyback(
    request_id: str,
    payload: MinecraftMaterialBuybackActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _material_buyback_action("complete", request_id, payload, db)


@router.post("/material-buybacks/{request_id}/cancel", status_code=204)
async def cancel_minecraft_material_buyback(
    request_id: str,
    payload: MinecraftMaterialBuybackActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _material_buyback_action("cancel", request_id, payload, db)


@router.get("/xp-shop", response_model=MinecraftXpShopOut)
async def get_minecraft_xp_shop(
    guild_id: str = Query(pattern=r"^\d+$"),
    user_id: str = Query(pattern=r"^\d+$"),
    db: AsyncSession = Depends(get_db),
) -> MinecraftXpShopOut:
    wallet = await _shop_wallet(db, guild_id=guild_id, user_id=user_id)
    return MinecraftXpShopOut(
        wallet=_wallet_out(wallet),
        packs=[
            MinecraftXpShopPackOut(cost_xp=pack.cost_xp, reward_xp=pack.reward_xp)
            for pack in MINECRAFT_XP_PACKS
        ],
    )


@router.post("/xp-shop/exchanges", response_model=MinecraftXpShopExchangeOut)
async def request_minecraft_xp_shop_exchange(
    payload: MinecraftXpShopExchangeIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftXpShopExchangeOut:
    wallet = await _shop_wallet(db, guild_id=payload.guild_id, user_id=payload.user_id)
    result = await request_exchange(
        db,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        request_id=payload.request_id,
        cost_xp=payload.cost_xp,
        expected_reward_xp=payload.expected_reward_xp,
        total_xp=wallet.total_xp,
    )
    return MinecraftXpShopExchangeOut(
        status=result.status,
        message=result.message,
        wallet_before=_wallet_out(result.wallet_before),
        wallet_after=_wallet_out(result.wallet_after),
        pack=(
            MinecraftXpShopPackOut(
                cost_xp=result.pack.cost_xp,
                reward_xp=result.pack.reward_xp,
            )
            if result.pack is not None
            else None
        ),
    )


@router.get("/resource-shop", response_model=MinecraftResourceShopOut)
async def get_minecraft_resource_shop(
    guild_id: str = Query(pattern=r"^\d+$"),
    user_id: str = Query(pattern=r"^\d+$"),
    db: AsyncSession = Depends(get_db),
) -> MinecraftResourceShopOut:
    wallet = await _shop_wallet(db, guild_id=guild_id, user_id=user_id)
    return MinecraftResourceShopOut(
        wallet=_wallet_out(wallet),
        packs=[
            MinecraftResourcePackOut(
                item_id=pack.item_id,
                item_name=pack.item_name,
                item_count=pack.item_count,
                cost_xp=pack.cost_xp,
            )
            for pack in MINECRAFT_RESOURCE_PACKS
        ],
    )


@router.post(
    "/resource-shop/exchanges", response_model=MinecraftResourceShopExchangeOut
)
async def request_minecraft_resource_shop_exchange(
    payload: MinecraftResourceShopExchangeIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftResourceShopExchangeOut:
    wallet = await _shop_wallet(db, guild_id=payload.guild_id, user_id=payload.user_id)
    result = await request_resource_exchange(
        db,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        request_id=payload.request_id,
        item_id=payload.item_id,
        item_count=payload.item_count,
        expected_cost_xp=payload.expected_cost_xp,
        total_xp=wallet.total_xp,
    )
    return MinecraftResourceShopExchangeOut(
        status=result.status,
        message=result.message,
        wallet_before=_wallet_out(result.wallet_before),
        wallet_after=_wallet_out(result.wallet_after),
        pack=(
            MinecraftResourcePackOut(
                item_id=result.pack.item_id,
                item_name=result.pack.item_name,
                item_count=result.pack.item_count,
                cost_xp=result.pack.cost_xp,
            )
            if result.pack is not None
            else None
        ),
    )


@router.get("/item-gacha", response_model=MinecraftItemGachaOut)
async def get_minecraft_item_gacha(
    guild_id: str = Query(pattern=r"^\d+$"),
    user_id: str = Query(pattern=r"^\d+$"),
    db: AsyncSession = Depends(get_db),
) -> MinecraftItemGachaOut:
    wallet = await _shop_wallet(db, guild_id=guild_id, user_id=user_id)
    return MinecraftItemGachaOut(
        cost_xp=ITEM_GACHA_NORMAL_COST_XP,
        normal_cost_xp=ITEM_GACHA_NORMAL_COST_XP,
        premium_cost_xp=ITEM_GACHA_PREMIUM_COST_XP,
        daily_limit=ITEM_GACHA_DAILY_LIMIT,
        wallet=_wallet_out(wallet),
    )


@router.post("/item-gacha/spends", response_model=MinecraftItemGachaSpendOut)
async def request_minecraft_item_gacha_spend(
    payload: MinecraftItemGachaSpendIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftItemGachaSpendOut:
    wallet = await _shop_wallet(db, guild_id=payload.guild_id, user_id=payload.user_id)
    result = await request_item_gacha_spend(
        db,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        request_id=payload.request_id,
        minecraft_account_id=payload.minecraft_account_id,
        draw_day=payload.draw_day,
        draw_category=payload.draw_category,
        expected_cost_xp=payload.expected_cost_xp,
        total_xp=wallet.total_xp,
    )
    return MinecraftItemGachaSpendOut(
        status=result.status,
        message=result.message,
        cost_xp=result.cost_xp,
        wallet_before=_wallet_out(result.wallet_before),
        wallet_after=_wallet_out(result.wallet_after),
    )


async def _item_gacha_spend_action(
    action: str,
    request_id: str,
    payload: MinecraftItemGachaSpendActionIn,
    db: AsyncSession,
) -> Response:
    if action == "complete":
        changed = await complete_item_gacha_spend(
            db,
            guild_id=payload.guild_id,
            user_id=payload.user_id,
            request_id=request_id,
        )
    else:
        changed = await cancel_item_gacha_spend(
            db,
            guild_id=payload.guild_id,
            user_id=payload.user_id,
            request_id=request_id,
        )
    if not changed:
        raise HTTPException(status_code=409, detail="Item gacha spend state changed")
    if action == "complete":
        await request_level_role_sync(db, payload.guild_id)
    return Response(status_code=204)


@router.post("/item-gacha/spends/{request_id}/complete", status_code=204)
async def complete_minecraft_item_gacha_spend(
    request_id: str,
    payload: MinecraftItemGachaSpendActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _item_gacha_spend_action("complete", request_id, payload, db)


@router.post("/item-gacha/spends/{request_id}/cancel", status_code=204)
async def cancel_minecraft_item_gacha_spend(
    request_id: str,
    payload: MinecraftItemGachaSpendActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _item_gacha_spend_action("cancel", request_id, payload, db)


@router.post("/voice-heartbeats", response_model=MinecraftVoiceHeartbeatOut)
async def create_minecraft_voice_heartbeat(
    payload: MinecraftVoiceHeartbeatIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftVoiceHeartbeatOut:
    levels_before = await get_user_lifetime_levels(
        db, payload.guild_id, payload.user_id, include_live_voice=False
    )
    result = await record_minecraft_voice_heartbeat(
        db,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        minecraft_account_id=payload.minecraft_account_id,
        observed_at=payload.observed_at,
    )
    if result.awarded_bonus_seconds > 0:
        levels_after = await get_user_lifetime_levels(
            db, payload.guild_id, payload.user_id, include_live_voice=False
        )
        previous_level = levels_before.total.level if levels_before is not None else 0
        if levels_after is not None and levels_after.total.level > previous_level:
            await enqueue_minecraft_level_up_from_meta(
                db,
                guild_id=payload.guild_id,
                user_id=payload.user_id,
                level=levels_after.total.level,
            )
    return MinecraftVoiceHeartbeatOut(
        awarded_bonus_seconds=result.awarded_bonus_seconds,
        bonus_active=result.bonus_active,
        duplicate=result.duplicate,
    )


@router.post("/xp-events", response_model=MinecraftXpEventOut)
async def create_minecraft_xp_event(
    payload: MinecraftXpEventIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftXpEventOut:
    levels_before = await get_user_lifetime_levels(
        db, payload.guild_id, payload.user_id, include_live_voice=False
    )
    result = await record_minecraft_xp(
        db,
        event_id=payload.event_id,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        minecraft_account_id=payload.minecraft_account_id,
        minecraft_xp=payload.minecraft_xp,
        observed_at=payload.observed_at,
    )
    if result.awarded_xp > 0 and not result.duplicate:
        levels_after = await get_user_lifetime_levels(
            db, payload.guild_id, payload.user_id, include_live_voice=False
        )
        previous_level = levels_before.total.level if levels_before is not None else 0
        if levels_after is not None and levels_after.total.level > previous_level:
            await enqueue_minecraft_level_up_from_meta(
                db,
                guild_id=payload.guild_id,
                user_id=payload.user_id,
                level=levels_after.total.level,
            )
    return MinecraftXpEventOut(
        event_id=result.event_id,
        minecraft_xp=result.minecraft_xp,
        awarded_xp=result.awarded_xp,
        daily_awarded_xp=result.daily_awarded_xp,
        daily_limit=None,
        duplicate=result.duplicate,
    )


@router.get("/level-up-events", response_model=list[MinecraftLevelUpEventOut])
async def get_minecraft_level_up_events(
    guild_id: str = Query(pattern=r"^\d+$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[MinecraftLevelUpEventOut]:
    events = await list_pending_minecraft_level_ups(db, guild_id=guild_id, limit=limit)
    return [
        MinecraftLevelUpEventOut(
            id=event.id,
            guild_id=event.guild_id,
            guild_name=event.guild_name,
            user_id=event.user_id,
            display_name=event.display_name,
            level=event.level,
            minecraft_delivered=event.minecraft_delivered_at is not None,
            discord_delivered=event.discord_delivered_at is not None,
        )
        for event in events
    ]


@router.post("/level-up-events/{event_id}/ack", status_code=204)
async def ack_minecraft_level_up_event(
    event_id: int,
    payload: MinecraftLevelUpAckIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await acknowledge_minecraft_level_up(
        db,
        guild_id=payload.guild_id,
        event_id=event_id,
        destination=payload.destination,
    ):
        raise HTTPException(status_code=404, detail="Pending event not found")
    return Response(status_code=204)


@router.get("/xp-exchanges", response_model=list[MinecraftXpExchangeOut])
async def get_minecraft_xp_exchanges(
    guild_id: str = Query(pattern=r"^\d+$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[MinecraftXpExchangeOut]:
    events = await list_pending_exchanges(db, guild_id=guild_id, limit=limit)
    return [
        MinecraftXpExchangeOut(
            id=event.id,
            event_id=event.event_id,
            guild_id=event.guild_id,
            user_id=event.user_id,
            minecraft_account_id=event.minecraft_account_id,
            cost_xp=event.cost_xp,
            reward_xp=event.reward_xp,
            status=event.status,
        )
        for event in events
    ]


@router.get("/resource-exchanges", response_model=list[MinecraftResourceExchangeOut])
async def get_minecraft_resource_exchanges(
    guild_id: str = Query(pattern=r"^\d+$"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[MinecraftResourceExchangeOut]:
    events = await list_pending_resource_exchanges(db, guild_id=guild_id, limit=limit)
    return [
        MinecraftResourceExchangeOut(
            id=event.id,
            event_id=event.event_id,
            guild_id=event.guild_id,
            user_id=event.user_id,
            minecraft_account_id=event.minecraft_account_id,
            item_id=event.item_id,
            item_name=event.item_name,
            item_count=event.item_count,
            cost_xp=event.cost_xp,
            status=event.status,
        )
        for event in events
    ]


async def _exchange_action(
    action: str,
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession,
) -> Response:
    if action in {"claim", "complete"} and payload.claim_token is None:
        raise HTTPException(status_code=422, detail="claim_token is required")
    if action == "claim":
        assert payload.claim_token is not None
        changed = await claim_exchange(
            db,
            guild_id=payload.guild_id,
            exchange_id=event_id,
            claim_token=payload.claim_token,
        )
    elif action == "complete":
        assert payload.claim_token is not None
        changed = await complete_exchange(
            db,
            guild_id=payload.guild_id,
            exchange_id=event_id,
            claim_token=payload.claim_token,
        )
    else:
        changed = await cancel_exchange(
            db,
            guild_id=payload.guild_id,
            exchange_id=event_id,
            claim_token=payload.claim_token,
        )
    if not changed:
        raise HTTPException(status_code=409, detail="Exchange state changed")
    if action == "complete":
        await request_level_role_sync(db, payload.guild_id)
    return Response(status_code=204)


@router.post("/xp-exchanges/{event_id}/claim", status_code=204)
async def claim_minecraft_xp_exchange(
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _exchange_action("claim", event_id, payload, db)


@router.post("/xp-exchanges/{event_id}/complete", status_code=204)
async def complete_minecraft_xp_exchange(
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _exchange_action("complete", event_id, payload, db)


@router.post("/xp-exchanges/{event_id}/cancel", status_code=204)
async def cancel_minecraft_xp_exchange(
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _exchange_action("cancel", event_id, payload, db)


async def _resource_exchange_action(
    action: str,
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession,
) -> Response:
    if action in {"claim", "complete"} and payload.claim_token is None:
        raise HTTPException(status_code=422, detail="claim_token is required")
    if action == "claim":
        assert payload.claim_token is not None
        changed = await claim_resource_exchange(
            db,
            guild_id=payload.guild_id,
            exchange_id=event_id,
            claim_token=payload.claim_token,
        )
    elif action == "complete":
        assert payload.claim_token is not None
        changed = await complete_resource_exchange(
            db,
            guild_id=payload.guild_id,
            exchange_id=event_id,
            claim_token=payload.claim_token,
        )
    else:
        changed = await cancel_resource_exchange(
            db,
            guild_id=payload.guild_id,
            exchange_id=event_id,
            claim_token=payload.claim_token,
        )
    if not changed:
        raise HTTPException(status_code=409, detail="Exchange state changed")
    if action == "complete":
        await request_level_role_sync(db, payload.guild_id)
    return Response(status_code=204)


@router.post("/resource-exchanges/{event_id}/claim", status_code=204)
async def claim_minecraft_resource_exchange(
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _resource_exchange_action("claim", event_id, payload, db)


@router.post("/resource-exchanges/{event_id}/complete", status_code=204)
async def complete_minecraft_resource_exchange(
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _resource_exchange_action("complete", event_id, payload, db)


@router.post("/resource-exchanges/{event_id}/cancel", status_code=204)
async def cancel_minecraft_resource_exchange(
    event_id: int,
    payload: MinecraftXpExchangeActionIn,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await _resource_exchange_action("cancel", event_id, payload, db)
