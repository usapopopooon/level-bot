"""Chill-place read/write service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import GuildChillPlace, UserChillPlace
from src.features.chill.presets import (
    ChillDisplay,
    ChillPlace,
    ChillPlaceOverride,
    build_chill_places,
    resolve_chill_display,
)
from src.features.leveling.service import get_user_lifetime_levels


class ChillLevelUnavailableError(Exception):
    """The user's level cannot be resolved."""


class UnknownChillPlaceError(Exception):
    """The requested required_level does not map to a chill place."""


class LockedChillPlaceError(Exception):
    """The requested chill place is above the user's current level."""


@dataclass(frozen=True)
class ChillLevel:
    level: int
    progress: float


@dataclass(frozen=True)
class ChillPlaceOptions:
    guild_id: str
    user_id: str
    level: ChillLevel
    selected_required_level: int | None
    places: tuple[ChillPlace, ...]


@dataclass(frozen=True)
class ChillPlaceSelection:
    guild_id: str
    user_id: str
    level: ChillLevel
    selected: ChillPlace
    display: ChillDisplay | None


def _clean_name(name: str) -> str:
    return name.strip()


def _clean_emoji(emoji: str | None) -> str | None:
    if emoji is None:
        return None
    cleaned = emoji.strip()
    return cleaned or None


async def list_chill_place_overrides(
    session: AsyncSession,
    guild_id: str,
) -> dict[int, ChillPlaceOverride]:
    result = await session.execute(
        select(GuildChillPlace)
        .where(GuildChillPlace.guild_id == guild_id)
        .order_by(GuildChillPlace.required_level.asc())
    )
    return {
        row.required_level: ChillPlaceOverride(name=row.name, emoji=row.emoji)
        for row in result.scalars().all()
    }


async def list_chill_places(
    session: AsyncSession,
    guild_id: str,
) -> tuple[ChillPlace, ...]:
    overrides = await list_chill_place_overrides(session, guild_id)
    return build_chill_places(overrides)


async def get_user_selected_chill_level(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
) -> int | None:
    result = await session.execute(
        select(UserChillPlace.required_level).where(
            UserChillPlace.guild_id == guild_id,
            UserChillPlace.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _get_current_chill_level(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
) -> ChillLevel:
    levels = await get_user_lifetime_levels(
        session,
        guild_id,
        user_id,
        require_active_member=True,
    )
    if levels is None:
        raise ChillLevelUnavailableError
    return ChillLevel(level=levels.total.level, progress=levels.total.progress)


async def get_chill_place_options(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
) -> ChillPlaceOptions:
    level = await _get_current_chill_level(session, guild_id, user_id)
    selected_level = await get_user_selected_chill_level(session, guild_id, user_id)
    places = await list_chill_places(session, guild_id)
    unlocked = tuple(place for place in places if place.required_level <= level.level)
    return ChillPlaceOptions(
        guild_id=guild_id,
        user_id=user_id,
        level=level,
        selected_required_level=selected_level,
        places=unlocked,
    )


async def set_user_chill_place(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
    required_level: int,
) -> ChillPlaceSelection:
    level = await _get_current_chill_level(session, guild_id, user_id)
    places = await list_chill_places(session, guild_id)
    selected = next(
        (place for place in places if place.required_level == required_level),
        None,
    )
    if selected is None:
        raise UnknownChillPlaceError
    if selected.required_level > level.level:
        raise LockedChillPlaceError

    now = datetime.now(UTC)
    stmt = pg_insert(UserChillPlace).values(
        guild_id=guild_id,
        user_id=user_id,
        required_level=selected.required_level,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_user_chill_place",
        set_={"required_level": selected.required_level, "updated_at": now},
    )
    await session.execute(stmt)
    await session.commit()

    display = resolve_chill_display(
        places,
        level=level.level,
        selected_level=selected.required_level,
    )
    return ChillPlaceSelection(
        guild_id=guild_id,
        user_id=user_id,
        level=level,
        selected=selected,
        display=display,
    )


async def clear_user_chill_place(
    session: AsyncSession,
    guild_id: str,
    user_id: str,
) -> bool:
    stmt = delete(UserChillPlace).where(
        UserChillPlace.guild_id == guild_id,
        UserChillPlace.user_id == user_id,
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return (result.rowcount or 0) > 0


async def upsert_guild_chill_place(
    session: AsyncSession,
    guild_id: str,
    required_level: int,
    name: str,
    emoji: str | None,
) -> GuildChillPlace:
    clean_name = _clean_name(name)
    clean_emoji = _clean_emoji(emoji)
    if required_level < 1:
        msg = "required_level must be >= 1"
        raise ValueError(msg)
    if not clean_name:
        msg = "name must not be empty"
        raise ValueError(msg)

    now = datetime.now(UTC)
    stmt = pg_insert(GuildChillPlace).values(
        guild_id=guild_id,
        required_level=required_level,
        name=clean_name,
        emoji=clean_emoji,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_guild_chill_place",
        set_={"name": clean_name, "emoji": clean_emoji, "updated_at": now},
    )
    await session.execute(stmt)
    await session.commit()
    result = await session.execute(
        select(GuildChillPlace).where(
            GuildChillPlace.guild_id == guild_id,
            GuildChillPlace.required_level == required_level,
        )
    )
    row = result.scalar_one()
    return row


async def remove_guild_chill_place(
    session: AsyncSession,
    guild_id: str,
    required_level: int,
) -> bool:
    stmt = delete(GuildChillPlace).where(
        GuildChillPlace.guild_id == guild_id,
        GuildChillPlace.required_level == required_level,
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    await session.commit()
    return (result.rowcount or 0) > 0
