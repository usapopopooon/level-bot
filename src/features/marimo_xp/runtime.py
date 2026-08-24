"""Dependency selection for the in-process marimo integration."""

from __future__ import annotations

from src.features.marimo_xp.ports import MarimoXpDependencies


def default_dependencies() -> MarimoXpDependencies:
    from src.features.marimo_xp.adapters.level_bot import LEVEL_BOT_DEPENDENCIES

    return LEVEL_BOT_DEPENDENCIES
