"""Tests for src.config.Settings."""

import pytest

from src.config import Settings


def test_async_database_url_passthrough_for_asyncpg() -> None:
    s = Settings(
        discord_token="x",
        database_url="postgresql+asyncpg://u:p@h/db",
    )
    assert s.async_database_url == "postgresql+asyncpg://u:p@h/db"


def test_async_database_url_normalizes_postgres_scheme() -> None:
    s = Settings(discord_token="x", database_url="postgres://u:p@h/db")
    assert s.async_database_url == "postgresql+asyncpg://u:p@h/db"


def test_async_database_url_normalizes_postgresql_scheme() -> None:
    s = Settings(discord_token="x", database_url="postgresql://u:p@h/db")
    assert s.async_database_url == "postgresql+asyncpg://u:p@h/db"


def test_missing_discord_token_raises() -> None:
    with pytest.raises(ValueError, match="DISCORD_TOKEN"):
        Settings(discord_token="   ")
