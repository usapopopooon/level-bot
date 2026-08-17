"""カフェ・コレクションの抽選フローと常設パネルUI。"""

from __future__ import annotations

import re
from uuid import uuid4

import discord

from src.cogs.cafe_gacha_collection import _show_collection
from src.cogs.cafe_gacha_common import (
    MIN_DRAW_REWARD_XP,
    _earned_xp,
    _next_hour_label,
    _request_level_sync,
)
from src.cogs.cafe_gacha_notifications import _publish_draw, _publish_draws
from src.cogs.feature_access import ensure_feature_access
from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import (
    CARDS,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
    RARITY_ORDER,
    RARITY_TOTAL_WEIGHTS,
    rarity_label,
)
from src.features.feature_access import service as feature_access_service


async def _perform_draw(
    interaction: discord.Interaction,
    *,
    guild_id: int,
    event_id: str,
    allow_paid: bool,
    expected_cost_xp: int | None = None,
) -> None:
    guild = interaction.guild
    if guild is None or guild.id != guild_id:
        await interaction.followup.send(
            "このサーバーでは利用できません。", ephemeral=True
        )
        return
    total_xp = await _earned_xp(str(guild.id), str(interaction.user.id))
    async with async_session() as session:
        result = await service.draw_card(
            session,
            event_id=event_id,
            guild_id=str(guild.id),
            user_id=str(interaction.user.id),
            display_name=interaction.user.display_name,
            earned_xp=total_xp,
            allow_paid=allow_paid,
            expected_cost_xp=expected_cost_xp,
        )
    if result.status == "confirmation_required":
        await interaction.followup.send(
            "無料枠または消費XPが変わったため確定しませんでした。"
            "もう一度ボタンを押して内容を確認してください。",
            ephemeral=True,
        )
        return
    if result.status == "insufficient_xp":
        await interaction.followup.send(
            f"XPが足りません。現在 **{result.wallet_before.available_xp:,} XP** です。",
            ephemeral=True,
        )
        return
    if result.status == "hourly_limit":
        await interaction.followup.send(
            f"1時間の上限 **{MAX_HOURLY_DRAWS}回** に達しました。"
            f"次は **{_next_hour_label()}** から引けます。",
            ephemeral=True,
        )
        return
    if result.status == "conflict":
        await interaction.followup.send(
            "操作IDが別の抽選で使用済みです。もう一度ボタンを押してください。",
            ephemeral=True,
        )
        return
    if result.draw is None:
        await interaction.followup.send(
            "抽選結果を取得できませんでした。", ephemeral=True
        )
        return
    await _request_level_sync(str(guild.id))
    published = await _publish_draw(guild, result.draw)
    if not published:
        await interaction.followup.send(
            "抽選は確定しましたが、カフェ台帳へ投稿できませんでした。管理者に連絡してください。",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        (
            "抽選が完了しました。**カフェ台帳**で結果を確認してください。\n"
            f"現在XP: **{result.wallet_after.available_xp:,} XP**"
        ),
        ephemeral=True,
    )


async def _perform_ten_draw(
    interaction: discord.Interaction,
    *,
    guild_id: int,
    event_id: str,
    count: int = MAX_HOURLY_DRAWS,
    allow_paid: bool = True,
    expected_cost_xp: int | None = None,
) -> None:
    guild = interaction.guild
    if guild is None or guild.id != guild_id:
        await interaction.followup.send(
            "このサーバーでは利用できません。", ephemeral=True
        )
        return
    total_xp = await _earned_xp(str(guild.id), str(interaction.user.id))
    async with async_session() as session:
        result = await service.draw_cards(
            session,
            event_id=event_id,
            guild_id=str(guild.id),
            user_id=str(interaction.user.id),
            display_name=interaction.user.display_name,
            earned_xp=total_xp,
            count=count,
            allow_paid=allow_paid,
            expected_cost_xp=expected_cost_xp,
        )
    if result.status == "confirmation_required":
        await interaction.followup.send(
            "無料枠または消費XPが変わったため確定しませんでした。"
            "もう一度まとめ引きの内容を確認してください。",
            ephemeral=True,
        )
        return
    if result.status == "insufficient_xp":
        await interaction.followup.send(
            f"XPが足りません。現在 **{result.wallet_before.available_xp:,} XP** です。",
            ephemeral=True,
        )
        return
    if result.status == "hourly_limit":
        await interaction.followup.send(
            f"{count}枚のまとめ引きには、この時間の抽選枠が{count}回分必要です。"
            f"次は **{_next_hour_label()}** から引けます。",
            ephemeral=True,
        )
        return
    if result.status == "conflict":
        await interaction.followup.send(
            "操作IDが別の抽選で使用済みです。もう一度ボタンを押してください。",
            ephemeral=True,
        )
        return
    if len(result.draws) != count:
        await interaction.followup.send(
            "まとめ引きの抽選結果を取得できませんでした。", ephemeral=True
        )
        return
    await _request_level_sync(str(guild.id))
    published = await _publish_draws(guild, result.draws)
    if not published:
        await interaction.followup.send(
            "まとめ引きは確定しましたが、カフェ台帳へ投稿できませんでした。管理者に連絡してください。",
            ephemeral=True,
        )
        return
    await interaction.followup.send(
        (
            f"{count}枚のまとめ引きが完了しました。"
            "**カフェ台帳**で結果を確認してください。\n"
            f"現在XP: **{result.wallet_after.available_xp:,} XP**"
        ),
        ephemeral=True,
    )


