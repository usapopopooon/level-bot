"""カフェ・コレクションの重複カード交換UI。"""

from __future__ import annotations

from uuid import uuid4

import discord

from src.cogs.cafe_gacha_common import _request_level_sync
from src.cogs.cafe_gacha_notifications import _publish_redemption
from src.cogs.feature_access import ensure_feature_access
from src.database.engine import async_session
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import (
    CARDS_BY_KEY,
    RARITY_ORDER,
    Rarity,
    rarity_label,
)
from src.features.cafe_gacha.medals import MEDALS_BY_RARITY
from src.features.feature_access import service as feature_access_service


class RedemptionConfirmView(discord.ui.View):
    def __init__(
        self, guild_id: int, user_id: int, reward_key: str, quantity: int
    ) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.reward_key = reward_key
        self.quantity = quantity
        self.event_id = str(uuid4())

    @discord.ui.button(label="このカードを交換する", style=discord.ButtonStyle.danger)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id or interaction.guild is None:
            await interaction.response.send_message(
                "本人だけが確定できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.edit_message(content="交換しています…", view=None)
        self.stop()
        async with async_session() as session:
            result = await service.redeem_cards(
                session,
                event_id=self.event_id,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                display_name=interaction.user.display_name,
                quantities={self.reward_key: self.quantity},
            )
        if result.status != "redeemed" or result.redemption is None:
            await interaction.followup.send(
                "重複枚数が変わったため交換できませんでした。コレクションを開き直してください。",
                ephemeral=True,
            )
            return
        await _request_level_sync(str(self.guild_id))
        await _publish_redemption(interaction.guild, result.redemption)
        await interaction.followup.send(
            f"{result.redemption.reward_xp:,} XP を受け取りました。",
            ephemeral=True,
        )

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content="交換をキャンセルしました。", view=None
        )
        self.stop()


class CustomQuantityModal(discord.ui.Modal, title="交換する重複枚数"):
    quantity: discord.ui.TextInput[CustomQuantityModal] = discord.ui.TextInput(
        label="枚数", placeholder="1", min_length=1, max_length=4
    )

    def __init__(
        self, guild_id: int, user_id: int, reward_key: str, maximum: int
    ) -> None:
        super().__init__()
        self.guild_id = guild_id
        self.user_id = user_id
        self.reward_key = reward_key
        self.maximum = maximum

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        try:
            quantity = int(self.quantity.value)
        except ValueError:
            quantity = 0
        if not 1 <= quantity <= self.maximum:
            await interaction.response.send_message(
                f"1〜{self.maximum} の枚数を入力してください。", ephemeral=True
            )
            return
        await _send_redemption_confirmation(
            interaction,
            self.guild_id,
            self.user_id,
            self.reward_key,
            quantity,
            self.maximum + 1,
        )


async def _send_redemption_confirmation(
    interaction: discord.Interaction,
    guild_id: int,
    user_id: int,
    reward_key: str,
    quantity: int,
    current_count: int,
) -> None:
    card = CARDS_BY_KEY[reward_key]
    reward_xp = card.exchange_xp * quantity
    await interaction.response.send_message(
        (
            f"**{rarity_label(card.rarity)}｜{card.name} × {quantity}枚** "
            "を交換します。\n"
            f"所持: {current_count} → **{current_count - quantity}枚**\n"
            f"受取: **{reward_xp:,} XP**\n"
            "コレクション用の最初の1枚は残ります。"
        ),
        view=RedemptionConfirmView(guild_id, user_id, reward_key, quantity),
        ephemeral=True,
    )


