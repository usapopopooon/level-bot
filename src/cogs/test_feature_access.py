from types import SimpleNamespace
from typing import cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest

from src.cogs import feature_access
from src.features.feature_access import service


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Response:
    def __init__(self) -> None:
        self.send_message = AsyncMock()

    def is_done(self) -> bool:
        return False


async def test_matching_member_role_allows_feature_and_maps_ids_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_roles = AsyncMock(return_value=("2001", "2002"))
    response = _Response()
    member = SimpleNamespace(
        id=3001,
        roles=[SimpleNamespace(id=1001), SimpleNamespace(id=2002)],
    )
    guild = SimpleNamespace(id=1001, get_member=lambda _user_id: member)
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=guild,
            user=SimpleNamespace(id=3001),
            permissions=SimpleNamespace(administrator=False, manage_guild=False),
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
        ),
    )
    monkeypatch.setattr(feature_access, "async_session", _SessionContext)
    monkeypatch.setattr(service, "list_access_role_ids", list_roles)

    allowed = await feature_access.ensure_feature_access(
        interaction,
        guild_id=1001,
        feature=service.CAFE_GACHA,
    )

    assert allowed is True
    list_roles.assert_awaited_once_with(
        ANY,
        guild_id="1001",
        feature=service.CAFE_GACHA,
    )
    response.send_message.assert_not_awaited()


async def test_nonmatching_member_is_denied_without_role_mentions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Response()
    member = SimpleNamespace(id=3001, roles=[SimpleNamespace(id=9999)])
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001, get_member=lambda _user_id: member),
            user=SimpleNamespace(id=3001),
            permissions=SimpleNamespace(administrator=False, manage_guild=False),
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
        ),
    )
    monkeypatch.setattr(feature_access, "async_session", _SessionContext)
    monkeypatch.setattr(
        service,
        "list_access_role_ids",
        AsyncMock(return_value=("2001", "2002")),
    )

    allowed = await feature_access.ensure_feature_access(
        interaction,
        guild_id="1001",
        feature=service.COLOR_ROLE_SHOP,
    )

    assert allowed is False
    send_call = response.send_message.await_args
    assert send_call is not None
    kwargs = send_call.kwargs
    assert kwargs["ephemeral"] is True
    assert kwargs["allowed_mentions"].roles is False
    assert "<@&2001>" in send_call.args[0]
