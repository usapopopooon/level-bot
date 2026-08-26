from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest
from discord import app_commands

from src.bot import BOT_EXTENSIONS
from src.cogs import coffee_market as coffee_market_cog
from src.cogs.coffee_market import (
    CoffeeBuyConfirmationView,
    CoffeeBuyQuantitySelect,
    CoffeeBuyQuantityView,
    CoffeeMarketCog,
    CoffeeMarketPanelView,
    CoffeeSellConfirmationView,
    CoffeeSellModal,
    DynamicCoffeeBuyButton,
    DynamicCoffeeHistoryButton,
    DynamicCoffeePositionButton,
    DynamicCoffeeRankingButton,
    DynamicCoffeeSellAllButton,
    DynamicCoffeeSellButton,
    _ledger_log_embed,
    _market_error_message,
    _panel_embed,
    _ranking_embed,
)
from src.features.coffee_market.contracts import (
    AlreadyPurchasedThisPeriod,
    CoffeeMarketUnavailable,
    IdempotencyConflict,
    InsufficientBeans,
    MarketQuote,
    PublicTradeEntry,
    PurchaseResult,
    RankingEntry,
    RankingSnapshot,
    SaleResult,
    UserPosition,
)
from src.features.coffee_market.domain import (
    MARKET_TIMEZONE,
    MarketPeriod,
    market_period_for,
    next_market_period,
)
from src.features.feature_access import service as feature_access_service


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
        "ランキング",
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
    assert "購入は各相場の更新ごとに1回" in text
    assert "1〜10袋" in text
    assert "1日最大40袋" in text
    assert "売却回数に制限はありません" in text
    assert "現在の買値" in text
    assert "現在の売値" in text
    assert "本日の買値" not in text
    assert "安い相場で豆を買い" in text
    assert "値上がりしたタイミングで売って" in text
    assert "XPの利益" in text
    assert "値上がり・値下がり・横ばい" in text
    assert "上回れば利益、下回れば損失" in text
    assert "損失" in text
    assert "レベルにも反映" in text
    assert "購入日の7日後" in text
    assert "自動売却" in text
    assert embed.footer.text is not None
    assert "相場 2026/08/25 00:00" in embed.footer.text
    assert "1日4回更新" in embed.footer.text


def test_ranking_embed_shows_daily_last_five_days_and_cumulative_results() -> None:
    daily_entry = RankingEntry(
        user_id="2001",
        payout_xp=1_200,
        cost_basis_xp=1_000,
        profit_xp=200,
    )
    cumulative_entry = RankingEntry(
        user_id="2002",
        payout_xp=1_500,
        cost_basis_xp=1_000,
        profit_xp=500,
    )

    embed = _ranking_embed(
        RankingSnapshot(
            market_day=date(2026, 8, 25),
            daily=(daily_entry,),
            last_five_days=(),
            cumulative=(cumulative_entry,),
        )
    )

    assert embed.title == "🏆 豆相場ランキング"
    assert [field.name for field in embed.fields] == [
        "📅 本日",
        "🗓️ 過去5日",
        "☕ 累計",
    ]
    assert all(field.inline is False for field in embed.fields)
    daily_value = embed.fields[0].value
    cumulative_value = embed.fields[2].value
    assert daily_value is not None
    assert cumulative_value is not None
    assert "<@2001>" in daily_value
    assert "本日の確定損益" not in daily_value
    assert embed.fields[1].value == "過去5日の確定損益はまだありません。"
    assert "<@2002>" in cumulative_value
    assert embed.footer.text is not None
    assert "日本時間0:00更新" in embed.footer.text


def test_insufficient_beans_message_preserves_requested_and_available_mapping() -> None:
    message = _market_error_message(InsufficientBeans(requested=9, available=4))
    assert "指定: **9袋**" in message
    assert "売却可能: **4袋**" in message


def test_already_purchased_message_points_to_the_next_market_update() -> None:
    message = _market_error_message(AlreadyPurchasedThisPeriod())

    assert "現在の相場での購入は完了" in message
    assert "次回更新後" in message
    assert "翌日" not in message


def test_internal_and_temporary_errors_give_user_actionable_guidance() -> None:
    conflict = _market_error_message(IdempotencyConflict())
    unavailable = _market_error_message(CoffeeMarketUnavailable())

    assert "取引番号" not in conflict
    assert "取引履歴" in conflict
    assert "一時的に利用できません" in unavailable
    assert "時間をおいて" in unavailable


