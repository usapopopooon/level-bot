from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.features.color_role_shop.service import (
    ColorRoleExchangeResult,
    exchange_color_role,
    upsert_color_role_item,
    wallet_for_user,
)


async def _noop_role_mutator(_role_id: str, _reason: str) -> None:
    return None


def _failing_role_mutator(_role_id: str, _reason: str) -> Awaitable[None]:
    msg = "role mutation failed"
    raise RuntimeError(msg)


async def _exchange(
    db_session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    item_id: int,
    total_xp: int,
    grant_role: Callable[[str, str], Awaitable[None]] = _noop_role_mutator,
    remove_role: Callable[[str, str], Awaitable[None]] = _noop_role_mutator,
) -> ColorRoleExchangeResult:
    return await exchange_color_role(
        db_session,
        guild_id=guild_id,
        user_id=user_id,
        item_id=item_id,
        total_xp=total_xp,
        grant_role=grant_role,
        remove_role=remove_role,
    )


async def test_exchange_color_role_consumes_available_xp(
    db_session: AsyncSession,
) -> None:
    item = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2001",
        label="常連",
        cost_xp=300,
        description="常連ロール",
    )

    result = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=item.id,
        total_xp=1000,
    )
    wallet = await wallet_for_user(
        db_session,
        guild_id="1001",
        user_id="3001",
        total_xp=1000,
    )

    assert result.status == "purchased"
    assert wallet.spent_xp == 300
    assert wallet.available_xp == 700


async def test_exchange_color_role_rejects_when_xp_is_insufficient(
    db_session: AsyncSession,
) -> None:
    item = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2001",
        label="常連",
        cost_xp=300,
        description=None,
    )

    result = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=item.id,
        total_xp=299,
    )
    wallet = await wallet_for_user(
        db_session,
        guild_id="1001",
        user_id="3001",
        total_xp=299,
    )

    assert result.status == "insufficient_xp"
    assert wallet.spent_xp == 0
    assert wallet.available_xp == 299


async def test_upsert_color_role_item_rejects_free_exchange(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="cost_xp"):
        await upsert_color_role_item(
            db_session,
            guild_id="1001",
            role_id="2001",
            label="無料色",
            cost_xp=0,
            description=None,
        )


async def test_switching_back_to_previous_color_consumes_xp_again(
    db_session: AsyncSession,
) -> None:
    red = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2001",
        label="赤",
        cost_xp=100,
        description=None,
    )
    blue = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2002",
        label="青",
        cost_xp=150,
        description=None,
    )

    first = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=red.id,
        total_xp=1000,
    )
    second = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=blue.id,
        total_xp=1000,
    )
    third = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=red.id,
        total_xp=1000,
    )
    wallet = await wallet_for_user(
        db_session,
        guild_id="1001",
        user_id="3001",
        total_xp=1000,
    )

    assert first.status == "purchased"
    assert second.status == "purchased"
    assert third.status == "purchased"
    assert wallet.spent_xp == 350
    assert wallet.available_xp == 650


async def test_exchange_color_role_removes_other_exchange_roles(
    db_session: AsyncSession,
) -> None:
    red = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2001",
        label="赤",
        cost_xp=100,
        description=None,
    )
    blue = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2002",
        label="青",
        cost_xp=150,
        description=None,
    )
    removed_role_ids: list[str] = []

    await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=red.id,
        total_xp=1000,
    )
    result = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=blue.id,
        total_xp=1000,
        remove_role=lambda role_id, _reason: _record_removed_role(
            removed_role_ids,
            role_id,
        ),
    )
    wallet = await wallet_for_user(
        db_session,
        guild_id="1001",
        user_id="3001",
        total_xp=1000,
    )

    assert result.status == "purchased"
    assert removed_role_ids == ["2001"]
    assert wallet.spent_xp == 250
    assert wallet.available_xp == 750


async def _record_removed_role(removed_role_ids: list[str], role_id: str) -> None:
    removed_role_ids.append(role_id)


async def test_exchange_color_role_does_not_consume_xp_when_role_update_fails(
    db_session: AsyncSession,
) -> None:
    item = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2001",
        label="常連",
        cost_xp=300,
        description=None,
    )

    result = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=item.id,
        total_xp=1000,
        grant_role=_failing_role_mutator,
    )
    wallet = await wallet_for_user(
        db_session,
        guild_id="1001",
        user_id="3001",
        total_xp=1000,
    )

    assert result.status == "role_update_failed"
    assert wallet.spent_xp == 0


async def test_exchange_color_role_does_not_grant_new_role_when_remove_fails(
    db_session: AsyncSession,
) -> None:
    red = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2001",
        label="赤",
        cost_xp=100,
        description=None,
    )
    blue = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2002",
        label="青",
        cost_xp=150,
        description=None,
    )
    granted_role_ids: list[str] = []

    await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=red.id,
        total_xp=1000,
    )
    result = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=blue.id,
        total_xp=1000,
        grant_role=lambda role_id, _reason: _record_granted_role(
            granted_role_ids,
            role_id,
        ),
        remove_role=_failing_role_mutator,
    )
    wallet = await wallet_for_user(
        db_session,
        guild_id="1001",
        user_id="3001",
        total_xp=1000,
    )

    assert result.status == "role_update_failed"
    assert granted_role_ids == []
    assert wallet.spent_xp == 100
    assert wallet.available_xp == 900


async def test_exchange_color_role_restores_removed_roles_when_grant_fails(
    db_session: AsyncSession,
) -> None:
    red = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2001",
        label="赤",
        cost_xp=100,
        description=None,
    )
    blue = await upsert_color_role_item(
        db_session,
        guild_id="1001",
        role_id="2002",
        label="青",
        cost_xp=150,
        description=None,
    )
    removed_role_ids: list[str] = []
    granted_role_ids: list[str] = []

    await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=red.id,
        total_xp=1000,
    )

    async def fail_only_for_blue(role_id: str, _reason: str) -> None:
        if role_id == "2002":
            msg = "cannot grant blue"
            raise RuntimeError(msg)
        granted_role_ids.append(role_id)

    result = await _exchange(
        db_session,
        guild_id="1001",
        user_id="3001",
        item_id=blue.id,
        total_xp=1000,
        grant_role=fail_only_for_blue,
        remove_role=lambda role_id, _reason: _record_removed_role(
            removed_role_ids,
            role_id,
        ),
    )
    wallet = await wallet_for_user(
        db_session,
        guild_id="1001",
        user_id="3001",
        total_xp=1000,
    )

    assert result.status == "role_update_failed"
    assert removed_role_ids == ["2001"]
    assert granted_role_ids == ["2001"]
    assert wallet.spent_xp == 100
    assert wallet.available_xp == 900


async def _record_granted_role(granted_role_ids: list[str], role_id: str) -> None:
    granted_role_ids.append(role_id)
