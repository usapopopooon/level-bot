"""所持カードを名前検索して保護・解除するユーザーコマンド。"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import SQLAlchemyError

from src.cogs.cafe_gacha_collection_customization import (
    build_protection_choices,
    resolve_owned_card,
)
from src.cogs.feature_access import ensure_feature_access
from src.database.engine import async_session
from src.features.cafe_gacha import service
from src.features.feature_access import service as feature_access_service

logger = logging.getLogger(__name__)


class CafeGachaProtectionCog(commands.Cog):
    cafe_collection_group = app_commands.Group(
        name="cafe-collection",
        description="カフェ・コレクションのカード棚を管理",
        guild_only=True,
    )

    async def protection_card_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild_id is None:
            return []
        try:
            async with async_session() as session:
                collection = await service.list_collection(
                    session,
                    guild_id=str(interaction.guild_id),
                    user_id=str(interaction.user.id),
                )
        except SQLAlchemyError:
            logger.exception(
                "Failed to autocomplete cafe card protection for guild %s user %s",
                interaction.guild_id,
                interaction.user.id,
            )
            return []
        return build_protection_choices(collection, current)

    @cafe_collection_group.command(
        name="protect",
        description="名前検索で所持カードの保護／解除を切り替える",
    )
    @app_commands.describe(card="カード名を入力すると所持カードが候補表示されます")
    @app_commands.autocomplete(card=protection_card_autocomplete)
    async def protect_card(
        self,
        interaction: discord.Interaction,
        card: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=interaction.guild.id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session() as session:
            collection = await service.list_collection(
                session,
                guild_id=str(interaction.guild.id),
                user_id=str(interaction.user.id),
            )
            selected = resolve_owned_card(collection, card)
            if selected is None:
                await interaction.followup.send(
                    "そのカードは現在所持していません。カード欄の候補から選び直してください。",
                    ephemeral=True,
                )
                return
            protected = not selected.is_protected
            updated = await service.set_card_protection(
                session,
                guild_id=str(interaction.guild.id),
                user_id=str(interaction.user.id),
                reward_key=selected.card.key,
                protected=protected,
            )
        if updated is None:
            await interaction.followup.send(
                "所持状態が変わったため設定できませんでした。もう一度お試しください。",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            (
                f"🔒 **{updated.name}** を保護しました。"
                "今後のXP・メダル交換から除外します。"
                if protected
                else f"🔓 **{updated.name}** の保護を解除しました。"
            ),
            ephemeral=True,
        )
