from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import ANY, AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.features.coffee_market.adapters import level_bot_application
from src.features.coffee_market.adapters.level_bot_application import (
    LevelBotCoffeeMarketApplication,
)
from src.features.coffee_market.application import CoffeeMarketApplication
from src.features.coffee_market.contracts import CoffeeMarketUnavailable
from src.features.feature_access import service as feature_access_service


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_level_bot_adapter_implements_public_application_contract() -> None:
    application: CoffeeMarketApplication = LevelBotCoffeeMarketApplication()
    assert application is not None


async def test_access_role_adapter_maps_to_coffee_market_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_access_role = AsyncMock(return_value=True)
    monkeypatch.setattr(level_bot_application, "_market_session", _SessionContext)
    monkeypatch.setattr(
        feature_access_service,
        "add_access_role",
        add_access_role,
    )

    added = await LevelBotCoffeeMarketApplication().add_access_role(
        guild_id="1001",
        role_id="2001",
    )

    assert added is True
    add_access_role.assert_awaited_once_with(
        ANY,
        guild_id="1001",
        feature=feature_access_service.COFFEE_MARKET,
        role_id="2001",
    )


async def test_database_error_is_hidden_behind_application_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _UnavailableSession:
        async def __aenter__(self) -> Any:
            raise SQLAlchemyError("database unavailable")

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        level_bot_application,
        "async_session",
        lambda: _UnavailableSession(),
    )

    with pytest.raises(CoffeeMarketUnavailable):
        await LevelBotCoffeeMarketApplication().quote(
            guild_id="1001",
            market_day=date(2026, 8, 25),
        )
