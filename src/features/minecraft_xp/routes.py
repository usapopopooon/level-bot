from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.minecraft_xp.schemas import MinecraftXpEventIn, MinecraftXpEventOut
from src.features.minecraft_xp.service import (
    MINECRAFT_DAILY_AWARD_LIMIT,
    record_minecraft_xp,
)
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1/integrations/minecraft", tags=["minecraft-xp"])


@router.post("/xp-events", response_model=MinecraftXpEventOut)
async def create_minecraft_xp_event(
    payload: MinecraftXpEventIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftXpEventOut:
    result = await record_minecraft_xp(
        db,
        event_id=payload.event_id,
        guild_id=payload.guild_id,
        user_id=payload.user_id,
        minecraft_account_id=payload.minecraft_account_id,
        minecraft_xp=payload.minecraft_xp,
        observed_at=payload.observed_at,
    )
    return MinecraftXpEventOut(
        event_id=result.event_id,
        minecraft_xp=result.minecraft_xp,
        awarded_xp=result.awarded_xp,
        daily_awarded_xp=result.daily_awarded_xp,
        daily_limit=MINECRAFT_DAILY_AWARD_LIMIT,
        duplicate=result.duplicate,
    )