def test_bot_loads_coffee_market_extension() -> None:
    assert "src.cogs.coffee_market" in BOT_EXTENSIONS


def test_market_has_separate_commands_for_panels_and_ledger_channel() -> None:
    commands = {
        command.name: command
        for command in CoffeeMarketCog.coffee_market_group.commands
    }
    assert {"panel", "ledger", "ranking-panel"} <= commands.keys()
    assert "ledger-panel" not in commands
    assert "rules" not in commands
    assert all(
        len(cast(Any, commands[name]).checks) == 2
        for name in ("panel", "ranking-panel")
    )


def test_market_has_access_role_management_group() -> None:
    commands = {
        command.name: command
        for command in CoffeeMarketCog.coffee_market_group.commands
    }
    access_group = cast(app_commands.Group, commands["access-role"])
    access_commands = {command.name: command for command in access_group.commands}

    assert set(access_commands) == {"add", "remove", "list"}
    assert all(
        len(cast(Any, command).checks) == 1 for command in access_commands.values()
    )


async def test_market_access_role_add_uses_application_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_access_role = AsyncMock(return_value=True)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(guild=SimpleNamespace(id=1001), response=response),
    )
    role = cast(discord.Role, SimpleNamespace(id=2001, mention="<@&2001>"))
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(add_access_role=add_access_role),
    )
    cog = CoffeeMarketCog(cast(Any, SimpleNamespace()))

    await cast(Any, CoffeeMarketCog.add_access_role).callback(cog, interaction, role)

    add_access_role.assert_awaited_once_with(
        guild_id="1001",
        role_id="2001",
    )
    response.send_message.assert_awaited_once()


async def test_market_access_check_uses_coffee_market_roles_before_xp_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Member:
        id = 2001
        bot = False
        roles = [SimpleNamespace(id=3001)]

    access = AsyncMock(return_value=False)
    is_user_excluded = AsyncMock()
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            user=_Member(),
            permissions=SimpleNamespace(administrator=False, manage_guild=False),
            response=SimpleNamespace(send_message=AsyncMock(), is_done=lambda: False),
            followup=SimpleNamespace(send=AsyncMock()),
        ),
    )
    monkeypatch.setattr(discord, "Member", _Member)
    monkeypatch.setattr(coffee_market_cog, "ensure_feature_access", access)
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(is_user_excluded=is_user_excluded),
    )

    allowed = await coffee_market_cog._trade_allowed(interaction, guild_id=1001)

    assert allowed is False
    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=feature_access_service.COFFEE_MARKET,
    )
    is_user_excluded.assert_not_awaited()


@pytest.mark.parametrize(
    "button",
    (
        DynamicCoffeeBuyButton(1001),
        DynamicCoffeePositionButton(1001),
        DynamicCoffeeSellButton(1001),
        DynamicCoffeeSellAllButton(1001),
        DynamicCoffeeHistoryButton(1001),
        DynamicCoffeeRankingButton(1001),
    ),
)
async def test_every_market_panel_action_checks_current_access_role(
    monkeypatch: pytest.MonkeyPatch,
    button: discord.ui.DynamicItem[Any],
) -> None:
    access = AsyncMock(return_value=False)
    interaction = cast(discord.Interaction, SimpleNamespace())
    monkeypatch.setattr(coffee_market_cog, "_trade_allowed", access)

    await button.callback(interaction)

    access.assert_awaited_once_with(interaction, guild_id=1001)


async def test_market_ranking_command_checks_current_access_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=False)
    response = SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            response=response,
            followup=followup,
        ),
    )
    monkeypatch.setattr(coffee_market_cog, "_trade_allowed", access)
    monkeypatch.setattr(coffee_market_cog, "_settle_expired", AsyncMock())
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(rankings=AsyncMock()),
    )
    cog = CoffeeMarketCog(cast(Any, SimpleNamespace()))
    command = cast(Any, CoffeeMarketCog.show_ranking)

    await command.callback(cog, interaction)

    access.assert_awaited_once_with(interaction, guild_id=1001)
    response.defer.assert_not_awaited()
    response.send_message.assert_not_awaited()
    followup.send.assert_not_awaited()


