"""カフェ・コレクションのお気に入り・保護・棚テーマUI。"""

from __future__ import annotations

import discord

from src.cogs.feature_access import ensure_feature_access
from src.database.engine import async_session
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import Rarity, rarity_label
from src.features.cafe_gacha.medals import COSMETICS
from src.features.feature_access import service as feature_access_service


class FavoriteSelect(discord.ui.Select[discord.ui.View]):
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
        options = [
            discord.SelectOption(
                label=f"{rarity_label(item.card.rarity)}｜{item.card.name}",
                value=item.card.key,
            )
            for item in collection
            if item.count > 0 and item.card.rarity == rarity
        ]
        super().__init__(
            placeholder="お気に入りの一枚を選ぶ",
            options=options[page * 25 : (page + 1) * 25],
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
        page: int = 0,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(FavoriteSelect(guild_id, user_id, collection, rarity, page))


class ProtectionSelect(discord.ui.Select[discord.ui.View]):
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
        self.protected_by_key = {
            item.card.key: item.is_protected
            for item in collection
            if item.count > 0 and item.card.rarity == rarity
        }
        options = [
            discord.SelectOption(
                label=f"{'🔒' if item.is_protected else '🔓'} {item.card.name}",
                description=(
                    f"所持 {item.count}枚 · "
                    f"{'保護を解除' if item.is_protected else '重複を交換から保護'}"
                ),
                value=item.card.key,
            )
            for item in collection
            if item.count > 0 and item.card.rarity == rarity
        ]
        super().__init__(
            placeholder="保護設定を切り替えるカードを選ぶ",
            options=options[page * 25 : (page + 1) * 25],
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
        reward_key = self.values[0]
        protected = not self.protected_by_key[reward_key]
        async with async_session() as session:
            card = await service.set_card_protection(
                session,
                guild_id=str(self.guild_id),
                user_id=str(self.user_id),
                reward_key=reward_key,
                protected=protected,
            )
        if card is None:
            await interaction.response.send_message(
                "そのカードは現在所持していません。コレクションを開き直してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            (
                f"🔒 **{card.name}** を保護しました。"
                "今後のXP・メダル交換から除外します。"
                if protected
                else f"🔓 **{card.name}** の保護を解除しました。"
            ),
            ephemeral=True,
        )


class ProtectionSelectView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
        rarity: Rarity,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(ProtectionSelect(guild_id, user_id, collection, rarity, page))


class ProtectionButton(discord.ui.Button[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
    ) -> None:
        super().__init__(label="保護カードを設定", emoji="🔒", row=3)
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
            "カードを選ぶと保護／解除を切り替えます。保護中のカードは重複交換から除外されます。",
            view=CollectionRaritySelectView(
                self.guild_id, self.user_id, self.collection, "protection"
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
