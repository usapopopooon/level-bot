from __future__ import annotations

from fastapi import FastAPI

from src.bot import BOT_EXTENSIONS
from src.features.cafe_gacha.integration import (
    PUBLIC_CAFE_API_PREFIX,
    install_public_api,
    public_api_exempt_prefixes,
)


def test_disabled_public_adapter_registers_nothing() -> None:
    app = FastAPI()

    assert install_public_api(app, enabled=False) is False
    assert public_api_exempt_prefixes(enabled=False) == ()
    assert all(
        not getattr(route, "path", "").startswith(PUBLIC_CAFE_API_PREFIX)
        for route in app.routes
    )


def test_level_bot_does_not_install_cafe_discord_extensions() -> None:
    assert all(
        not extension.startswith("src.cogs.cafe_gacha") for extension in BOT_EXTENSIONS
    )


def test_enabled_public_api_registers_routes_and_auth_exemption() -> None:
    app = FastAPI()

    assert install_public_api(app, enabled=True) is True
    assert public_api_exempt_prefixes(enabled=True) == (f"{PUBLIC_CAFE_API_PREFIX}/",)
    assert any(
        getattr(route, "path", "") == f"{PUBLIC_CAFE_API_PREFIX}/catalog"
        for route in app.routes
    )