def _affordable_batch_count(availability: service.DrawAvailability) -> int:
    balance = availability.wallet.available_xp
    count = 0
    for index in range(min(MAX_HOURLY_DRAWS, availability.available_count)):
        cost_xp = 0 if availability.has_free_draw and index == 0 else PAID_DRAW_COST_XP
        if balance < cost_xp:
            break
        balance += MIN_DRAW_REWARD_XP - cost_xp
        count += 1
    return count


def _draw_confirmation_text(
    availability: service.DrawAvailability,
    *,
    count: int,
) -> str:
    cost_xp = availability.cost_for(count)
    free_text = "（本日の無料1枚を含む）" if availability.has_free_draw else ""
    draw_label = "1枚を引きます" if count == 1 else f"{count}枚をまとめて引きます"
    minimum_reward = count * MIN_DRAW_REWARD_XP
    minimum_balance_after = availability.wallet.available_xp + minimum_reward - cost_xp
    reinvest_text = (
        "\n獲得XPを次の1枚の費用に充てながら引きます。"
        if cost_xp > availability.wallet.available_xp
        else ""
    )
    return (
        f"**{draw_label}**{free_text}。\n"
        f"現在XP: **{availability.wallet.available_xp:,} XP**\n"
        f"消費: **{cost_xp:,} XP**\n"
        f"最低獲得: **{minimum_reward:,} XP**\n"
        f"抽選後: **{minimum_balance_after:,} XP以上**\n"
        f"この時間の残り枠: {availability.hourly_remaining} → "
        f"**{availability.hourly_remaining - count}回**"
        f"{reinvest_text}"
    )


class DrawConfirmView(discord.ui.View):
    def __init__(
        self, guild_id: int, user_id: int, count: int, expected_cost_xp: int
    ) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.count = count
        self.expected_cost_xp = expected_cost_xp
        self.event_id = str(uuid4())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return False
        return await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        )

    @discord.ui.button(label="この内容で引く", style=discord.ButtonStyle.primary)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await interaction.response.edit_message(
            content="抽選しています…",
            view=None,
        )
        if self.count == 1:
            await _perform_draw(
                interaction,
                guild_id=self.guild_id,
                event_id=self.event_id,
                allow_paid=True,
                expected_cost_xp=self.expected_cost_xp,
            )
        else:
            await _perform_ten_draw(
                interaction,
                guild_id=self.guild_id,
                event_id=self.event_id,
                count=self.count,
                allow_paid=True,
                expected_cost_xp=self.expected_cost_xp,
            )
        self.stop()

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await interaction.response.edit_message(
            content="抽選をキャンセルしました。", view=None
        )
        self.stop()