@pytest.mark.parametrize(
    ("command_attribute", "panel_kind"),
    (
        ("post_panel", "market"),
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
    monkeypatch.setattr(
        coffee_market_cog, "_settle_expired", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "_current_panel_embed",
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


async def test_ledger_command_only_configures_channel_and_flushes_unposted_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TextChannel:
        id = 3001

    channel = _TextChannel()
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            channel=channel,
            response=SimpleNamespace(send_message=AsyncMock()),
        ),
    )
    save_ledger_channel = AsyncMock()
    flush = AsyncMock()
    monkeypatch.setattr(discord, "TextChannel", _TextChannel)
    monkeypatch.setattr(
        coffee_market_cog, "_settle_expired", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: SimpleNamespace(save_ledger_channel=save_ledger_channel),
    )
    monkeypatch.setattr(coffee_market_cog, "_flush_ledger_logs", flush)
    cog = CoffeeMarketCog(cast(Any, SimpleNamespace()))

    await cast(Any, CoffeeMarketCog.configure_ledger).callback(cog, interaction)

    save_ledger_channel.assert_awaited_once_with(
        guild_id="1001",
        channel_id="3001",
    )
    flush.assert_awaited_once_with(interaction.guild)
    response = cast(AsyncMock, interaction.response.send_message)
    response.assert_awaited_once()
    assert response.await_args is not None
    assert response.await_args.kwargs["ephemeral"] is True


async def test_ledger_flush_posts_each_pending_trade_as_its_own_embed_and_marks_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TextChannel:
        def __init__(self) -> None:
            self.send = AsyncMock(
                side_effect=(SimpleNamespace(id=9001), SimpleNamespace(id=9002))
            )

    channel = _TextChannel()
    guild = cast(
        discord.Guild,
        SimpleNamespace(
            id=1001,
            get_channel=lambda channel_id: channel if channel_id == 3001 else None,
        ),
    )
    entries = (
        PublicTradeEntry(
            user_id="2001",
            kind="buy",
            market_day=date(2026, 8, 24),
            quantity=2,
            unit_price_xp=90,
            total_xp=180,
            profit_xp=None,
            created_at=datetime(2026, 8, 24, tzinfo=MARKET_TIMEZONE),
            record_id=41,
        ),
        PublicTradeEntry(
            user_id="2002",
            kind="manual",
            market_day=date(2026, 8, 25),
            quantity=3,
            unit_price_xp=120,
            total_xp=360,
            profit_xp=60,
            created_at=datetime(2026, 8, 25, tzinfo=MARKET_TIMEZONE),
            record_id=42,
        ),
    )
    pending = AsyncMock(side_effect=(entries, ()))
    mark = AsyncMock(return_value=True)
    application = SimpleNamespace(
        guild_config=AsyncMock(return_value=SimpleNamespace(ledger_channel_id="3001")),
        pending_ledger_entries=pending,
        mark_ledger_entry_posted=mark,
    )
    monkeypatch.setattr(discord, "TextChannel", _TextChannel)
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: application,
    )

    await coffee_market_cog._flush_ledger_logs(guild)

    assert channel.send.await_count == 2
    first_send = channel.send.await_args_list[0]
    second_send = channel.send.await_args_list[1]
    assert first_send.kwargs["embed"].title == "🫘 コーヒー豆を購入"
    assert second_send.kwargs["embed"].title == "☕ コーヒー豆を売却"
    assert first_send.kwargs["allowed_mentions"].everyone is False
    assert mark.await_args_list[0].kwargs == {
        "guild_id": "1001",
        "kind": "buy",
        "record_id": 41,
        "message_id": "9001",
    }
    assert mark.await_args_list[1].kwargs == {
        "guild_id": "1001",
        "kind": "manual",
        "record_id": 42,
        "message_id": "9002",
    }


def test_purchase_ledger_log_is_an_individual_embed() -> None:
    embed = _ledger_log_embed(
        PublicTradeEntry(
            user_id="2001",
            kind="buy",
            market_day=date(2026, 8, 25),
            quantity=5,
            unit_price_xp=90,
            total_xp=450,
            profit_xp=None,
            created_at=datetime(2026, 8, 25, tzinfo=MARKET_TIMEZONE),
            record_id=41,
        )
    )
    assert embed.title == "🫘 コーヒー豆を購入"
    text = embed.description or ""
    assert "<@2001>" in text
    assert "5袋 × 90 XP = **450 XP**" in text
    assert embed.footer.text == "相場 2026/08/25 00:00"


