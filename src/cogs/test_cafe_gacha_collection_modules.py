"""カフェ棚UIを分割した後の公開import契約。"""

from src.cogs import cafe_gacha_collection as collection
from src.cogs import cafe_gacha_collection_customization as customization
from src.cogs import cafe_gacha_collection_exchange as exchange
from src.cogs import cafe_gacha_collection_sets as sets


def test_collection_facade_reexports_responsibility_modules() -> None:
    exchange_names = (
        "RedemptionConfirmView",
        "CustomQuantityModal",
        "_send_redemption_confirmation",
        "RedemptionQuantityView",
        "RedemptionSelect",
        "RedemptionSelectView",
        "IndividualExchangeButton",
        "BulkRedemptionConfirmView",
        "BulkExchangeButton",
        "MedalRedemptionConfirmView",
        "MedalExchangeButton",
    )
    customization_names = (
        "FavoriteSelect",
        "FavoriteSelectView",
        "ProtectionSelect",
        "ProtectionSelectView",
        "ProtectionButton",
        "MossColaProtectionButton",
        "CosmeticConfirmView",
        "CosmeticSelect",
        "CafeMedalShopButton",
    )
    set_names = (
        "SET_MENU_PAGE_SIZE",
        "_set_menu_embed",
        "CafeSetMenuView",
        "CafeSetMenuButton",
    )

    for module, names in (
        (exchange, exchange_names),
        (customization, customization_names),
        (sets, set_names),
    ):
        for name in names:
            assert getattr(collection, name) is getattr(module, name)