async def _prepare_draw(
    interaction: discord.Interaction,
    *,
    guild_id: int,
    requested_count: int,
) -> None:
    guild = interaction.guild
    if guild is None or guild.id != guild_id:
        await interaction.followup.send(
            "このサーバーでは利用できません。", ephemeral=True
        )
        return
    earned_xp = await _earned_xp(str(guild_id), str(interaction.user.id))
    async with async_session() as session:
        availability = await service.draw_availability(
            session,
            guild_id=str(guild_id),
            user_id=str(interaction.user.id),
            earned_xp=earned_xp,
        )
    if availability.hourly_remaining == 0:
        await interaction.followup.send(
            f"1時間の上限 **{MAX_HOURLY_DRAWS}回** に達しました。"
            f"次は **{_next_hour_label()}** から引けます。",
            ephemeral=True,
        )
        return
    count = 1 if requested_count == 1 else _affordable_batch_count(availability)
    cost_xp = availability.cost_for(count)
    if count == 0 or (
        requested_count == 1 and cost_xp > availability.wallet.available_xp
    ):
        await interaction.followup.send(
            f"XPが足りません。現在 **{availability.wallet.available_xp:,} XP** です。",
            ephemeral=True,
        )
        return
    if cost_xp == 0 and requested_count == 1:
        await _perform_draw(
            interaction,
            guild_id=guild_id,
            event_id=str(interaction.id),
            allow_paid=False,
        )
        return
    await interaction.followup.send(
        _draw_confirmation_text(availability, count=count),
        view=DrawConfirmView(guild_id, interaction.user.id, count, cost_xp),
        ephemeral=True,
    )


class DynamicCafeDrawButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:cafe:draw:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="一枚引く",
                emoji="☕",
                style=discord.ButtonStyle.primary,
                custom_id=f"level:cafe:draw:{guild_id}",
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCafeDrawButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _prepare_draw(
            interaction,
            guild_id=self.guild_id,
            requested_count=1,
        )


class DynamicCafeTenDrawButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:cafe:draw10:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="まとめて引く（最大10枚）",
                emoji="🎟️",
                style=discord.ButtonStyle.success,
                custom_id=f"level:cafe:draw10:{guild_id}",
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCafeTenDrawButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _prepare_draw(
            interaction,
            guild_id=self.guild_id,
            requested_count=MAX_HOURLY_DRAWS,
        )


class DynamicCafeCollectionButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:cafe:collection:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="コレクション・XP交換",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:cafe:collection:{guild_id}",
                row=1,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCafeCollectionButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _show_collection(interaction, self.guild_id)


class DynamicCafeCatalogButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:cafe:catalog:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="排出一覧",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:cafe:catalog:{guild_id}",
                row=1,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCafeCatalogButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        embeds = []
        for rarity in RARITY_ORDER:
            lines = [
                (
                    f"**{card.name}** {card.weight / 100:.2f}% · "
                    f"獲得/交換 {card.draw_reward_xp} XP"
                )
                for card in CARDS
                if card.rarity == rarity
            ]
            embeds.append(
                discord.Embed(
                    title=(
                        f"☕ {rarity_label(rarity)} 排出一覧 "
                        f"（合計 {RARITY_TOTAL_WEIGHTS[rarity] / 100:.1f}%）"
                    ),
                    description="\n".join(lines),
                    color=DEFAULT_EMBED_COLOR,
                )
            )
        embeds[0].set_footer(
            text="表示は基準確率。未収集は同じレアリティ内で2倍優遇されます。"
        )
        await interaction.response.send_message(embeds=embeds, ephemeral=True)


class DynamicCafeBalanceButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:cafe:balance:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="自分のXP・残り枠",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:cafe:balance:{guild_id}",
                row=1,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCafeBalanceButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        total_xp = await _earned_xp(str(self.guild_id), str(interaction.user.id))
        async with async_session() as session:
            availability = await service.draw_availability(
                session,
                guild_id=str(self.guild_id),
                user_id=str(interaction.user.id),
                earned_xp=total_xp,
            )
        wallet = availability.wallet
        free_status = "利用できます" if availability.has_free_draw else "使用済み"
        await interaction.followup.send(
            (
                f"獲得・受取XP: **{wallet.total_xp:,} XP**\n"
                f"使用・譲渡済み: **{wallet.spent_xp:,} XP**\n"
                f"現在XP: **{wallet.available_xp:,} XP**\n\n"
                f"本日の無料1枚: **{free_status}**\n"
                f"この時間の残り: **{availability.hourly_remaining}/"
                f"{MAX_HOURLY_DRAWS}回**\n"
                "1日合計の上限はありません。"
            ),
            ephemeral=True,
        )


class CafeGachaPanelView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(DynamicCafeDrawButton(guild_id))
        self.add_item(DynamicCafeTenDrawButton(guild_id))
        self.add_item(DynamicCafeCollectionButton(guild_id))
        self.add_item(DynamicCafeCatalogButton(guild_id))
        self.add_item(DynamicCafeBalanceButton(guild_id))
