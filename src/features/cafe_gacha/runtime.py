"""Dependency selection for the in-process Cafe Collection implementation."""

from __future__ import annotations

from src.features.cafe_gacha.ports import CafeGachaDependencies


def default_dependencies() -> CafeGachaDependencies:
    """Load level-bot adapters lazily so core modules depend only on Cafe ports."""
    from src.features.cafe_gacha.adapters.level_bot import LEVEL_BOT_DEPENDENCIES

    return LEVEL_BOT_DEPENDENCIES
