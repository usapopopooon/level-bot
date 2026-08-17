"""カフェ・コレクションのカード棚と重複交換UI。"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Literal
from uuid import uuid4

import discord

from src.cogs.cafe_gacha_common import ASSET_DIR, _parse_rarity, _request_level_sync
from src.cogs.cafe_gacha_notifications import _publish_redemption
from src.cogs.feature_access import ensure_feature_access
from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import (
    CARDS_BY_KEY,
    ENDGAME_PITY_DUPLICATE_DRAWS,
    ENDGAME_PITY_MIN_COLLECTED,
    RARITY_ORDER,
    Rarity,
    rarity_label,
)
from src.features.cafe_gacha.collection_image import render_collection_shelves
from src.features.cafe_gacha.mastery import MASTERY_TIERS, mastery_tier
from src.features.cafe_gacha.medals import COSMETICS, MEDALS_BY_RARITY
from src.features.feature_access import service as feature_access_service

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        self.maximum_by_key = {
            item.card.key: item.redeemable_count
            for item in collection
            if item.redeemable_count > 0 and item.card.rarity == rarity
        }
        options = [
            discord.SelectOption(
                label=f"{rarity_label(item.card.rarity)}｜{item.card.name}",
                description=(
                    f"重複 {item.redeemable_count}枚 · 1枚 {item.card.exchange_xp} XP"
                ),
                value=item.card.key,
            )
            for item in collection
            if item.redeemable_count > 0 and item.card.rarity == rarity
        ]
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
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(RedemptionSelect(guild_id, user_id, collection, rarity))


type CollectionChoice = Literal["favorite", "redemption"]


class CollectionRaritySelect(discord.ui.Select[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
        choice: CollectionChoice,
    ) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        self.collection = collection
        self.choice = choice
        options = []
        for rarity in RARITY_ORDER:
            count = sum(
                1
                for item in collection
                if item.card.rarity == rarity
                and (
                    item.count > 0
                    if choice == "favorite"
                    else item.redeemable_count > 0
                )
            )
            if count:
                options.append(
                    discord.SelectOption(
                        label=f"{rarity_label(rarity)}（{count}種）",
                        value=rarity,
                    )
                )
        action = "お気に入り" if choice == "favorite" else "交換"
        super().__init__(
            placeholder=f"{action}するカードのレアリティを選ぶ",
            options=options,
        )

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
        rarity = _parse_rarity(self.values[0])
        if rarity is None:
            await interaction.response.send_message(
                "レアリティを選び直してください。", ephemeral=True
            )
            return
        if self.choice == "favorite":
            view: discord.ui.View = FavoriteSelectView(
                self.guild_id, self.user_id, self.collection, rarity
            )
            message = "お気に入りにするカードを選んでください。"
        else:
            view = RedemptionSelectView(
                self.guild_id, self.user_id, self.collection, rarity
            )
            message = "交換するカードを1種類選んでください。"
        await interaction.response.send_message(
            message,
            view=view,
            ephemeral=True,
        )


class CollectionRaritySelectView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
        choice: CollectionChoice,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(CollectionRaritySelect(guild_id, user_id, collection, choice))


class IndividualExchangeButton(discord.ui.Button[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
    ) -> None:
        super().__init__(
            label="カードを選んで個別交換",
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
        await interaction.response.send_message(
            "交換するカードのレアリティを選んでください。",
            view=CollectionRaritySelectView(
                self.guild_id, self.user_id, self.collection, "redemption"
            ),
            ephemeral=True,
        )


class FavoriteSelect(discord.ui.Select[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
        rarity: Rarity,
    ) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        super().__init__(
            placeholder="お気に入りの一枚を選ぶ",
            options=[
                discord.SelectOption(
                    label=f"{rarity_label(item.card.rarity)}｜{item.card.name}",
                    value=item.card.key,
                )
                for item in collection
                if item.count > 0 and item.card.rarity == rarity
            ],
        )

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
        async with async_session() as session:
            card = await service.set_favorite_card(
                session,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                reward_key=self.values[0],
            )
        if card is None:
            await interaction.response.send_message(
                "そのカードは現在所持していません。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"お気に入りの一枚を **{card.name}** にしました。", ephemeral=True
        )


class FavoriteSelectView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
        rarity: Rarity,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(FavoriteSelect(guild_id, user_id, collection, rarity))


class BulkRedemptionConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, quantities: dict[str, int]) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantities = quantities
        self.event_id = str(uuid4())

    @discord.ui.button(label="全カードを交換する", style=discord.ButtonStyle.danger)
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
            label="全カードを一括交換",
            style=discord.ButtonStyle.danger,
            emoji="♻️",
            row=1,
        )
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantities = {
            item.card.key: item.redeemable_count
            for item in collection
            if item.redeemable_count > 0
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
                "全カードの重複を一括交換します。\n"
                + "\n".join(details)
                + "\n各カードの最初の1枚は残ります。"
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
            item.card.key: item.redeemable_count
            for item in collection
            if item.redeemable_count > 0
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
            "XPには交換されません。最初の1枚は残ります。",
            view=MedalRedemptionConfirmView(
                self.guild_id, self.user_id, self.quantities
            ),
            ephemeral=True,
        )


class CosmeticConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, cosmetic_key: str) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.cosmetic_key = cosmetic_key

    @discord.ui.button(label="購入・装備する", style=discord.ButtonStyle.primary)
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
        await interaction.response.edit_message(
            content="棚テーマを確認しています…", view=None
        )
        self.stop()
        async with async_session() as session:
            result = await service.unlock_or_equip_cosmetic(
                session,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                cosmetic_key=self.cosmetic_key,
            )
        if result.status == "insufficient":
            await interaction.followup.send(
                f"メダルが足りません。現在 **{result.balance:,}メダル**です。",
                ephemeral=True,
            )
            return
        if result.cosmetic is None:
            await interaction.followup.send(
                "棚テーマが見つかりません。", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"{result.cosmetic.decoration} **{result.cosmetic.name}**を装備しました。"
            f"\n残り **{result.balance:,}メダル**",
            ephemeral=True,
        )


class CosmeticSelect(discord.ui.Select[discord.ui.View]):
    def __init__(self, guild_id: int, user_id: int) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        super().__init__(
            placeholder="購入・装備する棚テーマを選ぶ",
            options=[
                discord.SelectOption(
                    label=item.name,
                    value=item.key,
                    description=f"{item.cost_medals:,}カフェメダル",
                    emoji=item.decoration,
                )
                for item in COSMETICS
            ],
        )

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
        cosmetic = next(item for item in COSMETICS if item.key == self.values[0])
        await interaction.response.send_message(
            f"**{cosmetic.name}**（{cosmetic.cost_medals:,}メダル）を購入・装備します。"
            "\n購入済みの場合は再徴収されません。",
            view=CosmeticConfirmView(self.guild_id, self.user_id, cosmetic.key),
            ephemeral=True,
        )


class CafeMedalShopButton(discord.ui.Button[discord.ui.View]):
    def __init__(self, guild_id: int, user_id: int) -> None:
        super().__init__(label="メダル・棚テーマ", emoji="🪙", row=2)
        self.guild_id = guild_id
        self.user_id = user_id

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
        async with async_session() as session:
            balance = await service.cafe_medal_balance(
                session, guild_id=str(self.guild_id), user_id=str(self.user_id)
            )
        await interaction.response.send_message(
            f"現在 **{balance:,}カフェメダル**です。棚テーマを選んでください。",
            view=discord.ui.View(timeout=120).add_item(
                CosmeticSelect(self.guild_id, self.user_id)
            ),
            ephemeral=True,
        )


class CollectionView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
    ) -> None:
        super().__init__(timeout=180)
        if any(item.count > 0 for item in collection):
            self.add_item(
                CollectionRaritySelect(guild_id, user_id, collection, "favorite")
            )
        if any(item.redeemable_count > 0 for item in collection):
            self.add_item(IndividualExchangeButton(guild_id, user_id, collection))
            self.add_item(BulkExchangeButton(guild_id, user_id, collection))
            self.add_item(MedalExchangeButton(guild_id, user_id, collection))
        self.add_item(CafeMedalShopButton(guild_id, user_id))


def _exchange_guidance(collection: tuple[service.CollectionCard, ...]) -> str:
    redeemable_total = sum(item.redeemable_count for item in collection)
    if redeemable_total == 0:
        return (
            "交換できる重複カードはまだありません。"
            "同じカードの2枚目以降がXP・メダル交換の対象になります。"
        )
    return (
        f"交換可能なカードが合計 **{redeemable_total}枚** あります。"
        "XPへの個別・一括交換、またはカフェメダルへの一括交換を選べます。"
    )


def _n_collection_milestone(n_owned: int) -> tuple[str, str]:
    if n_owned >= 25:
        return "🏆 N棚の主", "Nカード全25種を収集しました。"
    if n_owned >= 10:
        return "🧺 N棚コレクター", f"次の称号まであと {25 - n_owned}種"
    if n_owned >= 5:
        return "☕ N棚見習い", f"次の称号まであと {10 - n_owned}種"
    return "N棚の入口", f"最初の称号まであと {5 - n_owned}種"


def _collection_rarity_description(
    collection: tuple[service.CollectionCard, ...], rarity: Rarity
) -> str:
    lines = [
        (
            f"**{item.card.name}** ×{item.count}"
            + (f"（交換可 {item.redeemable_count}）" if item.redeemable_count else "")
            + (
                f" · {tier.emoji}{tier.name}（累計{item.lifetime_count}枚）"
                if (tier := mastery_tier(item.lifetime_count)) is not None
                else ""
            )
        )
        for item in collection
        if item.card.rarity == rarity and item.count > 0
    ]
    return "\n".join(lines) if lines else "このレアリティはまだ未収集です。"


async def _show_collection(interaction: discord.Interaction, guild_id: int) -> None:
    async with async_session() as session:
        collection = await service.list_collection(
            session, guild_id=str(guild_id), user_id=str(interaction.user.id)
        )
        favorite = await service.favorite_card(
            session, guild_id=str(guild_id), user_id=str(interaction.user.id)
        )
        duplicate_streak = await service.duplicate_draw_streak(
            session, guild_id=str(guild_id), user_id=str(interaction.user.id)
        )
        medal_balance = await service.cafe_medal_balance(
            session, guild_id=str(guild_id), user_id=str(interaction.user.id)
        )
        cosmetic = await service.active_cosmetic(
            session, guild_id=str(guild_id), user_id=str(interaction.user.id)
        )
    owned = sum(item.count > 0 for item in collection)
    rarity_progress_parts = []
    for rarity in RARITY_ORDER:
        rarity_owned = sum(
            item.count > 0 for item in collection if item.card.rarity == rarity
        )
        rarity_total = sum(item.card.rarity == rarity for item in collection)
        rarity_progress_parts.append(
            f"{rarity_label(rarity)} {rarity_owned}/{rarity_total}"
        )
    rarity_progress = " / ".join(rarity_progress_parts)
    n_description = _collection_rarity_description(collection, "C")
    embed = discord.Embed(
        title=(
            f"{cosmetic.decoration if cosmetic else '🗃️'} "
            f"{interaction.user.display_name} のカード棚"
        ),
        description=(
            f"**レアリティ別収集**\n{rarity_progress}\n\n"
            f"**N 所持カード**\n{n_description}"
            if owned
            else "まだカードはありません。"
        ),
        color=cosmetic.color if cosmetic else DEFAULT_EMBED_COLOR,
    )
    embed.add_field(
        name="🪙 カフェメダル",
        value=f"{medal_balance:,}枚 · 重複カードから交換できます",
        inline=False,
    )
    if favorite is not None:
        embed.add_field(
            name="お気に入りの一枚",
            value=f"{rarity_label(favorite.rarity)}｜{favorite.name}",
        )
    mastery_counts = {
        tier.name: sum(mastery_tier(item.lifetime_count) == tier for item in collection)
        for tier in MASTERY_TIERS
    }
    embed.add_field(
        name="☕ カード熟練度",
        value=" / ".join(
            f"{tier.emoji}{tier.name} {mastery_counts[tier.name]}種"
            for tier in MASTERY_TIERS
        ),
        inline=False,
    )
    n_owned = sum(item.count > 0 for item in collection if item.card.rarity == "C")
    milestone, milestone_detail = _n_collection_milestone(n_owned)
    embed.add_field(
        name=milestone,
        value=f"N収集 {n_owned}/25種 · {milestone_detail}",
        inline=False,
    )
    if ENDGAME_PITY_MIN_COLLECTED <= owned < len(collection):
        embed.add_field(
            name="終盤のNEW保証",
            value=(
                f"NEWなし {duplicate_streak}/{ENDGAME_PITY_DUPLICATE_DRAWS}回\n"
                "上限まで続いた場合、次の抽選は未所持カードになります。"
            ),
            inline=False,
        )
    embed.add_field(name="XP交換", value=_exchange_guidance(collection), inline=False)
    embed.set_footer(
        text=f"収集 {owned}/{len(collection)}種 · 最初の1枚は交換されません"
    )
    files: list[discord.File] = []
    embeds = [embed]
    try:
        shelves = render_collection_shelves(
            ASSET_DIR, {item.card.key: item.count for item in collection}
        )
        embeds = []
        for index, shelf in enumerate(shelves):
            filename = f"collection-{shelf.rarity.lower()}.jpg"
            files.append(discord.File(BytesIO(shelf.image), filename=filename))
            page_embed = (
                embed
                if index == 0
                else discord.Embed(
                    title=f"{rarity_label(shelf.rarity)} カード棚",
                    description=_collection_rarity_description(
                        collection, shelf.rarity
                    ),
                    color=DEFAULT_EMBED_COLOR,
                )
            )
            page_embed.set_image(url=f"attachment://{filename}")
            embeds.append(page_embed)
    except OSError:
        logger.exception("Failed to render cafe collection shelf")
    await interaction.followup.send(
        embeds=embeds,
        files=files,
        view=CollectionView(guild_id, interaction.user.id, collection),
        ephemeral=True,
    )
