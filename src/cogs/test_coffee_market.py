from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest

from src.bot import BOT_EXTENSIONS
from src.cogs import coffee_market as coffee_market_cog
from src.cogs.coffee_market import (
    CoffeeBuyConfirmationView,
    CoffeeBuyModal,
    CoffeeMarketCog,
    CoffeeMarketPanelView,
    CoffeeSellConfirmationView,
    CoffeeSellModal,
    DynamicCoffeeSellAllButton,
    _ledger_embed,
    _market_error_message,
    _panel_embed,
)
from src.features.coffee_market.contracts import (
    CoffeeMarketUnavailable,
    IdempotencyConflict,
    InsufficientBeans,
    MarketQuote,
    PublicTradeEntry,
    PurchaseResult,
    SaleResult,
    UserPosition,
)
from src.features.coffee_market.domain import MARKET_TIMEZONE, market_day_for


async def test_panel_has_all_persistent_market_actions() -> None:
    view = CoffeeMarketPanelView(1001)
    assert view.timeout is None
    assert all(isinstance(child, discord.ui.DynamicItem) for child in view.children)
    children = cast(list[discord.ui.DynamicItem[Any]], view.children)
    assert [child.item.label for child in children] == [
        "豆を買う",
        "保有豆",
        "豆を売る",
        "全部売る",
        "取引履歴",
        "週間ランキング",
    ]
    assert [child.item.custom_id for child in children] == [
        "level:coffee-market:buy:1001",
        "level:coffee-market:position:1001",
        "level:coffee-market:sell:1001",
        "level:coffee-market:sell-all:1001",
        "level:coffee-market:history:1001",
        "level:coffee-market:ranking:1001",
    ]
    assert children[3].item.style == discord.ButtonStyle.danger


def test_panel_embed_shows_current_prices_and_automatic_sale_rule() -> None:
    embed = _panel_embed(
        MarketQuote(
            market_day=date(2026, 8, 25),
            buy_price_xp=95,
            sell_price_xp=120,
            previous_sell_price_xp=100,
            news="入荷が不安定です。",
        ),
        now=datetime(2026, 8, 25, 12, tzinfo=MARKET_TIMEZONE),
    )
    text = embed.description or ""
    assert embed.title == "☕ コーヒー豆相場"
    assert "95 XP / 袋" in text
    assert "120 XP / 袋" in text
    assert "毎日1回購入" in text
    assert "現在の買値" in text
    assert "現在の売値" in text
    assert "本日の買値" not in text
    assert "レベルにも反映" in text
    assert "購入日の7日後" in text
    assert "自動売却" in text


def test_insufficient_beans_message_preserves_requested_and_available_mapping() -> None:
    message = _market_error_message(InsufficientBeans(requested=9, available=4))
    assert "指定: **9袋**" in message
    assert "売却可能: **4袋**" in message


def test_internal_and_temporary_errors_give_user_actionable_guidance() -> None:
    conflict = _market_error_message(IdempotencyConflict())
    unavailable = _market_error_message(CoffeeMarketUnavailable())

    assert "取引番号" not in conflict
    assert "取引履歴" in conflict
    assert "一時的に利用できません" in unavailable
    assert "時間をおいて" in unavailable


def test_bot_loads_coffee_market_extension() -> None:
    assert "src.cogs.coffee_market" in BOT_EXTENSIONS


def test_market_has_separate_commands_for_each_public_panel() -> None:
    commands = {
        command.name: command
        for command in CoffeeMarketCog.coffee_market_group.commands
    }
    assert {"panel", "ledger-panel", "ranking-panel"} <= commands.keys()
    assert all(
        len(cast(Any, commands[name]).checks) == 2
        for name in ("panel", "ledger-panel", "ranking-panel")
    )


