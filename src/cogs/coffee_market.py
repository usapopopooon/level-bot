"""コーヒー豆相場のDiscordパネルと日次処理。"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.cogs.feature_access import ensure_feature_access, format_access_roles
from src.constants import DEFAULT_EMBED_COLOR
from src.features.coffee_market import contracts as market_contracts
from src.features.coffee_market import presentation
from src.features.coffee_market.domain import (
    MARKET_UPDATE_HOURS,
    MAX_PURCHASE_QUANTITY_PER_PERIOD,
    MAX_SELL_QUANTITY,
    RANKING_WINDOW_DAYS,
    MarketPeriod,
    market_day_for,
    market_period_for,
    next_reset_at,
)
from src.features.coffee_market.runtime import default_application
from src.features.feature_access import service as feature_access_service

logger = logging.getLogger(__name__)
MARKET_TICK_SECONDS = 60.0
CONFIRMATION_TIMEOUT_SECONDS = 180
_LEDGER_FLUSH_LOCKS: dict[int, asyncio.Lock] = {}


def _panel_embed(
    quote: market_contracts.MarketQuote, *, now: datetime
) -> discord.Embed:
    reset_timestamp = int(next_reset_at(now).timestamp())
    embed = discord.Embed(
        title=presentation.PANEL_TITLE,
        description=presentation.panel_description(
            quote, next_reset_timestamp=reset_timestamp
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    update_hour = MARKET_UPDATE_HOURS[quote.market_slot]
    embed.set_footer(
        text=f"相場 {quote.market_day:%Y/%m/%d} {update_hour:02d}:00・1日4回更新"
    )
    return embed


def _ledger_log_embed(entry: market_contracts.PublicTradeEntry) -> discord.Embed:
    titles = {
        "buy": "🫘 コーヒー豆を購入",
        "manual": "☕ コーヒー豆を売却",
        "expired": "⏰ コーヒー豆を自動売却",
    }
    profit = (
        "" if entry.profit_xp is None else f"\n確定損益: **{entry.profit_xp:+,} XP**"
    )
    embed = discord.Embed(
        title=titles[entry.kind],
        description=(
            f"<@{entry.user_id}>\n"
            f"{entry.quantity:,}袋 × {entry.unit_price_xp:,} XP "
            f"= **{entry.total_xp:,} XP**{profit}"
        ),
        color=DEFAULT_EMBED_COLOR,
        timestamp=entry.created_at,
    )
    update_hour = MARKET_UPDATE_HOURS[entry.market_slot]
    embed.set_footer(text=f"相場 {entry.market_day:%Y/%m/%d} {update_hour:02d}:00")
    return embed


def _ranking_embed(
    snapshot: market_contracts.RankingSnapshot,
) -> discord.Embed:
    embed = discord.Embed(
        title=presentation.RANKING_TITLE,
        description="売却時に確定した損益のランキングです。",
        color=DEFAULT_EMBED_COLOR,
    )
    sections = (
        ("📅 本日", snapshot.daily, "本日の確定損益はまだありません。"),
        (
            f"🗓️ 過去{RANKING_WINDOW_DAYS}日",
            snapshot.last_five_days,
            f"過去{RANKING_WINDOW_DAYS}日の確定損益はまだありません。",
        ),
        ("☕ 累計", snapshot.cumulative, "確定損益はまだありません。"),
    )
    for name, entries, empty_message in sections:
        embed.add_field(
            name=name,
            value=presentation.ranking_lines(
                entries,
                empty_message=empty_message,
            ),
            inline=False,
        )
    embed.set_footer(text=f"相場日 {snapshot.market_day:%Y/%m/%d}・日本時間0:00更新")
    return embed


async def _settle_expired(guild_id: str, *, now: datetime) -> bool:
    return await default_application().settle_expired(
        guild_id=guild_id,
        market_period=market_period_for(now),
    )


async def _trade_allowed(interaction: discord.Interaction, *, guild_id: int) -> bool:
    if interaction.guild is None or interaction.guild.id != guild_id:
        await interaction.response.send_message(
            "このサーバーのパネルから操作してください。", ephemeral=True
        )
        return False
    if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
        await interaction.response.send_message(
            "メンバー情報を取得できませんでした。", ephemeral=True
        )
        return False
    if not await ensure_feature_access(
        interaction,
        guild_id=guild_id,
        feature=feature_access_service.COFFEE_MARKET,
    ):
        return False
    excluded = await default_application().is_user_excluded(
        guild_id=str(guild_id), user_id=str(interaction.user.id)
    )
    if excluded:
        await interaction.response.send_message(
            "あなたは現在XP集計の対象外です。", ephemeral=True
        )
        return False
    return True


def _market_error_message(error: market_contracts.CoffeeMarketError) -> str:
    if isinstance(error, market_contracts.InvalidQuantity):
        return f"袋数は1〜{error.maximum}の整数で入力してください。"
    if isinstance(error, market_contracts.AlreadyPurchasedThisPeriod):
        return "現在の相場での購入は完了しています。次回更新後に再び購入できます。"
    if isinstance(error, market_contracts.InsufficientXp):
        return (
            f"サーバーXPが不足しています。必要: **{error.required_xp:,} XP** / "
            f"現在: **{error.available_xp:,} XP**"
        )
    if isinstance(error, market_contracts.NoSellableBeans):
        return (
            "現在売却できる豆はありません。購入した豆は次の相場更新後から売却できます。"
        )
    if isinstance(error, market_contracts.InsufficientBeans):
        return (
            f"売却できる豆が不足しています。指定: **{error.requested:,}袋** / "
            f"売却可能: **{error.available:,}袋**"
        )
    if isinstance(error, market_contracts.IdempotencyConflict):
        return "取引履歴を確認してから、もう一度パネルからお試しください。"
    if isinstance(error, market_contracts.CoffeeMarketUnavailable):
        return "コーヒー豆相場を一時的に利用できません。時間をおいてお試しください。"
    return "取引を完了できませんでした。"


def _purchase_confirmation_message(
    *,
    quantity: int,
    unit_price_xp: int,
    available_xp: int,
) -> str:
    cost_xp = quantity * unit_price_xp
    return (
        "🫘 **購入内容を確認してください**\n"
        f"{quantity:,}袋 × {unit_price_xp:,} XP = **{cost_xp:,} XP**\n"
        f"購入後XP: **{available_xp - cost_xp:,} XP**\n\n"
        "購入するとサーバーXPとレベルが下がります。\n"
        "内容を確認し、3分以内に確定してください。"
    )


def _sale_confirmation_message(
    *,
    quantity: int,
    unit_price_xp: int,
    available_xp: int,
    sell_all: bool,
) -> str:
    payout_xp = quantity * unit_price_xp
    heading = (
        "売却可能な豆をすべて売ります" if sell_all else "売却内容を確認してください"
    )
    return (
        f"☕ **{heading}**\n"
        f"{quantity:,}袋 × {unit_price_xp:,} XP = **{payout_xp:,} XP**\n"
        f"売却後XP: **{available_xp + payout_xp:,} XP**\n\n"
        "確定後は取り消せません。3分以内に確定してください。"
    )


def _purchase_result_message(result: market_contracts.PurchaseResult) -> str:
    sellable_hour = MARKET_UPDATE_HOURS[result.sellable_slot]
    return (
        "🫘 **購入しました**\n"
        f"{result.quantity:,}袋 × {result.unit_price_xp:,} XP "
        f"= **{result.cost_xp:,} XP**\n"
        f"売却可能: **{result.sellable_on:%Y/%m/%d} {sellable_hour:02d}:00から**\n"
        f"自動売却日: **{result.expires_on:%Y/%m/%d} 0:00**\n"
        f"現在XP: **{result.available_xp_after:,} XP**"
    )


def _sale_result_message(result: market_contracts.SaleResult, *, sell_all: bool) -> str:
    heading = "売却可能な豆をすべて売却しました" if sell_all else "売却しました"
    return (
        f"☕ **{heading}**\n"
        f"{result.quantity:,}袋 × {result.unit_price_xp:,} XP "
        f"= **{result.payout_xp:,} XP**\n"
        f"確定損益: **{result.profit_xp:+,} XP**\n"
        f"現在XP: **{result.available_xp_after:,} XP**"
    )


async def _confirmation_allowed(
    interaction: discord.Interaction,
    *,
    guild_id: int,
    user_id: int,
) -> bool:
    if interaction.user.id != user_id:
        await interaction.response.send_message(
            "この取引を確定できるのは本人だけです。", ephemeral=True
        )
        return False
    return await _trade_allowed(interaction, guild_id=guild_id)


class _CoffeeConfirmationView(discord.ui.View):
    def __init__(self, *, expired_message: str) -> None:
        super().__init__(timeout=CONFIRMATION_TIMEOUT_SECONDS)
        self.expired_message = expired_message
        self.message: discord.InteractionMessage | discord.WebhookMessage | None = None

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(content=self.expired_message, view=self)
        except discord.HTTPException:
            logger.exception("Failed to expire a coffee market confirmation")


class CoffeeBuyConfirmationView(_CoffeeConfirmationView):
    def __init__(
        self,
        *,
        guild_id: int,
        user_id: int,
        quantity: int,
        market_period: MarketPeriod,
    ) -> None:
        super().__init__(
            expired_message="購入の確認期限が切れました。パネルからやり直してください。"
        )
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantity = quantity
        self.market_period = market_period
        self.event_id = f"discord-coffee-buy:{uuid4()}"

    @discord.ui.button(
        label="この内容で購入",
        emoji="🫘",
        style=discord.ButtonStyle.primary,
        custom_id="coffee-market-buy-confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if not await _confirmation_allowed(
            interaction, guild_id=self.guild_id, user_id=self.user_id
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        if market_period_for(now) != self.market_period:
            self.stop()
            await interaction.edit_original_response(
                content="相場が更新されました。現在のパネルから購入し直してください。",
                view=None,
            )
            return
        try:
            result = await default_application().purchase(
                event_id=self.event_id,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                quantity=self.quantity,
                market_period=self.market_period,
            )
        except market_contracts.CoffeeMarketError as error:
            self.stop()
            await interaction.edit_original_response(
                content=_market_error_message(error), embed=None, view=None
            )
            return
        self.stop()
        await interaction.edit_original_response(
            content=_purchase_result_message(result), embed=None, view=None
        )
        await _refresh_after_interaction(
            interaction,
            now=now,
            ledger=True,
            ranking=False,
        )

    @discord.ui.button(
        label="キャンセル",
        style=discord.ButtonStyle.secondary,
        custom_id="coffee-market-buy-cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この取引をキャンセルできるのは本人だけです。", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content="購入をキャンセルしました。", embed=None, view=None
        )


class CoffeeSellConfirmationView(_CoffeeConfirmationView):
    def __init__(
        self,
        *,
        guild_id: int,
        user_id: int,
        quantity: int,
        market_period: MarketPeriod,
        sell_all: bool,
    ) -> None:
        super().__init__(
            expired_message="売却の確認期限が切れました。パネルからやり直してください。"
        )
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantity = quantity
        self.market_period = market_period
        self.sell_all = sell_all
        event_kind = "sell-all" if sell_all else "sell"
        self.event_id = f"discord-coffee-{event_kind}:{uuid4()}"

    @discord.ui.button(
        label="この内容で売却",
        style=discord.ButtonStyle.danger,
        custom_id="coffee-market-sell-confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if not await _confirmation_allowed(
            interaction, guild_id=self.guild_id, user_id=self.user_id
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        if market_period_for(now) != self.market_period:
            self.stop()
            await interaction.edit_original_response(
                content="相場が更新されました。現在のパネルから売却し直してください。",
                view=None,
            )
            return
        try:
            result = await default_application().sell(
                event_id=self.event_id,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                quantity=self.quantity,
                market_period=self.market_period,
            )
        except market_contracts.CoffeeMarketError as error:
            self.stop()
            await interaction.edit_original_response(
                content=_market_error_message(error), embed=None, view=None
            )
            return
        self.stop()
        await interaction.edit_original_response(
            content=_sale_result_message(result, sell_all=self.sell_all),
            embed=None,
            view=None,
        )
        await _refresh_after_interaction(
            interaction,
            now=now,
            ledger=True,
            ranking=True,
        )

    @discord.ui.button(
        label="キャンセル",
        style=discord.ButtonStyle.secondary,
        custom_id="coffee-market-sell-cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この取引をキャンセルできるのは本人だけです。", ephemeral=True
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content="売却をキャンセルしました。", embed=None, view=None
        )


async def _send_purchase_confirmation(
    interaction: discord.Interaction,
    *,
    guild_id: int,
    quantity: int,
    now: datetime,
) -> None:
    try:
        settled = await _settle_expired(str(guild_id), now=now)
        quote, position = await default_application().position(
            guild_id=str(guild_id),
            user_id=str(interaction.user.id),
            market_period=market_period_for(now),
        )
        if position.purchased_this_period:
            raise market_contracts.AlreadyPurchasedThisPeriod
        cost_xp = quantity * quote.buy_price_xp
        if cost_xp > position.available_xp:
            raise market_contracts.InsufficientXp(
                required_xp=cost_xp,
                available_xp=position.available_xp,
            )
    except market_contracts.CoffeeMarketError as error:
        await interaction.edit_original_response(
            content=_market_error_message(error), embed=None, view=None
        )
        return
    if settled:
        await _refresh_after_interaction(
            interaction,
            now=now,
            ledger=True,
            ranking=True,
        )
    view = CoffeeBuyConfirmationView(
        guild_id=guild_id,
        user_id=interaction.user.id,
        quantity=quantity,
        market_period=MarketPeriod(quote.market_day, quote.market_slot),
    )
    message = await interaction.edit_original_response(
        content=_purchase_confirmation_message(
            quantity=quantity,
            unit_price_xp=quote.buy_price_xp,
            available_xp=position.available_xp,
        ),
        embed=None,
        view=view,
    )
    view.message = message


async def _send_sale_confirmation(
    interaction: discord.Interaction,
    *,
    guild_id: int,
    quantity: int | None,
    now: datetime,
) -> None:
    try:
        settled = await _settle_expired(str(guild_id), now=now)
        quote, position = await default_application().position(
            guild_id=str(guild_id),
            user_id=str(interaction.user.id),
            market_period=market_period_for(now),
        )
        sell_quantity = position.sellable_quantity if quantity is None else quantity
        if position.sellable_quantity <= 0:
            raise market_contracts.NoSellableBeans
        if sell_quantity > position.sellable_quantity:
            raise market_contracts.InsufficientBeans(
                requested=sell_quantity,
                available=position.sellable_quantity,
            )
    except market_contracts.CoffeeMarketError as error:
        await interaction.followup.send(_market_error_message(error), ephemeral=True)
        return
    if settled:
        await _refresh_after_interaction(
            interaction,
            now=now,
            ledger=True,
            ranking=True,
        )
    sell_all = quantity is None
    view = CoffeeSellConfirmationView(
        guild_id=guild_id,
        user_id=interaction.user.id,
        quantity=sell_quantity,
        market_period=MarketPeriod(quote.market_day, quote.market_slot),
        sell_all=sell_all,
    )
    message = await interaction.followup.send(
        _sale_confirmation_message(
            quantity=sell_quantity,
            unit_price_xp=quote.sell_price_xp,
            available_xp=position.available_xp,
            sell_all=sell_all,
        ),
        view=view,
        ephemeral=True,
        wait=True,
    )
    view.message = message


class CoffeeBuyQuantitySelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, *, guild_id: int, user_id: int) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        super().__init__(
            placeholder="購入する袋数を選択",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=f"{quantity}袋", value=str(quantity))
                for quantity in range(1, MAX_PURCHASE_QUANTITY_PER_PERIOD + 1)
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "この購入メニューを使えるのは開いた本人だけです。",
                ephemeral=True,
            )
            return
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        quantity = int(self.values[0])
        await interaction.response.defer()
        if self.view is not None:
            self.view.stop()
        now = datetime.now(UTC)
        await _send_purchase_confirmation(
            interaction,
            guild_id=self.guild_id,
            quantity=quantity,
            now=now,
        )


class CoffeeBuyQuantityView(discord.ui.View):
    def __init__(self, *, guild_id: int, user_id: int) -> None:
        super().__init__(timeout=CONFIRMATION_TIMEOUT_SECONDS)
        self.message: discord.InteractionMessage | None = None
        self.add_item(CoffeeBuyQuantitySelect(guild_id=guild_id, user_id=user_id))

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Select):
                child.disabled = True
        if self.message is None:
            return
        try:
            await self.message.edit(
                content="袋数選択の期限が切れました。パネルからやり直してください。",
                view=self,
            )
        except discord.HTTPException:
            logger.exception("Failed to expire a coffee market quantity select")


class CoffeeSellModal(discord.ui.Modal, title="コーヒー豆を売る"):
    quantity: discord.ui.TextInput[CoffeeSellModal] = discord.ui.TextInput(
        label=f"売却する袋数（1〜{MAX_SELL_QUANTITY}）",
        placeholder="例: 10",
        min_length=1,
        max_length=len(str(MAX_SELL_QUANTITY)),
    )

    def __init__(self, guild_id: int) -> None:
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        try:
            quantity = int(self.quantity.value)
        except ValueError:
            await interaction.response.send_message(
                f"袋数は1〜{MAX_SELL_QUANTITY}の整数で入力してください。",
                ephemeral=True,
            )
            return
        if not 1 <= quantity <= MAX_SELL_QUANTITY:
            await interaction.response.send_message(
                f"袋数は1〜{MAX_SELL_QUANTITY}の整数で入力してください。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        await _send_sale_confirmation(
            interaction,
            guild_id=self.guild_id,
            quantity=quantity,
            now=now,
        )


class DynamicCoffeeBuyButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:coffee-market:buy:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="豆を買う",
                emoji="🫘",
                style=discord.ButtonStyle.primary,
                custom_id=f"level:coffee-market:buy:{guild_id}",
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCoffeeBuyButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        view = CoffeeBuyQuantityView(
            guild_id=self.guild_id,
            user_id=interaction.user.id,
        )
        await interaction.response.send_message(
            "購入する袋数を選んでください。",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


class DynamicCoffeeSellButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:coffee-market:sell:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="豆を売る",
                style=discord.ButtonStyle.success,
                custom_id=f"level:coffee-market:sell:{guild_id}",
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCoffeeSellButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        await interaction.response.send_modal(CoffeeSellModal(self.guild_id))


class DynamicCoffeeSellAllButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:coffee-market:sell-all:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="全部売る",
                style=discord.ButtonStyle.danger,
                custom_id=f"level:coffee-market:sell-all:{guild_id}",
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCoffeeSellAllButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        await _send_sale_confirmation(
            interaction,
            guild_id=self.guild_id,
            quantity=None,
            now=now,
        )


class DynamicCoffeePositionButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:coffee-market:position:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="保有豆",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:coffee-market:position:{guild_id}",
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCoffeePositionButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        settled = await _settle_expired(str(self.guild_id), now=now)
        if settled:
            await _refresh_after_interaction(
                interaction,
                now=now,
                ledger=True,
                ranking=True,
            )
        quote, position = await default_application().position(
            guild_id=str(self.guild_id),
            user_id=str(interaction.user.id),
            market_period=market_period_for(now),
        )
        await interaction.followup.send(
            embed=discord.Embed(
                title="自分のコーヒー豆",
                description=presentation.position_description(
                    position, market_day=quote.market_day
                ),
                color=DEFAULT_EMBED_COLOR,
            ),
            ephemeral=True,
        )


class DynamicCoffeeHistoryButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:coffee-market:history:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="取引履歴",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:coffee-market:history:{guild_id}",
                row=1,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCoffeeHistoryButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        settled = await _settle_expired(str(self.guild_id), now=now)
        if settled:
            await _refresh_after_interaction(
                interaction,
                now=now,
                ledger=True,
                ranking=True,
            )
        history = await default_application().user_history(
            guild_id=str(self.guild_id),
            user_id=str(interaction.user.id),
        )
        await interaction.followup.send(
            embed=discord.Embed(
                title="自分の豆取引履歴",
                description=presentation.history_lines(history),
                color=DEFAULT_EMBED_COLOR,
            ),
            ephemeral=True,
        )


class DynamicCoffeeRankingButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:coffee-market:ranking:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="ランキング",
                emoji="🏆",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:coffee-market:ranking:{guild_id}",
                row=1,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCoffeeRankingButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await _trade_allowed(interaction, guild_id=self.guild_id):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        settled = await _settle_expired(str(self.guild_id), now=now)
        if settled:
            await _refresh_after_interaction(
                interaction,
                now=now,
                ledger=True,
                ranking=True,
            )
        ranking = await default_application().rankings(
            guild_id=str(self.guild_id),
            market_day=market_day_for(now),
        )
        await interaction.followup.send(
            embed=_ranking_embed(ranking),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class CoffeeMarketPanelView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(DynamicCoffeeBuyButton(guild_id))
        self.add_item(DynamicCoffeePositionButton(guild_id))
        self.add_item(DynamicCoffeeSellButton(guild_id))
        self.add_item(DynamicCoffeeSellAllButton(guild_id))
        self.add_item(DynamicCoffeeHistoryButton(guild_id))
        self.add_item(DynamicCoffeeRankingButton(guild_id))


async def _current_panel_embed(guild_id: str, *, now: datetime) -> discord.Embed:
    quote = await default_application().quote(
        guild_id=guild_id,
        market_period=market_period_for(now),
    )
    return _panel_embed(quote, now=now)


async def _current_ranking_embed(guild_id: str, *, now: datetime) -> discord.Embed:
    ranking = await default_application().rankings(
        guild_id=guild_id,
        market_day=market_day_for(now),
    )
    return _ranking_embed(ranking)


async def _flush_ledger_logs(guild: discord.Guild) -> bool:
    """未投稿の全取引を、指定台帳チャンネルへ1件ずつ古い順に投稿する。"""
    lock = _LEDGER_FLUSH_LOCKS.setdefault(guild.id, asyncio.Lock())
    async with lock:
        application = default_application()
        try:
            config = await application.guild_config(guild_id=str(guild.id))
            if config is None or config.ledger_channel_id is None:
                return True
            channel = guild.get_channel(int(config.ledger_channel_id))
            if not isinstance(channel, discord.TextChannel):
                logger.warning(
                    "Coffee market ledger channel is unavailable: guild=%s channel=%s",
                    guild.id,
                    config.ledger_channel_id,
                )
                return False
            while True:
                entries = await application.pending_ledger_entries(
                    guild_id=str(guild.id)
                )
                if not entries:
                    return True
                for entry in entries:
                    try:
                        message = await channel.send(
                            embed=_ledger_log_embed(entry),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    except discord.HTTPException:
                        logger.exception(
                            "Failed to post coffee market ledger entry: "
                            "guild=%s kind=%s record=%s",
                            guild.id,
                            entry.kind,
                            entry.record_id,
                        )
                        return False
                    marked = await application.mark_ledger_entry_posted(
                        guild_id=str(guild.id),
                        kind=entry.kind,
                        record_id=entry.record_id,
                        message_id=str(message.id),
                    )
                    if not marked:
                        logger.warning(
                            "Coffee market ledger entry was already marked: "
                            "guild=%s kind=%s record=%s",
                            guild.id,
                            entry.kind,
                            entry.record_id,
                        )
        except market_contracts.CoffeeMarketError:
            logger.exception(
                "Failed to flush coffee market ledger logs: guild=%s",
                guild.id,
            )
            return False


async def _edit_configured_panel(
    guild: discord.Guild,
    *,
    channel_id: str | None,
    message_id: str | None,
    embed: discord.Embed,
    view: discord.ui.View | None = None,
) -> None:
    if channel_id is None or message_id is None:
        return
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        logger.warning(
            "Coffee market panel channel is unavailable: guild=%s channel=%s",
            guild.id,
            channel_id,
        )
        return
    message = await channel.fetch_message(int(message_id))
    await message.edit(
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def _refresh_public_panels(
    guild: discord.Guild,
    *,
    now: datetime,
    market: bool = False,
    ranking: bool = False,
) -> bool:
    config = await default_application().guild_config(guild_id=str(guild.id))
    if config is None:
        return True
    updates: list[tuple[str, str, str, discord.Embed, discord.ui.View | None]] = []
    if market and config.panel_channel_id and config.panel_message_id:
        updates.append(
            (
                "market",
                config.panel_channel_id,
                config.panel_message_id,
                await _current_panel_embed(str(guild.id), now=now),
                CoffeeMarketPanelView(guild.id),
            )
        )
    if ranking and config.ranking_channel_id and config.ranking_message_id:
        updates.append(
            (
                "ranking",
                config.ranking_channel_id,
                config.ranking_message_id,
                await _current_ranking_embed(str(guild.id), now=now),
                None,
            )
        )
    refreshed = True
    for panel_kind, channel_id, message_id, embed, view in updates:
        try:
            await _edit_configured_panel(
                guild,
                channel_id=channel_id,
                message_id=message_id,
                embed=embed,
                view=view,
            )
        except discord.NotFound:
            logger.warning(
                "Coffee market %s panel message is unavailable: guild=%s",
                panel_kind,
                guild.id,
            )
        except discord.HTTPException:
            refreshed = False
            logger.exception(
                "Failed to update coffee market %s panel: guild=%s",
                panel_kind,
                guild.id,
            )
    return refreshed


async def _refresh_after_interaction(
    interaction: discord.Interaction,
    *,
    now: datetime,
    ledger: bool,
    ranking: bool,
) -> None:
    if interaction.guild is None:
        return
    try:
        if ledger:
            await _flush_ledger_logs(interaction.guild)
        await _refresh_public_panels(
            interaction.guild,
            now=now,
            ranking=ranking,
        )
    except market_contracts.CoffeeMarketError:
        logger.exception(
            "Failed to refresh coffee market activity panels: guild=%s",
            interaction.guild.id,
        )


class CoffeeMarketCog(commands.Cog):
    coffee_market_group = app_commands.Group(
        name="coffee-market",
        description="コーヒー豆相場",
    )
    coffee_market_access_group = app_commands.Group(
        name="access-role",
        description="コーヒー豆相場の利用ロール管理",
        parent=coffee_market_group,
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._rendered_period_by_guild: dict[str, MarketPeriod] = {}
        self._rendered_activity_by_guild: dict[
            str, tuple[int, int, tuple[str, ...]]
        ] = {}

    async def cog_load(self) -> None:
        self._market_tick.start()

    async def cog_unload(self) -> None:
        self._market_tick.cancel()

    @tasks.loop(seconds=MARKET_TICK_SECONDS)
    async def _market_tick(self) -> None:
        now = datetime.now(UTC)
        period = market_period_for(now)
        try:
            configs = await default_application().guild_configs()
        except market_contracts.CoffeeMarketError:
            logger.exception("Failed to load coffee market panel configurations")
            return
        for config in configs:
            try:
                settled = await _settle_expired(config.guild_id, now=now)
                activity_version = await default_application().activity_version(
                    guild_id=config.guild_id
                )
                rendered_period = self._rendered_period_by_guild.get(config.guild_id)
                period_changed = rendered_period != period
                day_changed = (
                    rendered_period is None
                    or rendered_period.market_day != period.market_day
                )
                activity_changed = (
                    self._rendered_activity_by_guild.get(config.guild_id)
                    != activity_version
                )
                guild = self.bot.get_guild(int(config.guild_id))
                if guild is None:
                    continue
                await _flush_ledger_logs(guild)
                if not period_changed and not activity_changed and not settled:
                    continue
                refreshed = await _refresh_public_panels(
                    guild,
                    now=now,
                    market=period_changed,
                    ranking=day_changed or activity_changed or settled,
                )
                if refreshed and period_changed:
                    self._rendered_period_by_guild[config.guild_id] = period
                if refreshed and activity_changed:
                    self._rendered_activity_by_guild[config.guild_id] = activity_version
            except (
                discord.HTTPException,
                market_contracts.CoffeeMarketError,
            ):
                logger.exception(
                    "Failed to update coffee market: guild=%s", config.guild_id
                )

    @_market_tick.before_loop
    async def _before_market_tick(self) -> None:
        await self.bot.wait_until_ready()

    @coffee_market_group.command(
        name="panel", description="このチャンネルにコーヒー豆相場パネルを投稿"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def post_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(
            interaction.channel, discord.TextChannel
        ):
            await interaction.response.send_message(
                "サーバーのテキストチャンネルで実行してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = str(interaction.guild.id)
        now = datetime.now(UTC)
        await _settle_expired(guild_id, now=now)
        message = await interaction.channel.send(
            embed=await _current_panel_embed(guild_id, now=now),
            view=CoffeeMarketPanelView(interaction.guild.id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await default_application().save_panel(
            guild_id=guild_id,
            panel_kind="market",
            channel_id=str(interaction.channel.id),
            message_id=str(message.id),
        )
        self._rendered_period_by_guild[guild_id] = market_period_for(now)
        await interaction.edit_original_response(content="パネルを投稿しました。")

    @coffee_market_group.command(
        name="ledger",
        description="このチャンネルを取引台帳に設定",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def configure_ledger(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(
            interaction.channel, discord.TextChannel
        ):
            await interaction.response.send_message(
                "サーバーのテキストチャンネルで実行してください。", ephemeral=True
            )
            return
        guild_id = str(interaction.guild.id)
        await default_application().save_ledger_channel(
            guild_id=guild_id,
            channel_id=str(interaction.channel.id),
        )
        await interaction.response.send_message(
            "このチャンネルをコーヒー豆取引台帳に設定しました。",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await _settle_expired(guild_id, now=datetime.now(UTC))
        await _flush_ledger_logs(interaction.guild)

    @coffee_market_group.command(
        name="ranking-panel",
        description="このチャンネルに豆相場ランキングパネルを投稿",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def post_ranking_panel(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(
            interaction.channel, discord.TextChannel
        ):
            await interaction.response.send_message(
                "サーバーのテキストチャンネルで実行してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = str(interaction.guild.id)
        now = datetime.now(UTC)
        await _settle_expired(guild_id, now=now)
        message = await interaction.channel.send(
            embed=await _current_ranking_embed(guild_id, now=now),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await default_application().save_panel(
            guild_id=guild_id,
            panel_kind="ranking",
            channel_id=str(interaction.channel.id),
            message_id=str(message.id),
        )
        await interaction.edit_original_response(content="パネルを投稿しました。")

    @coffee_market_group.command(
        name="ranking", description="本日・過去5日・累計の豆相場ランキングを表示"
    )
    async def show_ranking(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        if not await _trade_allowed(interaction, guild_id=interaction.guild.id):
            return
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "メッセージを投稿できるチャンネルで実行してください。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        now = datetime.now(UTC)
        guild_id = str(interaction.guild.id)
        settled = await _settle_expired(guild_id, now=now)
        if settled:
            await _refresh_after_interaction(
                interaction,
                now=now,
                ledger=True,
                ranking=True,
            )
        ranking = await default_application().rankings(
            guild_id=guild_id, market_day=market_day_for(now)
        )
        await channel.send(
            embed=_ranking_embed(ranking),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.edit_original_response(content="ランキングを投稿しました。")

    @coffee_market_access_group.command(
        name="add", description="利用できるロールを追加"
    )
    @app_commands.describe(role="コーヒー豆相場の利用を許可するロール")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_access_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        added = await default_application().add_access_role(
            guild_id=str(interaction.guild.id),
            role_id=str(role.id),
        )
        message = (
            f"コーヒー豆相場の利用ロールに {role.mention} を追加しました。"
            if added
            else f"{role.mention} はすでに利用ロールへ追加されています。"
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @coffee_market_access_group.command(name="remove", description="利用ロールを削除")
    @app_commands.describe(role="コーヒー豆相場の利用許可から外すロール")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_access_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        removed = await default_application().remove_access_role(
            guild_id=str(interaction.guild.id),
            role_id=str(role.id),
        )
        message = (
            f"コーヒー豆相場の利用ロールから {role.mention} を削除しました。"
            if removed
            else f"{role.mention} は利用ロールに設定されていません。"
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @coffee_market_access_group.command(name="list", description="利用ロールを表示")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_access_roles(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        role_ids = await default_application().list_access_role_ids(
            guild_id=str(interaction.guild.id)
        )
        message = (
            "コーヒー豆相場の利用ロール: " + format_access_roles(role_ids)
            if role_ids
            else "利用ロールは未設定です。現在は全員が利用できます。"
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


def register_coffee_market_dynamic_items(bot: commands.Bot) -> None:
    bot.add_dynamic_items(
        DynamicCoffeeBuyButton,
        DynamicCoffeeSellButton,
        DynamicCoffeeSellAllButton,
        DynamicCoffeePositionButton,
        DynamicCoffeeHistoryButton,
        DynamicCoffeeRankingButton,
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CoffeeMarketCog(bot))
