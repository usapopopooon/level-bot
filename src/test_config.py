"""Tests for src.config.Settings."""

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


def test_settings_does_not_require_discord_token() -> None:
    """API プロセスは DISCORD_TOKEN なしで Settings をロードできる。

    トークン必須チェックは src/main.py に移ったため、Settings 単体は
    空文字でも例外を上げない。
    """
    s = Settings(discord_token="")
    assert s.discord_token == ""


def test_user_stats_site_settings_are_optional() -> None:
    s = Settings()
    assert s.user_stats_site_guild_id == ""
    assert s.user_stats_site_base_url == ""


def test_user_stats_site_settings_can_be_configured() -> None:
    s = Settings(
        user_stats_site_guild_id="1168847276291137586",
        user_stats_site_base_url="https://chill-cafe.site/u",
    )
    assert s.user_stats_site_guild_id == "1168847276291137586"
    assert s.user_stats_site_base_url == "https://chill-cafe.site/u"
