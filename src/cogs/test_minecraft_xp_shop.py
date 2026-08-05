import asyncio

from src.cogs.minecraft_xp_shop import (
    MinecraftXpConfirmView,
    MinecraftXpShopPanelView,
    build_minecraft_xp_shop_embed,
)


def test_minecraft_xp_shop_panel_lists_fixed_packs() -> None:
    embed = build_minecraft_xp_shop_embed()

    assert embed.title == "Minecraft XP交換所"
    assert embed.fields[0].value == (
        "`サーバーXP 10` → `Minecraft 50 XP`\n"
        "`サーバーXP 50` → `Minecraft 250 XP`\n"
        "`サーバーXP 100` → `Minecraft 500 XP`"
    )


def test_minecraft_xp_shop_panel_has_persistent_exchange_button() -> None:
    async def build_view() -> MinecraftXpShopPanelView:
        return MinecraftXpShopPanelView(1001)

    view = asyncio.run(build_view())

    assert view.timeout is None
    assert len(view.children) == 1
    item = getattr(view.children[0], "item", view.children[0])
    assert getattr(item, "custom_id", None) == "level:minecraft-xp:open:1001"


def test_minecraft_xp_confirm_disables_unaffordable_exchange() -> None:
    async def build_view() -> MinecraftXpConfirmView:
        return MinecraftXpConfirmView(
            guild_id="1001", user_id=2001, cost_xp=10, affordable=False
        )

    view = asyncio.run(build_view())

    assert view.confirm.disabled
