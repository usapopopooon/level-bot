from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.features.coffee_market.adapters import level_bot_application
from src.features.coffee_market.adapters.level_bot_application import (
    LevelBotCoffeeMarketApplication,
)
from src.features.coffee_market.application import CoffeeMarketApplication
from src.features.coffee_market.contracts import CoffeeMarketUnavailable


def test_level_bot_adapter_implements_public_application_contract() -> None:
    application: CoffeeMarketApplication = LevelBotCoffeeMarketApplication()
    assert application is not None


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