@pytest.mark.parametrize(
    ("kind", "expected_title"),
    (("manual", "☕ コーヒー豆を売却"), ("expired", "⏰ コーヒー豆を自動売却")),
)
def test_each_sale_ledger_log_is_an_individual_embed(
    kind: str,
    expected_title: str,
) -> None:
    embed = _ledger_log_embed(
        PublicTradeEntry(
            user_id="2001",
            kind=kind,
            market_day=date(2026, 8, 25),
            quantity=3,
            unit_price_xp=120,
            total_xp=360,
            profit_xp=60,
            created_at=datetime(2026, 8, 25, tzinfo=MARKET_TIMEZONE),
            record_id=42,
        )
    )
    assert embed.title == expected_title
    text = embed.description or ""
    assert "3袋 × 120 XP = **360 XP**" in text
    assert "確定損益: **+60 XP**" in text


async def test_buy_button_opens_a_one_to_ten_quantity_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = cast(
        discord.InteractionMessage,
        SimpleNamespace(edit=AsyncMock()),
    )
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            user=SimpleNamespace(id=2001),
            response=response,
            original_response=AsyncMock(return_value=message),
        ),
    )
    monkeypatch.setattr(
        coffee_market_cog, "_trade_allowed", AsyncMock(return_value=True)
    )

    await DynamicCoffeeBuyButton(1001).callback(interaction)

    response.send_message.assert_awaited_once()
    call = response.send_message.await_args
    assert call is not None
    assert call.args[0] == "購入する袋数を選んでください。"
    assert call.kwargs["ephemeral"] is True
    view = call.kwargs["view"]
    assert isinstance(view, CoffeeBuyQuantityView)
    select = cast(CoffeeBuyQuantitySelect, view.children[0])
    assert [option.label for option in select.options] == [
        f"{quantity}袋" for quantity in range(1, 11)
    ]
    assert [option.value for option in select.options] == [
        str(quantity) for quantity in range(1, 11)
    ]
    assert view.message is message


async def test_buy_quantity_select_shows_cost_and_remaining_xp_before_purchase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period = market_period_for(datetime.now(MARKET_TIMEZONE))
    market_day = period.market_day
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            id=9001,
            user=SimpleNamespace(id=2001),
            response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(
                return_value=SimpleNamespace(edit=AsyncMock())
            ),
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
                market_slot=period.market_slot,
            ),
            UserPosition(
                quantity=0,
                sellable_quantity=0,
                average_buy_price_xp=0,
                evaluation_xp=0,
                unrealized_profit_xp=0,
                earliest_expiry=None,
                purchased_this_period=False,
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
    view = CoffeeBuyQuantityView(guild_id=1001, user_id=2001)
    select = cast(CoffeeBuyQuantitySelect, view.children[0])
    cast(Any, select)._values = ["7"]

    await select.callback(interaction)

    purchase.assert_not_awaited()
    position.assert_awaited_once_with(
        guild_id="1001",
        user_id="2001",
        market_period=ANY,
    )
    edit = cast(AsyncMock, interaction.edit_original_response)
    edit.assert_awaited_once()
    call = edit.await_args
    assert call is not None
    assert "7袋 × 100 XP = **700 XP**" in call.kwargs["content"]
    assert "購入後XP: **1,300 XP**" in call.kwargs["content"]
    assert "レベルが下がります" in call.kwargs["content"]
    confirmation = call.kwargs["view"]
    assert isinstance(confirmation, CoffeeBuyConfirmationView)
    assert confirmation.quantity == 7
    assert confirmation.user_id == 2001
    assert confirmation.market_period == period
    assert confirmation.message is not None
    assert view.is_finished()


async def test_buy_quantity_select_rechecks_access_before_showing_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=False)
    response = SimpleNamespace(defer=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(user=SimpleNamespace(id=2001), response=response),
    )
    view = CoffeeBuyQuantityView(guild_id=1001, user_id=2001)
    select = cast(CoffeeBuyQuantitySelect, view.children[0])
    cast(Any, select)._values = ["7"]
    monkeypatch.setattr(coffee_market_cog, "_trade_allowed", access)

    await select.callback(interaction)

    access.assert_awaited_once_with(interaction, guild_id=1001)
    response.defer.assert_not_awaited()
    assert not view.is_finished()