@pytest.mark.parametrize(
    ("command_attribute", "panel_kind"),
    (
        ("post_panel", "market"),
        ("post_ledger_panel", "ledger"),
        ("post_ranking_panel", "ranking"),
    ),
)
async def test_each_panel_command_saves_the_channel_where_it_was_run(
    monkeypatch: pytest.MonkeyPatch,
    command_attribute: str,
    panel_kind: str,
) -> None:
    class _TextChannel:
        id = 3001

    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            channel=_TextChannel(),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(
                send=AsyncMock(return_value=SimpleNamespace(id=4001))
            ),
        ),
    )
    save_placement = AsyncMock()
    application = SimpleNamespace(save_panel=save_placement)
    monkeypatch.setattr(discord, "TextChannel", _TextChannel)
    monkeypatch.setattr(coffee_market_cog, "_settle_expired", AsyncMock())
    monkeypatch.setattr(
        coffee_market_cog,
        "_current_panel_embed",
        AsyncMock(return_value=discord.Embed()),
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "_current_ledger_embed",
        AsyncMock(return_value=discord.Embed()),
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "_current_ranking_embed",
        AsyncMock(return_value=discord.Embed()),
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: application,
    )
    cog = CoffeeMarketCog(cast(Any, SimpleNamespace()))
    command = cast(Any, getattr(CoffeeMarketCog, command_attribute))

    await command.callback(cog, interaction)

    save_placement.assert_awaited_once_with(
        guild_id="1001",
        panel_kind=panel_kind,
        channel_id="3001",
        message_id="4001",
    )


def test_public_ledger_embed_shows_other_members() -> None:
    embed = _ledger_embed(
        (
            PublicTradeEntry(
                user_id="2001",
                kind="buy",
                market_day=date(2026, 8, 25),
                quantity=5,
                unit_price_xp=90,
                total_xp=450,
                profit_xp=None,
                created_at=datetime(2026, 8, 25, tzinfo=MARKET_TIMEZONE),
            ),
        ),
        now=datetime(2026, 8, 25, 12, tzinfo=MARKET_TIMEZONE),
    )
    assert embed.title == "📒 コーヒー豆取引台帳"
    text = embed.description or ""
    assert "<@2001>" in text
    assert "`08/25`" in text


async def test_buy_modal_shows_cost_and_remaining_xp_before_purchase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_day = market_day_for(datetime.now(MARKET_TIMEZONE))
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            id=9001,
            user=SimpleNamespace(id=2001),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        ),
    )
    purchase = AsyncMock()
    position = AsyncMock(
        return_value=(
            MarketQuote(
                market_day=market_day,
                buy_price_xp=100,
                sell_price_xp=120,
                previous_sell_price_xp=110,
                news="入荷が続いています。",
            ),
            UserPosition(
                quantity=0,
                sellable_quantity=0,
                average_buy_price_xp=0,
                evaluation_xp=0,
                unrealized_profit_xp=0,
                earliest_expiry=None,
                purchased_today=False,
                available_xp=2_000,
            ),
        )
    )
    application = SimpleNamespace(position=position, purchase=purchase)
    monkeypatch.setattr(
        coffee_market_cog, "_trade_allowed", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        coffee_market_cog, "_settle_expired", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: application,
    )
    modal = CoffeeBuyModal(1001)
    cast(Any, modal.quantity)._value = "7"

    await modal.on_submit(interaction)

    purchase.assert_not_awaited()
    position.assert_awaited_once_with(
        guild_id="1001",
        user_id="2001",
        market_day=ANY,
    )
    send = cast(AsyncMock, interaction.followup.send)
    send.assert_awaited_once()
    call = send.await_args
    assert call is not None
    assert "7袋 × 100 XP = **700 XP**" in call.args[0]
    assert "購入後XP: **1,300 XP**" in call.args[0]
    assert "レベルが下がります" in call.args[0]
    view = call.kwargs["view"]
    assert isinstance(view, CoffeeBuyConfirmationView)
    assert view.quantity == 7
    assert view.user_id == 2001
    assert view.message is not None


