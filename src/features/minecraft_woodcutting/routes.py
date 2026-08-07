from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.minecraft_woodcutting.schemas import (
    MinecraftWoodcuttingComboEventIn,
    MinecraftWoodcuttingComboEventOut,
)
from src.features.minecraft_woodcutting.service import record_woodcutting_combo_event
from src.web.deps import get_db

router = APIRouter(
    prefix="/api/v1/integrations/minecraft", tags=["minecraft-woodcutting"]
)


@router.post(
    "/woodcutting-combo-events", response_model=MinecraftWoodcuttingComboEventOut
)
async def create_woodcutting_combo_event(
    payload: MinecraftWoodcuttingComboEventIn,
    db: AsyncSession = Depends(get_db),
) -> MinecraftWoodcuttingComboEventOut:
    try:
        result = await record_woodcutting_combo_event(
            db,
            event_id=payload.event_id,
            guild_id=payload.guild_id,
            user_id=payload.user_id,
            minecraft_account_id=payload.minecraft_account_id,
            log_count=payload.log_count,
            combo_count=payload.combo_count,
            reward_xp=payload.reward_xp,
            observed_at=payload.observed_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MinecraftWoodcuttingComboEventOut(
        event_id=result.event_id,
        log_count=result.log_count,
        combo_count=result.combo_count,
        reward_xp=result.reward_xp,
        duplicate=result.duplicate,
    )
