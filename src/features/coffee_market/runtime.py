"""コーヒー豆相場の実行環境依存を選ぶ。"""

from __future__ import annotations

from src.features.coffee_market.application import CoffeeMarketApplication


def default_application() -> CoffeeMarketApplication:
    from src.features.coffee_market.adapters.level_bot_application import (
        LEVEL_BOT_COFFEE_MARKET_APPLICATION,
    )

    return LEVEL_BOT_COFFEE_MARKET_APPLICATION
