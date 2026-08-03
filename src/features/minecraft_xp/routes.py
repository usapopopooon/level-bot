from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.leveling.service import get_user_lifetime_levels
from src.features.minecraft_xp.schemas import (
    MinecraftLevelUpAckIn,
    MinecraftLevelUpEventOut,
    MinecraftXpEventIn,
    MinecraftXpEventOut,
)
from src.features.minecraft_xp.service import (
    acknowledge_minecraft_level_up,
    enqueue_minecraft_level_up_from_meta,
    list_pending_minecraft_level_ups,
    record_minecraft_xp,
)
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1/integrations/minecraft", tags=["minecraft-xp"])


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
