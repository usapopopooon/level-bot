from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.marimo_xp.schemas import MarimoXpEventIn, MarimoXpEventOut
from src.features.marimo_xp.service import record_marimo_xp
from src.web.deps import get_db

router = APIRouter(
    prefix="/api/v1/integrations/marimo",
    tags=["marimo-xp"],
)


@router.post("/watering-events", response_model=MarimoXpEventOut)
async def create_marimo_xp_event(
    payload: MarimoXpEventIn,
    db: AsyncSession = Depends(get_db),
) -> MarimoXpEventOut:
    try:
        result = await record_marimo_xp(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MarimoXpEventOut(
        event_id=result.event_id,
        awarded_xp=result.awarded_xp,
        duplicate=result.duplicate,
    )
