from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.color_role_shop.service import Wallet, wallet_for_user
from src.features.guilds.service import request_level_role_sync
from src.features.leveling.service import get_user_lifetime_levels
from src.features.minecraft_xp.schemas import (
    MinecraftLevelUpAckIn,
    MinecraftLevelUpEventOut,
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
        total_xp = (
            levels.voice.xp
            + levels.text.xp
            + levels.reactions_received.xp
            + levels.reactions_given.xp
            + levels.minecraft.xp
        )
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
