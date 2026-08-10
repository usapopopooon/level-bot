import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.feature_access.service import (
    CAFE_GACHA,
    COLOR_ROLE_SHOP,
    add_access_role,
    list_access_role_ids,
    member_has_access,
    remove_access_role,
)


async def test_access_roles_are_idempotent_and_isolated_by_feature(
    db_session: AsyncSession,
) -> None:
    assert await add_access_role(
        db_session,
        guild_id="1001",
        feature=CAFE_GACHA,
        role_id="2001",
    )
    assert not await add_access_role(
        db_session,
        guild_id="1001",
        feature=CAFE_GACHA,
        role_id="2001",
    )
    assert await add_access_role(
        db_session,
        guild_id="1001",
        feature=CAFE_GACHA,
        role_id="2002",
    )
    assert await add_access_role(
        db_session,
        guild_id="1001",
        feature=COLOR_ROLE_SHOP,
        role_id="3001",
    )

    assert await list_access_role_ids(
        db_session,
        guild_id="1001",
        feature=CAFE_GACHA,
    ) == ("2001", "2002")
    assert await list_access_role_ids(
        db_session,
        guild_id="1001",
        feature=COLOR_ROLE_SHOP,
    ) == ("3001",)

    assert await remove_access_role(
        db_session,
        guild_id="1001",
        feature=CAFE_GACHA,
        role_id="2001",
    )
    assert not await remove_access_role(
        db_session,
        guild_id="1001",
        feature=CAFE_GACHA,
        role_id="2001",
    )
    assert await list_access_role_ids(
        db_session,
        guild_id="1001",
        feature=CAFE_GACHA,
    ) == ("2002",)


@pytest.mark.parametrize(
    ("allowed_role_ids", "member_role_ids", "can_manage_guild", "expected"),
    [
        ((), set(), False, True),
        (("2001", "2002"), {"2002"}, False, True),
        (("2001", "2002"), {"9999"}, False, False),
        (("2001", "2002"), set(), True, True),
    ],
)
def test_member_access_uses_unconfigured_or_any_role_or_manager(
    allowed_role_ids: tuple[str, ...],
    member_role_ids: set[str],
    can_manage_guild: bool,
    expected: bool,
) -> None:
    assert (
        member_has_access(
            allowed_role_ids=allowed_role_ids,
            member_role_ids=member_role_ids,
            can_manage_guild=can_manage_guild,
        )
        is expected
    )
