import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest
from discord.ext import commands

from src.cogs import color_role_shop as color_role_shop_cog
from src.cogs.color_role_shop import (
    COLOR_ROLE_BALANCE_LABEL,
    COLOR_ROLE_CLEAR_LABEL,
    COLOR_ROLE_OPEN_LABEL,
    ColorRoleExchangeConfirmView,
    ColorRoleShopCog,
    ColorRoleShopPanelView,
    DynamicColorRoleShopOpenButton,
    build_color_role_panel_embed,
    build_color_role_panel_files,
)
from src.features.color_role_shop.presentation import (
    COLOR_ROLE_SAMPLE_ATTACHMENT_URL,
    _centered_text_origin,
)
from src.features.color_role_shop.service import ColorRoleItemView
from src.features.feature_access import service as feature_access_service
from src.features.feature_access.service import COLOR_ROLE_SHOP


class _FakeTextDraw:
    def textbbox(
        self,
        xy: tuple[int, int],
        text: str,
        *,
        font: object,
    ) -> tuple[int, int, int, int]:
        assert xy == (0, 0)
        assert text == "01"
        assert font is _FAKE_FONT
        return (2, 7, 30, 27)


_FAKE_FONT = object()


def _component_label(component: object) -> str | None:
    return getattr(component, "label", None) or getattr(
        getattr(component, "item", None), "label", None
    )


def _component_custom_id(component: object) -> str | None:
    return getattr(component, "custom_id", None) or getattr(
        getattr(component, "item", None), "custom_id", None
    )


def test_color_role_shop_panel_view_has_clear_persistent_buttons() -> None:
    async def build_view() -> discord.ui.View:
        return ColorRoleShopPanelView(1001)

    view = asyncio.run(build_view())
    labels = [_component_label(child) for child in view.children]
    custom_ids = [_component_custom_id(child) for child in view.children]

    assert view.timeout is None
    assert labels == [
        COLOR_ROLE_OPEN_LABEL,
        COLOR_ROLE_BALANCE_LABEL,
        COLOR_ROLE_CLEAR_LABEL,
    ]
    assert custom_ids == [
        "level:color-role:open:1001",
        "level:color-role:balance:1001",
        "level:color-role:clear:1001",
    ]


def test_build_color_role_panel_embed_lists_roles_and_usage() -> None:
    guild = discord.Object(id=1001)
    items = (
        ColorRoleItemView(
            id=1,
            guild_id="1001",
            role_id="2001",
            label="常連",
            description="常連ロール",
            cost_xp=500,
            color=0xF43F5E,
        ),
    )

    embed = build_color_role_panel_embed(guild, items)  # type: ignore[arg-type]
    values = "\n".join(str(field.value) for field in embed.fields)

    assert embed.title == "カラーロール交換所"
    assert "<@&2001>" in values
    assert "500 XP" in values
    assert "#F43F5E" not in values
    assert "ロール選択" in values
    assert "他の交換ロールは外れます" in values
    assert "ロールを外す" in values
    assert "XP は戻りません" in values
    assert embed.thumbnail.url is None
    assert embed.image.url == COLOR_ROLE_SAMPLE_ATTACHMENT_URL


def test_build_color_role_panel_files_contains_transparent_png_sample() -> None:
    items = (
        ColorRoleItemView(
            id=1,
            guild_id="1001",
            role_id="2001",
            label="常連",
            description=None,
            cost_xp=500,
            color=0x22C55E,
        ),
    )

    files = build_color_role_panel_files(items)

    assert len(files) == 1
    assert files[0].filename == "color-role-samples.png"
    assert files[0].fp.read(8) == b"\x89PNG\r\n\x1a\n"


def test_centered_text_origin_uses_actual_text_bbox_center() -> None:
    origin_x, origin_y = _centered_text_origin(
        _FakeTextDraw(),
        "01",
        _FAKE_FONT,
        (10, 20, 82, 106),
    )

    assert (origin_x, origin_y) == (30.0, 46.0)


def test_exchange_confirm_view_disables_confirm_when_unaffordable() -> None:
    async def build_view() -> ColorRoleExchangeConfirmView:
        return ColorRoleExchangeConfirmView(
            guild_id="1001",
            user_id=3001,
            item_id=1,
            affordable=False,
        )

    view = asyncio.run(build_view())
    confirm = next(
        child
        for child in view.children
        if isinstance(child, discord.ui.Button) and child.custom_id == "confirm"
    )

    assert confirm.disabled is True


async def test_open_button_checks_access_before_loading_shop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=False)
    response = SimpleNamespace(defer=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(response=response, user=SimpleNamespace(id=3001)),
    )
    monkeypatch.setattr(color_role_shop_cog, "ensure_feature_access", access)

    await DynamicColorRoleShopOpenButton(1001).callback(interaction)

    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=COLOR_ROLE_SHOP,
    )
    response.defer.assert_not_awaited()


async def test_exchange_confirmation_rechecks_access_before_spending_xp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=False)
    response = SimpleNamespace(defer=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(response=response, user=SimpleNamespace(id=3001)),
    )
    monkeypatch.setattr(color_role_shop_cog, "ensure_feature_access", access)
    view = ColorRoleExchangeConfirmView(
        guild_id="1001",
        user_id=3001,
        item_id=1,
        affordable=True,
    )
    button = next(
        child
        for child in view.children
        if isinstance(child, discord.ui.Button) and child.custom_id == "confirm"
    )

    await button.callback(interaction)

    access.assert_awaited_once()
    response.defer.assert_not_awaited()


async def test_color_access_role_command_writes_color_feature_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    add_role = AsyncMock(return_value=True)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(guild=SimpleNamespace(id=1001), response=response),
    )
    role = cast(discord.Role, SimpleNamespace(id=2001, mention="<@&2001>"))
    cog = ColorRoleShopCog(cast(commands.Bot, SimpleNamespace()))
    monkeypatch.setattr(color_role_shop_cog, "async_session", _SessionContext)
    monkeypatch.setattr(
        feature_access_service,
        "add_access_role",
        add_role,
    )

    callback = cast(Any, ColorRoleShopCog.add_access_role.callback)
    await callback(cog, interaction, role)

    add_role.assert_awaited_once_with(
        ANY,
        guild_id="1001",
        feature=COLOR_ROLE_SHOP,
        role_id="2001",
    )
