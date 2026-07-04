import asyncio

import discord
import pytest

from src.cogs.level_actions import build_level_action_view, build_user_stats_url
from src.config import settings


def _component_label(component: object) -> str | None:
    return getattr(component, "label", None) or getattr(
        getattr(component, "item", None), "label", None
    )


def test_build_user_stats_url_requires_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "user_stats_site_base_url", "")
    monkeypatch.setattr(settings, "user_stats_site_guild_id", "42")

    assert build_user_stats_url("42", 100) is None


def test_build_user_stats_url_requires_matching_guild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "user_stats_site_base_url", "https://stats.example.com"
    )
    monkeypatch.setattr(settings, "user_stats_site_guild_id", "42")

    assert build_user_stats_url("43", 100) is None


def test_build_user_stats_url_adds_user_level_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "user_stats_site_base_url", "https://stats.example.com"
    )
    monkeypatch.setattr(settings, "user_stats_site_guild_id", "42")

    assert (
        build_user_stats_url("42", 100)
        == "https://stats.example.com/u/100/level?days=30"
    )


def test_build_level_action_view_contains_chill_button_without_stats_url() -> None:
    async def build_view() -> discord.ui.View:
        return build_level_action_view("42", 100, None)

    view = asyncio.run(build_view())

    assert len(view.children) == 1
    assert _component_label(view.children[0]) == "チル場所を設定"


def test_build_level_action_view_contains_chill_and_stats_buttons() -> None:
    async def build_view() -> discord.ui.View:
        return build_level_action_view(
            "42",
            100,
            "https://stats.example.com/u/100/level?days=30",
        )

    view = asyncio.run(build_view())

    assert len(view.children) == 2
    labels = [_component_label(child) for child in view.children]
    urls = [getattr(child, "url", None) for child in view.children]
    assert "チル場所を設定" in labels
    assert "ユーザー統計を開く" in labels
    assert "https://stats.example.com/u/100/level?days=30" in urls


def test_build_user_stats_url_does_not_duplicate_u_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "user_stats_site_base_url",
        "https://stats.example.com/u",
    )
    monkeypatch.setattr(settings, "user_stats_site_guild_id", "42")

    assert (
        build_user_stats_url("42", 100)
        == "https://stats.example.com/u/100/level?days=30"
    )