async def test_confirmation_timeout_disables_buttons_and_explains_next_step() -> None:
    view = CoffeeBuyConfirmationView(
        guild_id=1001,
        user_id=2001,
        quantity=7,
        market_period=MarketPeriod(date(2026, 8, 25), 2),
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
    period = market_period_for(datetime.now(MARKET_TIMEZONE))
    market_day = period.market_day
    sellable_period = next_market_period(period)
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
            sellable_on=sellable_period.market_day,
            expires_on=market_day + timedelta(days=7),
            available_xp_after=1_300,
            purchased_slot=period.market_slot,
            sellable_slot=sellable_period.market_slot,
        )
    )
    view = CoffeeBuyConfirmationView(
        guild_id=1001,
        user_id=2001,
        quantity=7,
        market_period=period,
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
        market_period=period,
    )
    edit = cast(AsyncMock, interaction.edit_original_response)
    edit_call = edit.await_args
    assert edit_call is not None
    assert "7袋 × 100 XP = **700 XP**" in edit_call.kwargs["content"]
    assert (
        f"売却可能: **{sellable_period.market_day:%Y/%m/%d} "
        f"{sellable_period.update_hour:02d}:00から**" in edit_call.kwargs["content"]
    )
    assert "自動売却日:" in edit_call.kwargs["content"]
    assert "0:00" in edit_call.kwargs["content"]
    assert "5:00" not in edit_call.kwargs["content"]
    assert edit_call.kwargs["view"] is None
    assert view.is_finished()
    refresh.assert_awaited_once_with(
        interaction,
        now=ANY,
        ledger=True,
        ranking=False,
    )


async def test_confirmation_rejects_a_quote_from_a_previous_market_period(
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
        market_period=MarketPeriod(date(2000, 1, 1), 3),
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
    period = market_period_for(datetime.now(MARKET_TIMEZONE))
    market_day = period.market_day
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
                market_slot=period.market_slot,
            ),
            UserPosition(
                quantity=8,
                sellable_quantity=6,
                average_buy_price_xp=100,
                evaluation_xp=960,
                unrealized_profit_xp=160,
                earliest_expiry=market_day,
                purchased_this_period=False,
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
    period = market_period_for(datetime.now(MARKET_TIMEZONE))
    market_day = period.market_day
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
                market_slot=period.market_slot,
            ),
            UserPosition(
                quantity=8,
                sellable_quantity=6,
                average_buy_price_xp=100,
                evaluation_xp=960,
                unrealized_profit_xp=160,
                earliest_expiry=market_day,
                purchased_this_period=False,
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
    period = market_period_for(datetime.now(MARKET_TIMEZONE))
    market_day = period.market_day
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
        market_period=period,
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
        market_period=period,
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


async def test_intraday_tick_refreshes_market_without_refreshing_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=MARKET_TIMEZONE)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> _FixedDatetime:
            return cls.fromtimestamp(now.timestamp(), tz=tz)

    guild = SimpleNamespace(id=1001)
    application = SimpleNamespace(
        guild_configs=AsyncMock(return_value=(SimpleNamespace(guild_id="1001"),)),
        activity_version=AsyncMock(return_value=(4, 2)),
    )
    refresh = AsyncMock(return_value=True)
    monkeypatch.setattr(coffee_market_cog, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        coffee_market_cog,
        "default_application",
        lambda: application,
    )
    monkeypatch.setattr(
        coffee_market_cog, "_settle_expired", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        coffee_market_cog, "_flush_ledger_logs", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(coffee_market_cog, "_refresh_public_panels", refresh)
    cog = CoffeeMarketCog(cast(Any, SimpleNamespace(get_guild=lambda _guild_id: guild)))
    cog._rendered_period_by_guild["1001"] = MarketPeriod(date(2026, 8, 25), 1)
    cog._rendered_activity_by_guild["1001"] = (4, 2)

    await cast(Any, CoffeeMarketCog._market_tick).coro(cog)

    refresh.assert_awaited_once_with(
        guild,
        now=ANY,
        market=True,
        ranking=False,
    )
    assert cog._rendered_period_by_guild["1001"] == MarketPeriod(date(2026, 8, 25), 2)
