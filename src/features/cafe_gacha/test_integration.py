from __future__ import annotations

from typing import cast
from unittest.mock import Mock

import pytest
from discord.ext import commands
from fastapi import FastAPI

from src.features.cafe_gacha.integration import (
    BOT_EXTENSION,
    PUBLIC_CAFE_API_PREFIX,
    install_bot,
    install_public_api,
    public_api_exempt_prefixes,
)


def test_disabled_adapters_register_nothing() -> None:
    bot = cast(commands.Bot, Mock())
    app = FastAPI()

    assert install_bot(bot, enabled=False) == ()
    assert install_public_api(app, enabled=False) is False
    assert public_api_exempt_prefixes(enabled=False) == ()
    assert all(
        not getattr(route, "path", "").startswith(PUBLIC_CAFE_API_PREFIX)
        for route in app.routes
    )


def test_enabled_bot_adapter_registers_dynamic_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register = Mock()
    monkeypatch.setattr(
        "src.cogs.cafe_gacha.register_cafe_gacha_dynamic_items",
        register,
    )
    bot = cast(commands.Bot, Mock())

    assert install_bot(bot, enabled=True) == (BOT_EXTENSION,)
    register.assert_called_once_with(bot)


def test_enabled_public_api_registers_routes_and_auth_exemption() -> None:
    app = FastAPI()

    assert install_public_api(app, enabled=True) is True
    assert public_api_exempt_prefixes(enabled=True) == (f"{PUBLIC_CAFE_API_PREFIX}/",)
    assert any(
        getattr(route, "path", "") == f"{PUBLIC_CAFE_API_PREFIX}/catalog"
        for route in app.routes
    )