async def test_confirmation_timeout_disables_buttons_and_explains_next_step() -> None:
    view = CoffeeBuyConfirmationView(
        guild_id=1001,
        user_id=2001,
        quantity=7,
        market_day=date(2026, 8, 25),
    )
    edit = AsyncMock()
    view.message = cast(discord.WebhookMessage, SimpleNamespace(edit=edit))

    await view.on_timeout()

    assert all(
        isinstance(child, discord.ui.Button) and child.disabled
        for child in view.children
    )
    edit.assert_awaited_once_with(
        content="購入の確認期限が切れました。パネルからやり直してください。",
        view=view,
    )


async def test_buy_confirmation_maps_identity_quantity_and_event_to_purchase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_day = market_day_for(datetime.now(MARKET_TIMEZONE))
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            user=SimpleNamespace(id=2001),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),
            guild=SimpleNamespace(id=1001),
        ),
    )
    purchase = AsyncMock(
        return_value=PurchaseResult(
            status="completed",
            market_day=market_day,
            quantity=7,
            unit_price_xp=100,
            cost_xp=700,
            sellable_on=market_day + timedelta(days=1),
            expires_on=market_day + timedelta(days=7),
            available_xp_after=1_300,
        )
    )
    view = CoffeeBuyConfirmationView(
        guild_id=1001,
        user_id=2001,
        quantity=7,
        market_day=market_day,
    )
    monkeypatch.setattr(
        coffee_market_cog, "_confirmation_allowed", AsyncMock(return_value=True)
    )
    refresh = AsyncMock()
    monkeypatch.setattr(coffee_market_cog, "_refresh_after_interaction", refresh)
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(purchase=purchase),
    )

    await cast(Any, view.children[0]).callback(interaction)

    purchase.assert_awaited_once_with(
        event_id=view.event_id,
        guild_id="1001",
        user_id="2001",
        quantity=7,
        market_day=market_day,
    )
    edit = cast(AsyncMock, interaction.edit_original_response)
    edit_call = edit.await_args
    assert edit_call is not None
    assert "7袋 × 100 XP = **700 XP**" in edit_call.kwargs["content"]
    assert edit_call.kwargs["view"] is None
    assert view.is_finished()
    refresh.assert_awaited_once_with(
        interaction,
        now=ANY,
        ledger=True,
        ranking=False,
    )


async def test_confirmation_rejects_a_quote_from_the_previous_market_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            user=SimpleNamespace(id=2001),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),
        ),
    )
    purchase = AsyncMock()
    view = CoffeeBuyConfirmationView(
        guild_id=1001,
        user_id=2001,
        quantity=7,
        market_day=date(2000, 1, 1),
    )
    monkeypatch.setattr(
        coffee_market_cog, "_confirmation_allowed", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(purchase=purchase),
    )

    await cast(Any, view.children[0]).callback(interaction)

    purchase.assert_not_awaited()
    edit = cast(AsyncMock, interaction.edit_original_response)
    edit_call = edit.await_args
    assert edit_call is not None
    assert "相場が更新されました" in edit_call.kwargs["content"]
    assert edit_call.kwargs["view"] is None


async def test_sell_modal_shows_available_quantity_and_payout_before_sale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_day = market_day_for(datetime.now(MARKET_TIMEZONE))
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            user=SimpleNamespace(id=2001),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        ),
    )
    sell = AsyncMock()
    position = AsyncMock(
        return_value=(
            MarketQuote(
                market_day=market_day,
                buy_price_xp=100,
                sell_price_xp=120,
                previous_sell_price_xp=110,
                news="入荷が続いています。",
            ),
            UserPosition(
                quantity=8,
                sellable_quantity=6,
                average_buy_price_xp=100,
                evaluation_xp=960,
                unrealized_profit_xp=160,
                earliest_expiry=market_day,
                purchased_today=False,
                available_xp=1_300,
            ),
        )
    )
    monkeypatch.setattr(
        coffee_market_cog, "_trade_allowed", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        coffee_market_cog, "_settle_expired", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(position=position, sell=sell),
    )
    modal = CoffeeSellModal(1001)
    cast(Any, modal.quantity)._value = "4"

    await modal.on_submit(interaction)

    sell.assert_not_awaited()
    call = cast(AsyncMock, interaction.followup.send).await_args
    assert call is not None
    assert "4袋 × 120 XP = **480 XP**" in call.args[0]
    assert "売却後XP: **1,780 XP**" in call.args[0]
    view = call.kwargs["view"]
    assert isinstance(view, CoffeeSellConfirmationView)
    assert view.quantity == 4
    assert view.sell_all is False


