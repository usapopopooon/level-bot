"""カフェ・コレクションのカード棚UIと互換用の公開ファサード。"""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Literal

import discord

from src.cogs import cafe_gacha_collection_customization as _customization
from src.cogs import cafe_gacha_collection_exchange as _exchange
from src.cogs import cafe_gacha_collection_sets as _sets
from src.cogs.cafe_gacha_common import ASSET_DIR, _parse_rarity
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
from src.features.feature_access import service as feature_access_service

logger = logging.getLogger(__name__)

DISCORD_EMBED_LIMIT = 10

# 既存のimport経路を維持する公開ファサード。
CafeMedalShopButton = _customization.CafeMedalShopButton
CosmeticConfirmView = _customization.CosmeticConfirmView
CosmeticSelect = _customization.CosmeticSelect
FavoriteSelect = _customization.FavoriteSelect
FavoriteSelectView = _customization.FavoriteSelectView
ProtectionButton = _customization.ProtectionButton
ProtectionSelect = _customization.ProtectionSelect
ProtectionSelectView = _customization.ProtectionSelectView

BulkExchangeButton = _exchange.BulkExchangeButton
BulkRedemptionConfirmView = _exchange.BulkRedemptionConfirmView
CustomQuantityModal = _exchange.CustomQuantityModal
IndividualExchangeButton = _exchange.IndividualExchangeButton
MedalExchangeButton = _exchange.MedalExchangeButton
MedalRedemptionConfirmView = _exchange.MedalRedemptionConfirmView
RedemptionConfirmView = _exchange.RedemptionConfirmView
RedemptionQuantityView = _exchange.RedemptionQuantityView
RedemptionSelect = _exchange.RedemptionSelect
RedemptionSelectView = _exchange.RedemptionSelectView
_send_redemption_confirmation = _exchange._send_redemption_confirmation

SET_MENU_PAGE_SIZE = _sets.SET_MENU_PAGE_SIZE
CafeSetMenuButton = _sets.CafeSetMenuButton
CafeSetMenuView = _sets.CafeSetMenuView
_set_menu_embed = _sets._set_menu_embed

type CollectionChoice = Literal["favorite", "redemption", "protection"]


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
        options: list[discord.SelectOption] = []
        for rarity in RARITY_ORDER:
            count = sum(
                1
                for item in collection
                if item.card.rarity == rarity
                and (
                    item.count > 0
                    if choice in {"favorite", "protection"}
                    else item.exchangeable_count > 0
                )
            )
            if count:
                page_count = (count + 24) // 25
                options.extend(
                    discord.SelectOption(
                        label=(
                            f"{rarity_label(rarity)}（{count}種）"
                            if page_count == 1
                            else (
                                f"{rarity_label(rarity)}"
                                f"（{count}種・{page + 1}/{page_count}）"
                            )
                        ),
                        value=f"{rarity}:{page}",
                    )
                    for page in range(page_count)
                )
        action = {
            "favorite": "お気に入り",
            "redemption": "交換",
            "protection": "保護設定",
        }[choice]
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
        rarity_value, _, page_value = self.values[0].partition(":")
        rarity = _parse_rarity(rarity_value)
        if rarity is None:
            await interaction.response.send_message(
                "レアリティを選び直してください。", ephemeral=True
            )
            return
        page = int(page_value or "0")
        if self.choice == "favorite":
            view: discord.ui.View = FavoriteSelectView(
                self.guild_id, self.user_id, self.collection, rarity, page
            )
            message = "お気に入りにするカードを選んでください。"
        elif self.choice == "redemption":
            view = RedemptionSelectView(
                self.guild_id, self.user_id, self.collection, rarity, page
            )
            message = "交換するカードを1種類選んでください。"
        else:
            view = ProtectionSelectView(
                self.guild_id, self.user_id, self.collection, rarity, page
            )
            message = "保護または保護解除するカードを選んでください。"
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
        if any(item.exchangeable_count > 0 for item in collection):
            self.add_item(IndividualExchangeButton(guild_id, user_id, collection))
            self.add_item(BulkExchangeButton(guild_id, user_id, collection))
            self.add_item(MedalExchangeButton(guild_id, user_id, collection))
        self.add_item(CafeMedalShopButton(guild_id, user_id))
        if any(item.count > 0 for item in collection):
            self.add_item(ProtectionButton(guild_id, user_id, collection))
        self.add_item(CafeSetMenuButton(guild_id, user_id, collection))


