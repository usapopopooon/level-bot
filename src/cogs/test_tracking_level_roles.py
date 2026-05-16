from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.cogs.tracking import TrackingCog
from src.database.models import LevelRoleAward


class _Role:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


class _Guild:
    def __init__(self, roles: list[_Role]) -> None:
        self.id = 1001
        self._roles = {r.id: r for r in roles}

    def get_role(self, role_id: int) -> _Role | None:
        return self._roles.get(role_id)


@pytest.mark.asyncio
async def test_grant_level_roles_keeps_highest_per_slot_and_removes_lower() -> None:
    role11 = _Role(11)
    role12 = _Role(12)
    role21 = _Role(21)
    role99 = _Role(99)
    guild = _Guild([role11, role12, role21, role99])

    member = SimpleNamespace(
        guild=guild,
        id=2001,
        roles=[role11, role99],
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    rules = [
        LevelRoleAward(guild_id="1001", slot=1, level=3, role_id="11"),
        LevelRoleAward(guild_id="1001", slot=1, level=10, role_id="12"),
        LevelRoleAward(guild_id="1001", slot=2, level=5, role_id="21"),
    ]

    changed = await cog._grant_level_roles_from_rules(
        member=member,  # type: ignore[arg-type]
        level=10,
        rules=rules,
    )

    assert changed is True
    member.add_roles.assert_awaited_once()
    added_ids = {r.id for r in member.add_roles.await_args.args}
    assert added_ids == {12, 21}

    member.remove_roles.assert_awaited_once()
    removed_ids = {r.id for r in member.remove_roles.await_args.args}
    assert removed_ids == {11}


@pytest.mark.asyncio
async def test_grant_level_roles_noop_when_member_already_matches_selection() -> None:
    role12 = _Role(12)
    role21 = _Role(21)
    guild = _Guild([role12, role21])

    member = SimpleNamespace(
        guild=guild,
        id=2001,
        roles=[role12, role21],
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
    )

    cog = TrackingCog(SimpleNamespace())  # type: ignore[arg-type]
    rules = [
        LevelRoleAward(guild_id="1001", slot=1, level=10, role_id="12"),
        LevelRoleAward(guild_id="1001", slot=2, level=5, role_id="21"),
    ]

    changed = await cog._grant_level_roles_from_rules(
        member=member,  # type: ignore[arg-type]
        level=10,
        rules=rules,
    )

    assert changed is False
    member.add_roles.assert_not_awaited()
    member.remove_roles.assert_not_awaited()
