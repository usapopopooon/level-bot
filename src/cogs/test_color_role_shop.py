import asyncio

import discord

from src.cogs.color_role_shop import (
    COLOR_ROLE_BALANCE_LABEL,
    COLOR_ROLE_CLEAR_LABEL,
    COLOR_ROLE_OPEN_LABEL,
    ColorRoleExchangeConfirmView,
    ColorRoleShopPanelView,
    build_color_role_panel_embed,
)
from src.features.color_role_shop.service import ColorRoleItemView


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
        ),
    )

    embed = build_color_role_panel_embed(guild, items)  # type: ignore[arg-type]
    values = "\n".join(str(field.value) for field in embed.fields)

    assert embed.title == "カラーロール交換所"
    assert "<@&2001>" in values
    assert "500 XP" in values
    assert "ロール選択" in values
    assert "他の交換ロールは外れます" in values
    assert "ロールを外す" in values
    assert "XP は戻りません" in values
    assert embed.thumbnail.url is None


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
