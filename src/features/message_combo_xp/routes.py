from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.message_combo_xp.schemas import (
    MessageComboXpEventIn,
    MessageComboXpEventOut,
)
from src.features.message_combo_xp.service import record_message_combo_xp
from src.web.deps import get_db

router = APIRouter(
    prefix="/api/v1/integrations/itsuka",
    tags=["message-combo-xp"],
)


@router.post("/message-combo-xp-events", response_model=MessageComboXpEventOut)
async def create_message_combo_xp_event(
    payload: MessageComboXpEventIn,
    db: AsyncSession = Depends(get_db),
) -> MessageComboXpEventOut:
    try:
        result = await record_message_combo_xp(
            db,
            event_id=payload.event_id,
            guild_id=payload.guild_id,
            user_id=payload.user_id,
            channel_id=payload.channel_id,
            config_id=payload.config_id,
            streak_days=payload.streak_days,
            observed_at=payload.observed_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MessageComboXpEventOut(
        event_id=result.event_id,
        streak_days=result.streak_days,
        awarded_xp=result.awarded_xp,
        duplicate=result.duplicate,
    )
