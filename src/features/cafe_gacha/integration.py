"""Composition boundary for Cafe Collection's remaining HTTP data adapter."""

from __future__ import annotations

from fastapi import FastAPI

PUBLIC_CAFE_API_PREFIX = "/api/v1/public/cafe-collection"


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