async def test_sell_all_button_shows_exact_sale_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_day = market_day_for(datetime.now(MARKET_TIMEZONE))
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            id=9002,
            user=SimpleNamespace(id=2001),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        ),
    )
    sell = AsyncMock()
    position = AsyncMock(
        return_value=(
            MarketQuote(
                market_day=market_day,
                buy_price_xp=100,
                sell_price_xp=120,
                previous_sell_price_xp=110,
                news="入荷が続いています。",
            ),
            UserPosition(
                quantity=8,
                sellable_quantity=6,
                average_buy_price_xp=100,
                evaluation_xp=960,
                unrealized_profit_xp=160,
                earliest_expiry=market_day,
                purchased_today=False,
                available_xp=1_300,
            ),
        )
    )
    application = SimpleNamespace(position=position, sell=sell)
    monkeypatch.setattr(
        coffee_market_cog, "_trade_allowed", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        coffee_market_cog, "_settle_expired", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: application,
    )

    await DynamicCoffeeSellAllButton(1001).callback(interaction)

    sell.assert_not_awaited()
    send = cast(AsyncMock, interaction.followup.send)
    send.assert_awaited_once()
    call = send.await_args
    assert call is not None
    assert "6袋 × 120 XP = **720 XP**" in call.args[0]
    assert "売却後XP: **2,020 XP**" in call.args[0]
    view = call.kwargs["view"]
    assert isinstance(view, CoffeeSellConfirmationView)
    assert view.quantity == 6
    assert view.sell_all is True


async def test_sell_all_confirmation_preserves_identity_and_confirmed_quantity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_day = market_day_for(datetime.now(MARKET_TIMEZONE))
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            user=SimpleNamespace(id=2001),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(),
            guild=SimpleNamespace(id=1001),
        ),
    )
    sell = AsyncMock(
        return_value=SaleResult(
            status="completed",
            market_day=market_day,
            sale_kind="manual",
            quantity=6,
            unit_price_xp=120,
            payout_xp=720,
            cost_basis_xp=600,
            available_xp_after=2_020,
        )
    )
    view = CoffeeSellConfirmationView(
        guild_id=1001,
        user_id=2001,
        quantity=6,
        market_day=market_day,
        sell_all=True,
    )
    monkeypatch.setattr(
        coffee_market_cog, "_confirmation_allowed", AsyncMock(return_value=True)
    )
    refresh = AsyncMock()
    monkeypatch.setattr(coffee_market_cog, "_refresh_after_interaction", refresh)
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(sell=sell),
    )

    await cast(Any, view.children[0]).callback(interaction)

    sell.assert_awaited_once_with(
        event_id=view.event_id,
        guild_id="1001",
        user_id="2001",
        quantity=6,
        market_day=market_day,
    )
    edit = cast(AsyncMock, interaction.edit_original_response)
    edit_call = edit.await_args
    assert edit_call is not None
    assert "6袋 × 120 XP = **720 XP**" in edit_call.kwargs["content"]
    assert edit_call.kwargs["view"] is None
    assert view.is_finished()
    refresh.assert_awaited_once_with(
        interaction,
        now=ANY,
        ledger=True,
        ranking=True,
    )
