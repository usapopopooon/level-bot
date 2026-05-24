from src.cogs import user_commands


def test_build_user_stats_url_requires_config(monkeypatch) -> None:
    monkeypatch.setattr(user_commands.settings, "user_stats_site_base_url", "")
    monkeypatch.setattr(user_commands.settings, "user_stats_site_guild_id", "42")

    assert user_commands.build_user_stats_url("42", 100) is None


def test_build_user_stats_url_requires_matching_guild(monkeypatch) -> None:
    monkeypatch.setattr(
        user_commands.settings, "user_stats_site_base_url", "https://stats.example.com"
    )
    monkeypatch.setattr(user_commands.settings, "user_stats_site_guild_id", "42")

    assert user_commands.build_user_stats_url("43", 100) is None


def test_build_user_stats_url_adds_user_level_path(monkeypatch) -> None:
    monkeypatch.setattr(
        user_commands.settings, "user_stats_site_base_url", "https://stats.example.com"
    )
    monkeypatch.setattr(user_commands.settings, "user_stats_site_guild_id", "42")

    assert (
        user_commands.build_user_stats_url("42", 100)
        == "https://stats.example.com/u/100/level?days=30"
    )


def test_build_user_stats_url_does_not_duplicate_u_path(monkeypatch) -> None:
    monkeypatch.setattr(
        user_commands.settings, "user_stats_site_base_url", "https://stats.example.com/u"
    )
    monkeypatch.setattr(user_commands.settings, "user_stats_site_guild_id", "42")

    assert (
        user_commands.build_user_stats_url("42", 100)
        == "https://stats.example.com/u/100/level?days=30"
    )
