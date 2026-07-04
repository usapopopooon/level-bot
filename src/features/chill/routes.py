"""Chill-place API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.chill import service as chill_service
from src.features.chill.presets import (
    ChillDisplay,
    ChillPlace,
    format_chill_choice_name,
    format_chill_place_name,
)
from src.features.chill.schemas import (
    ChillDisplayOut,
    ChillLevelOut,
    ChillPlaceOptionsOut,
    ChillPlaceOut,
    ChillPlaceOverrideIn,
    ChillPlaceOverrideOut,
    ChillPlaceSelectionIn,
    ChillPlaceSelectionOut,
)
from src.web.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["chill"])

_CHILL_CACHE_CONTROL = "private, max-age=30"


def _place_out(place: ChillPlace) -> ChillPlaceOut:
    return ChillPlaceOut(
        required_level=place.required_level,
        name=place.name,
        emoji=place.emoji,
        display_name=format_chill_place_name(place),
        choice_label=format_chill_choice_name(place),
        tags=list(place.tags),
        description=place.description,
    )


def _level_out(level: chill_service.ChillLevel) -> ChillLevelOut:
    return ChillLevelOut(
        level=level.level,
        progress=level.progress,
        progress_percent=int(level.progress * 100),
    )


def _display_out(display: ChillDisplay | None) -> ChillDisplayOut | None:
    if display is None:
        return None
    return ChillDisplayOut(
        current=_place_out(display.current) if display.current is not None else None,
        next=_place_out(display.next_place) if display.next_place is not None else None,
        selected_locked=display.selected_locked,
    )


@router.get(
    "/guilds/{guild_id}/chill-places",
    response_model=list[ChillPlaceOut],
    summary="ギルドのチル場所一覧",
)
async def get_guild_chill_places(
    guild_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> list[ChillPlaceOut]:
    response.headers["Cache-Control"] = _CHILL_CACHE_CONTROL
    places = await chill_service.list_chill_places(db, guild_id)
    return [_place_out(place) for place in places]


@router.put(
    "/guilds/{guild_id}/chill-places/{required_level}",
    response_model=ChillPlaceOverrideOut,
    summary="ギルドのチル場所カスタムを追加・更新",
)
async def put_guild_chill_place(
    guild_id: str,
    required_level: int,
    payload: ChillPlaceOverrideIn,
    db: AsyncSession = Depends(get_db),
) -> ChillPlaceOverrideOut:
    try:
        row = await chill_service.upsert_guild_chill_place(
            db,
            guild_id,
            required_level,
            payload.name,
            payload.emoji,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ChillPlaceOverrideOut(
        guild_id=row.guild_id,
        required_level=row.required_level,
        name=row.name,
        emoji=row.emoji,
    )


@router.delete(
    "/guilds/{guild_id}/chill-places/{required_level}",
    status_code=204,
    summary="ギルドのチル場所カスタムを削除",
)
async def delete_guild_chill_place(
    guild_id: str,
    required_level: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await chill_service.remove_guild_chill_place(db, guild_id, required_level)
    return Response(status_code=204)


@router.get(
    "/guilds/{guild_id}/users/{user_id}/chill-places",
    response_model=ChillPlaceOptionsOut,
    summary="ユーザーが選択可能なチル場所一覧",
)
async def get_user_chill_places(
    guild_id: str,
    user_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ChillPlaceOptionsOut:
    response.headers["Cache-Control"] = _CHILL_CACHE_CONTROL
    try:
        options = await chill_service.get_chill_place_options(db, guild_id, user_id)
    except chill_service.ChillLevelUnavailableError as e:
        raise HTTPException(status_code=424, detail="Current level unavailable") from e
    return ChillPlaceOptionsOut(
        guild_id=options.guild_id,
        user_id=options.user_id,
        level=_level_out(options.level),
        selected_required_level=options.selected_required_level,
        places=[_place_out(place) for place in options.places],
    )


@router.put(
    "/guilds/{guild_id}/users/{user_id}/chill-place",
    response_model=ChillPlaceSelectionOut,
    summary="ユーザーのチル場所選択を更新",
)
async def put_user_chill_place(
    guild_id: str,
    user_id: str,
    payload: ChillPlaceSelectionIn,
    db: AsyncSession = Depends(get_db),
) -> ChillPlaceSelectionOut:
    try:
        selection = await chill_service.set_user_chill_place(
            db,
            guild_id,
            user_id,
            payload.required_level,
        )
    except chill_service.UnknownChillPlaceError as e:
        raise HTTPException(status_code=400, detail="Unknown chill place") from e
    except chill_service.LockedChillPlaceError as e:
        raise HTTPException(status_code=403, detail="Chill place is locked") from e
    except chill_service.ChillLevelUnavailableError as e:
        raise HTTPException(status_code=424, detail="Current level unavailable") from e

    return ChillPlaceSelectionOut(
        guild_id=selection.guild_id,
        user_id=selection.user_id,
        level=_level_out(selection.level),
        selected=_place_out(selection.selected),
        chill_place=_display_out(selection.display),
    )


@router.delete(
    "/guilds/{guild_id}/users/{user_id}/chill-place",
    status_code=204,
    summary="ユーザーのチル場所選択を解除",
)
async def delete_user_chill_place(
    guild_id: str,
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await chill_service.clear_user_chill_place(db, guild_id, user_id)
    return Response(status_code=204)
