from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.minecraft_fishing.schemas import (
    MinecraftFishingComboEventIn,
    MinecraftFishingComboEventOut,
)
from src.features.minecraft_fishing.service import record_fishing_combo_event
from src.web.deps import get_db

router = APIRouter(
    prefix="/api/v1/integrations/minecraft",
    tags=["minecraft-fishing"],
)


@router.post(
    "/fishing-combo-events",
    response_model=MinecraftFishingComboEventOut,
)
async def create_fishing_combo_event(
    payload: MinecraftFishingComboEventIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftFishingComboEventOut:
    try:
        result = await record_fishing_combo_event(
            db,
            event_id=payload.event_id,
            guild_id=payload.guild_id,
            user_id=payload.user_id,
            minecraft_account_id=payload.minecraft_account_id,
            catch_count=payload.catch_count,
            combo_count=payload.combo_count,
            reward_xp=payload.reward_xp,
            observed_at=payload.observed_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MinecraftFishingComboEventOut(
        event_id=result.event_id,
        catch_count=result.catch_count,
        combo_count=result.combo_count,
        reward_xp=result.reward_xp,
        duplicate=result.duplicate,
    )