class RedemptionQuantityView(discord.ui.View):
    def __init__(
        self, guild_id: int, user_id: int, reward_key: str, maximum: int
    ) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.reward_key = reward_key
        self.maximum = maximum

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

    @discord.ui.button(label="このカードを1枚交換", style=discord.ButtonStyle.primary)
    async def one(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await _send_redemption_confirmation(
            interaction,
            self.guild_id,
            self.user_id,
            self.reward_key,
            1,
            self.maximum + 1,
        )

    @discord.ui.button(
        label="このカードの重複を全交換",
        style=discord.ButtonStyle.secondary,
    )
    async def all_duplicates(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await _send_redemption_confirmation(
            interaction,
            self.guild_id,
            self.user_id,
            self.reward_key,
            self.maximum,
            self.maximum + 1,
        )

    @discord.ui.button(
        label="このカードの枚数を指定",
        style=discord.ButtonStyle.secondary,
    )
    async def custom(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        await interaction.response.send_modal(
            CustomQuantityModal(
                self.guild_id, self.user_id, self.reward_key, self.maximum
            )
        )


class RedemptionSelect(discord.ui.Select[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
        rarity: Rarity,
        page: int = 0,
    ) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        self.maximum_by_key = {
            item.card.key: item.exchangeable_count
            for item in collection
            if item.exchangeable_count > 0 and item.card.rarity == rarity
        }
        all_options = [
            discord.SelectOption(
                label=f"{rarity_label(item.card.rarity)}｜{item.card.name}",
                description=(
                    f"交換可 {item.exchangeable_count}枚 · "
                    f"1枚 {item.card.exchange_xp} XP"
                ),
                value=item.card.key,
            )
            for item in collection
            if item.exchangeable_count > 0 and item.card.rarity == rarity
        ]
        options = all_options[page * 25 : (page + 1) * 25]
        super().__init__(placeholder="交換するカードを1種類選ぶ", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        key = self.values[0]
        card = CARDS_BY_KEY[key]
        maximum = self.maximum_by_key[key]
        await interaction.response.send_message(
            (
                f"**{rarity_label(card.rarity)}｜{card.name}** "
                "の交換枚数を選んでください"
                f"（重複 {maximum}枚）。"
            ),
            view=RedemptionQuantityView(self.guild_id, self.user_id, key, maximum),
            ephemeral=True,
        )


class RedemptionSelectView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
        rarity: Rarity,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(RedemptionSelect(guild_id, user_id, collection, rarity, page))


class IndividualExchangeButton(discord.ui.Button[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
    ) -> None:
        super().__init__(
            label="重複を選んでXP交換",
            style=discord.ButtonStyle.primary,
            emoji="🎴",
            row=1,
        )
        self.guild_id = guild_id
        self.user_id = user_id
        self.collection = collection

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        # 遅延importで、公開ファサード側のレアリティ選択UIとの循環を避ける。
        from src.cogs.cafe_gacha_collection import CollectionRaritySelectView

        await interaction.response.send_message(
            "交換するカードのレアリティを選んでください。",
            view=CollectionRaritySelectView(
                self.guild_id, self.user_id, self.collection, "redemption"
            ),
            ephemeral=True,
        )


class BulkRedemptionConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, quantities: dict[str, int]) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantities = quantities
        self.event_id = str(uuid4())

    @discord.ui.button(label="全重複をXPへ交換する", style=discord.ButtonStyle.danger)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id or interaction.guild is None:
            await interaction.response.send_message(
                "本人だけが確定できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.edit_message(content="交換しています…", view=None)
        self.stop()
        async with async_session() as session:
            result = await service.redeem_cards(
                session,
                event_id=self.event_id,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                display_name=interaction.user.display_name,
                quantities=self.quantities,
            )
        if result.status != "redeemed" or result.redemption is None:
            await interaction.followup.send(
                "所持数が変わったため交換できませんでした。コレクションを開き直してください。",
                ephemeral=True,
            )
            return
        await _request_level_sync(str(self.guild_id))
        await _publish_redemption(interaction.guild, result.redemption)
        await interaction.followup.send(
            f"{result.redemption.reward_xp:,} XP を受け取りました。",
            ephemeral=True,
        )

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content="交換をキャンセルしました。", view=None
        )
        self.stop()


class BulkExchangeButton(discord.ui.Button[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
    ) -> None:
        super().__init__(
            label="全重複をXP交換",
            style=discord.ButtonStyle.success,
            emoji="♻️",
            row=1,
        )
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantities = {
            item.card.key: item.exchangeable_count
            for item in collection
            if item.exchangeable_count > 0
        }

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        total_xp = sum(
            CARDS_BY_KEY[key].exchange_xp * quantity
            for key, quantity in self.quantities.items()
        )
        details = []
        for rarity in RARITY_ORDER:
            keys = tuple(
                key for key in self.quantities if CARDS_BY_KEY[key].rarity == rarity
            )
            if not keys:
                continue
            quantity = sum(self.quantities[key] for key in keys)
            reward_xp = sum(
                CARDS_BY_KEY[key].exchange_xp * self.quantities[key] for key in keys
            )
            details.append(
                f"{rarity_label(rarity)}: {len(keys)}種・{quantity}枚 "
                f"→ {reward_xp:,} XP"
            )
        await interaction.response.send_message(
            (
                "交換可能な重複カードをすべてXPへ交換します。\n"
                + "\n".join(details)
                + "\n**各カードの最初の1枚と保護カードは残ります。**"
                + f"\n\n受取合計: **{total_xp:,} XP**"
            ),
            view=BulkRedemptionConfirmView(
                self.guild_id, self.user_id, self.quantities
            ),
            ephemeral=True,
        )


class MedalRedemptionConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, quantities: dict[str, int]) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantities = quantities
        self.event_id = str(uuid4())

    @discord.ui.button(label="メダルへ交換する", style=discord.ButtonStyle.danger)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが確定できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.edit_message(content="交換しています…", view=None)
        self.stop()
        async with async_session() as session:
            result = await service.redeem_cards_for_medals(
                session,
                event_id=self.event_id,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                quantities=self.quantities,
            )
            balance = await service.cafe_medal_balance(
                session, guild_id=str(self.guild_id), user_id=str(self.user_id)
            )
        if result.status != "redeemed" or result.redemption is None:
            await interaction.followup.send(
                "所持数が変わったため交換できませんでした。", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"☕ **{result.redemption.reward_medals:,}メダル**を受け取りました。"
            f"\n現在: **{balance:,}メダル**",
            ephemeral=True,
        )


class MedalExchangeButton(discord.ui.Button[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
    ) -> None:
        super().__init__(label="全重複をメダル交換", emoji="☕", row=2)
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantities = {
            item.card.key: item.exchangeable_count
            for item in collection
            if item.exchangeable_count > 0
        }

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        total = sum(
            MEDALS_BY_RARITY[CARDS_BY_KEY[key].rarity] * quantity
            for key, quantity in self.quantities.items()
        )
        await interaction.response.send_message(
            f"全カードの重複を **{total:,}カフェメダル**へ交換します。\n"
            "XPには交換されません。最初の1枚と保護カードは残ります。",
            view=MedalRedemptionConfirmView(
                self.guild_id, self.user_id, self.quantities
            ),
            ephemeral=True,
        )
