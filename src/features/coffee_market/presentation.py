"""コーヒー豆相場の表示文言。Discordオブジェクトには依存しない。"""

from __future__ import annotations

from datetime import date

from src.features.coffee_market.contracts import (
    MarketQuote,
    PublicTradeEntry,
    RankingEntry,
    TradeHistoryEntry,
    UserPosition,
)
from src.features.coffee_market.domain import MAX_DAILY_QUANTITY

PANEL_TITLE = "☕ コーヒー豆相場"
LEDGER_TITLE = "📒 コーヒー豆取引台帳"
RANKING_TITLE = "🏆 今週の豆相場ランキング"


def _signed_xp(value: int) -> str:
    return f"{value:+,} XP"


def panel_description(quote: MarketQuote, *, next_reset_timestamp: int) -> str:
    change = quote.sell_price_change
    arrow = "↗" if change > 0 else "↘" if change < 0 else "→"
    return (
        f"**現在の買値**\n`{quote.buy_price_xp:,} XP / 袋`\n\n"
        f"**現在の売値**\n`{quote.sell_price_xp:,} XP / 袋` "
        f"{arrow} {_signed_xp(change)}\n\n"
        f"**相場ニュース**\n{quote.news}\n\n"
        f"次回更新: <t:{next_reset_timestamp}:R>\n"
        "毎日1回購入でき、購入翌日から売却できます。\n"
        "購入額はサーバーXPから差し引かれ、レベルにも反映されます。\n"
        "購入日の7日後、5:00に残っている豆は自動売却されます。"
    )


def position_description(position: UserPosition, *, market_day: date) -> str:
    expiry = (
        "なし"
        if position.earliest_expiry is None
        else f"{position.earliest_expiry:%Y/%m/%d} "
        f"（残り {(position.earliest_expiry - market_day).days}日）"
    )
    purchased = "購入済み" if position.purchased_today else "購入できます"
    return (
        f"**保有**　{position.quantity:,}袋\n"
        f"**売却可能**　{position.sellable_quantity:,}袋\n"
        f"**平均買値**　{position.average_buy_price_xp:,} XP / 袋\n"
        f"**現在の評価額**　{position.evaluation_xp:,} XP\n"
        f"**評価損益**　{_signed_xp(position.unrealized_profit_xp)}\n"
        f"**最短の自動売却日**　{expiry}\n"
        f"**本日の購入**　{purchased}\n"
        f"**現在XP**　{position.available_xp:,} XP"
    )


def history_lines(entries: tuple[TradeHistoryEntry, ...]) -> str:
    if not entries:
        return "取引履歴はまだありません。"
    labels = {"buy": "購入", "manual": "売却", "expired": "自動売却"}
    lines: list[str] = []
    for entry in entries:
        suffix = "" if entry.profit_xp is None else f" / {_signed_xp(entry.profit_xp)}"
        lines.append(
            f"{entry.market_day:%Y/%m/%d} **{labels[entry.kind]}** "
            f"{entry.quantity:,}袋 × {entry.unit_price_xp:,} XP "
            f"= {entry.total_xp:,} XP{suffix}"
        )
    return "\n".join(lines)


def public_ledger_lines(entries: tuple[PublicTradeEntry, ...]) -> str:
    if not entries:
        return "取引はまだありません。最初の豆を買ってみましょう。"
    labels = {"buy": "購入", "manual": "売却", "expired": "自動売却"}
    icons = {"buy": "🫘", "manual": "☕", "expired": "⏰"}
    lines: list[str] = []
    for entry in entries:
        suffix = "" if entry.profit_xp is None else f" / {_signed_xp(entry.profit_xp)}"
        lines.append(
            f"{icons[entry.kind]} `{entry.market_day:%m/%d}` "
            f"<@{entry.user_id}> **{labels[entry.kind]}** "
            f"{entry.quantity:,}袋 × {entry.unit_price_xp:,} XP "
            f"= {entry.total_xp:,} XP{suffix}"
        )
    return "\n".join(lines)


def ranking_lines(entries: tuple[RankingEntry, ...]) -> str:
    if not entries:
        return "今週の確定損益はまだありません。"
    medals = ("🥇", "🥈", "🥉")
    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        rank = medals[index - 1] if index <= len(medals) else f"**{index}.**"
        lines.append(
            f"{rank} <@{entry.user_id}>　{_signed_xp(entry.profit_xp)} "
            f"({entry.profit_rate:+.1f}%)"
        )
    return "\n".join(lines)


def rules_description() -> str:
    return (
        f"購入は1日1回、**1〜{MAX_DAILY_QUANTITY}袋**です。\n"
        "購入した豆は翌日の相場更新後から売却できます。\n"
        "売却は期限の近い豆から自動的に行われます。\n"
        "購入日の7日後、**5:00**まで売らなかった豆は、その時点の売値で"
        "自動売却されます。\n"
        "購入時にサーバーXPとレベルが下がり、売却時に上がります。"
    )
