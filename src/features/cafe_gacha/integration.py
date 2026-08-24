"""Composition boundary for installing Cafe Collection into level-bot processes."""

from __future__ import annotations

from discord.ext import commands
from fastapi import FastAPI

BOT_EXTENSION = "src.cogs.cafe_gacha"
PUBLIC_CAFE_API_PREFIX = "/api/v1/public/cafe-collection"


def install_bot(bot: commands.Bot, *, enabled: bool) -> tuple[str, ...]:
    """Register persistent UI items and return extensions owned by Cafe Collection."""
    if not enabled:
        return ()
    from src.cogs.cafe_gacha import register_cafe_gacha_dynamic_items

    register_cafe_gacha_dynamic_items(bot)
    return (BOT_EXTENSION,)


def public_api_exempt_prefixes(*, enabled: bool) -> tuple[str, ...]:
    """Return unauthenticated public paths only when the API adapter is installed."""
    return (f"{PUBLIC_CAFE_API_PREFIX}/",) if enabled else ()


def install_public_api(app: FastAPI, *, enabled: bool) -> bool:
    """Install the public HTTP adapter and report whether it was enabled."""
    if not enabled:
        return False
    from src.features.cafe_gacha.public_routes import router

    app.include_router(router)
    return True