def _exchange_guidance(collection: tuple[service.CollectionCard, ...]) -> str:
    redeemable_total = sum(item.exchangeable_count for item in collection)
    protected_total = sum(
        item.redeemable_count for item in collection if item.is_protected
    )
    protected_text = (
        f" 保護中の重複 **{protected_total}枚** は交換対象外です。"
        if protected_total
        else ""
    )
    if redeemable_total == 0:
        return (
            "交換できる重複カードはまだありません。"
            "同じカードの2枚目以降がXP・メダル交換の対象になります。" + protected_text
        )
    return (
        f"交換可能なカードが合計 **{redeemable_total}枚** あります。"
        "XPへの個別・全重複交換、またはカフェメダルへの全重複交換を選べます。"
        "どの交換でも各カードの最初の1枚は必ず残ります。" + protected_text
    )


def _n_collection_milestone(n_owned: int) -> tuple[str, str]:
    n_total = len(tuple(card for card in CARDS_BY_KEY.values() if card.rarity == "C"))
    if n_owned >= n_total:
        return "🏆 N棚の主", f"Nカード全{n_total}種を収集しました。"
    if n_owned >= 10:
        return "🧺 N棚コレクター", f"次の称号まであと {n_total - n_owned}種"
    if n_owned >= 5:
        return "☕ N棚見習い", f"次の称号まであと {10 - n_owned}種"
    return "N棚の入口", f"最初の称号まであと {5 - n_owned}種"


def _collection_rarity_description(
    collection: tuple[service.CollectionCard, ...], rarity: Rarity
) -> str:
    lines = [
        (
            f"**{item.card.name}** ×{item.count}"
            + (
                f"（🔒重複 {item.redeemable_count}枚を保護）"
                if item.is_protected and item.redeemable_count
                else (
                    "（🔒保護中）"
                    if item.is_protected
                    else (
                        f"（交換可 {item.exchangeable_count}）"
                        if item.exchangeable_count
                        else ""
                    )
                )
            )
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


def _collection_footer(owned: int, total: int) -> str:
    return (
        f"収集 {owned}/{total}種 · "
        "最初の1枚と保護カードは残ります（交換対象は未保護の2枚目以降）"
    )


def _apply_collection_footer(
    embeds: list[discord.Embed], *, owned: int, total: int
) -> None:
    footer = _collection_footer(owned, total)
    for embed in embeds:
        embed.set_footer(text=footer)


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
    n_total = sum(item.card.rarity == "C" for item in collection)
    milestone, milestone_detail = _n_collection_milestone(n_owned)
    embed.add_field(
        name=milestone,
        value=f"N収集 {n_owned}/{n_total}種 · {milestone_detail}",
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
    files: list[discord.File] = []
    embeds = [embed]
    try:
        shelves = await asyncio.to_thread(
            render_collection_shelves,
            ASSET_DIR,
            {item.card.key: item.count for item in collection},
        )
        embeds = []
        for index, shelf in enumerate(shelves):
            rarity_owned = sum(
                item.count > 0
                for item in collection
                if item.card.rarity == shelf.rarity
            )
            rarity_total = sum(item.card.rarity == shelf.rarity for item in collection)
            filename = f"collection-{shelf.rarity.lower()}-{shelf.page}.jpg"
            files.append(discord.File(BytesIO(shelf.image), filename=filename))
            page_embed = (
                embed
                if index == 0
                else discord.Embed(
                    title=(
                        f"{rarity_label(shelf.rarity)} カード棚"
                        + (
                            f" {shelf.page}/{shelf.page_count}"
                            if shelf.page_count > 1
                            else ""
                        )
                    ),
                    description=f"所持 {rarity_owned}/{rarity_total}種",
                    color=DEFAULT_EMBED_COLOR,
                )
            )
            page_embed.set_image(url=f"attachment://{filename}")
            embeds.append(page_embed)
    except OSError:
        logger.exception("Failed to render cafe collection shelf")
    _apply_collection_footer(embeds, owned=owned, total=len(collection))
    view = CollectionView(guild_id, interaction.user.id, collection)
    for start in range(0, len(embeds), DISCORD_EMBED_LIMIT):
        chunk_embeds = embeds[start : start + DISCORD_EMBED_LIMIT]
        chunk_files = files[start : start + DISCORD_EMBED_LIMIT]
        if start + DISCORD_EMBED_LIMIT >= len(embeds):
            await interaction.followup.send(
                embeds=chunk_embeds,
                files=chunk_files,
                view=view,
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embeds=chunk_embeds,
                files=chunk_files,
                ephemeral=True,
            )
