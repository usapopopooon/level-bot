from datetime import UTC, date, datetime

from src.features.coffee_market.contracts import (
    MarketQuote,
    RankingEntry,
    TradeHistoryEntry,
    UserPosition,
)
from src.features.coffee_market.presentation import (
    history_lines,
    panel_description,
    position_description,
    ranking_lines,
)


def test_panel_explains_daily_buy_and_automatic_sale() -> None:
    text = panel_description(
        MarketQuote(
            market_day=date(2026, 8, 25),
            buy_price_xp=98,
            sell_price_xp=124,
            previous_sell_price_xp=106,
            news="入荷が遅れています。",
        ),
        next_reset_timestamp=1_777_777_777,
    )
    assert "98 XP / 袋" in text
    assert "124 XP / 袋" in text
    assert "+18 XP" in text
    assert "購入は毎日1回" in text
    assert "1〜10袋" in text
    assert "0時・6時・12時・18時" in text
    assert "次の相場更新後" in text
    assert "安い日に豆を買い" in text
    assert "XPの利益" in text
    assert "値上がりの機会は多め" in text
    assert "損失" in text
    assert "購入日の7日後" in text
    assert "期限の近い豆から" in text
    assert "サーバーXPから差し引かれ" in text
    assert "自動売却" in text


def test_position_and_panel_do_not_claim_expiry_deletes_beans() -> None:
    text = position_description(
        UserPosition(
            quantity=8,
            sellable_quantity=6,
            average_buy_price_xp=100,
            evaluation_xp=960,
            unrealized_profit_xp=160,
            earliest_expiry=date(2026, 8, 27),
            purchased_today=True,
            available_xp=2_000,
        ),
        market_day=date(2026, 8, 25),
    )
    panel = panel_description(
        MarketQuote(
            market_day=date(2026, 8, 25),
            buy_price_xp=98,
            sell_price_xp=124,
            previous_sell_price_xp=106,
            news="入荷が遅れています。",
        ),
        next_reset_timestamp=1_777_777_777,
    )
    assert "残り 2日" in text
    assert "購入済み" in text
    assert "自動売却" in panel
    assert "購入日の7日後" in panel
    assert "0:00" in panel
    assert "5:00" not in panel
    assert "消失" not in panel
    assert "レベルにも反映" in panel


def test_history_and_ranking_distinguish_forced_sales() -> None:
    history = history_lines(
        (
            TradeHistoryEntry(
                kind="expired",
                market_day=date(2026, 8, 25),
                quantity=3,
                unit_price_xp=120,
                total_xp=360,
                profit_xp=60,
                created_at=datetime(2026, 8, 25, tzinfo=UTC),
            ),
        )
    )
    ranking = ranking_lines(
        (
            RankingEntry(
                user_id="2001", payout_xp=1_200, cost_basis_xp=1_000, profit_xp=200
            ),
        )
    )
    assert "自動売却" in history
    assert "+60 XP" in history
    assert "<@2001>" in ranking
    assert "+20.0%" in ranking
