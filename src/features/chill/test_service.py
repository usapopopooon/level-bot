from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, UserChillPlace
from src.features.chill import service
from src.features.chill.presets import ChillPlaceOverride, build_chill_places
from src.features.meta.service import upsert_guild_member_meta


async def _seed_level(db_session: AsyncSession, guild_id: str, user_id: str) -> None:
    await upsert_guild_member_meta(
        db_session,
        guild_id=guild_id,
        user_id=user_id,
        is_active=True,
    )
    db_session.add(
        DailyStat(
            guild_id=guild_id,
            user_id=user_id,
            channel_id="3001",
            stat_date=date(2026, 7, 4),
            message_count=500,
        )
    )
    await db_session.commit()


async def test_build_chill_places_keeps_default_metadata() -> None:
    places = build_chill_places({2: ChillPlaceOverride(name="秘密のソファ")})
    place = next(p for p in places if p.required_level == 2)

    assert place.name == "秘密のソファ"
    assert place.emoji == "🛋️"
    assert place.description is not None


async def test_get_chill_place_options_returns_unlocked_places(
    db_session: AsyncSession,
) -> None:
    await _seed_level(db_session, "1001", "2001")

    options = await service.get_chill_place_options(db_session, "1001", "2001")

    assert options.level.level >= 1
    assert options.places
    assert all(p.required_level <= options.level.level for p in options.places)


async def test_set_user_chill_place_persists_selection(
    db_session: AsyncSession,
) -> None:
    await _seed_level(db_session, "1001", "2001")

    selection = await service.set_user_chill_place(db_session, "1001", "2001", 1)

    assert selection.selected.required_level == 1
    row = (
        await db_session.execute(
            select(UserChillPlace).where(
                UserChillPlace.guild_id == "1001",
                UserChillPlace.user_id == "2001",
            )
        )
    ).scalar_one()
    assert row.required_level == 1


async def test_set_user_chill_place_rejects_locked_place(
    db_session: AsyncSession,
) -> None:
    await _seed_level(db_session, "1001", "2001")

    with pytest.raises(service.LockedChillPlaceError):
        await service.set_user_chill_place(db_session, "1001", "2001", 100)


async def test_clear_user_chill_place_removes_selection(
    db_session: AsyncSession,
) -> None:
    await _seed_level(db_session, "1001", "2001")
    await service.set_user_chill_place(db_session, "1001", "2001", 1)

    removed = await service.clear_user_chill_place(db_session, "1001", "2001")

    assert removed is True
    rows = (
        await db_session.execute(
            select(UserChillPlace).where(
                UserChillPlace.guild_id == "1001",
                UserChillPlace.user_id == "2001",
            )
        )
    ).scalars()
    assert list(rows) == []
