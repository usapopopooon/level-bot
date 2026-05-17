"""Shared definitions for level-role award behavior."""

from __future__ import annotations

from typing import Literal, cast

type LevelRoleGrantMode = Literal["replace", "stack"]

LEVEL_ROLE_GRANT_MODE_REPLACE: LevelRoleGrantMode = "replace"
LEVEL_ROLE_GRANT_MODE_STACK: LevelRoleGrantMode = "stack"
LEVEL_ROLE_GRANT_MODES: frozenset[str] = frozenset(
    (LEVEL_ROLE_GRANT_MODE_REPLACE, LEVEL_ROLE_GRANT_MODE_STACK)
)
DEFAULT_LEVEL_ROLE_GRANT_MODE: LevelRoleGrantMode = LEVEL_ROLE_GRANT_MODE_REPLACE

LEVEL_ROLE_GRANT_MODE_CHECK_SQL = "grant_mode IN ('replace', 'stack')"


def validate_level_role_grant_mode(value: str) -> LevelRoleGrantMode:
    """Return a typed grant mode or raise ValueError for unknown values."""
    if value not in LEVEL_ROLE_GRANT_MODES:
        allowed = ", ".join(sorted(LEVEL_ROLE_GRANT_MODES))
        raise ValueError(f"grant_mode must be one of: {allowed}")
    return cast(LevelRoleGrantMode, value)
