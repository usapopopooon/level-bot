"""カフェ・コレクションの管理コマンドとセットアップ入口。

Discord UI、公開通知、カード棚の実装は責務別モジュールへ分離し、このモジュールは
従来の拡張ロードパスとテスト向けインポートを維持する。
"""

from __future__ import annotations

import contextlib
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.cogs.cafe_gacha_collection import (
    BulkExchangeButton,
    BulkRedemptionConfirmView,
    CollectionChoice,
    CollectionRaritySelect,
    CollectionRaritySelectView,
    CollectionView,
    CustomQuantityModal,
    FavoriteSelect,
    FavoriteSelectView,
    IndividualExchangeButton,
    RedemptionConfirmView,
    RedemptionQuantityView,
    RedemptionSelect,
    RedemptionSelectView,
    _collection_rarity_description,
    _exchange_guidance,
    _n_collection_milestone,
    _send_redemption_confirmation,
    _show_collection,
)
from src.cogs.cafe_gacha_common import (
    ASSET_DIR,
    COUNTER_NAME,
    LEDGER_NAME,
    MAX_DRAW_REWARD_XP,
    MIN_DRAW_REWARD_XP,
    NOTIFICATION_RETRY_MINUTES,
    PANEL_TITLE,
    PUBLIC_MENTION_RARITY_RANK,
    RARITY_XP_TEXT,
    _earned_xp,
    _next_hour_label,
    _parse_rarity,
    _request_level_sync,
    build_panel_embed,
)
from src.cogs.cafe_gacha_draw import (
    CafeGachaPanelView,
    DrawConfirmView,
    DynamicCafeBalanceButton,
    DynamicCafeCatalogButton,
    DynamicCafeCollectionButton,
    DynamicCafeDrawButton,
    DynamicCafeTenDrawButton,
    _affordable_batch_count,
    _draw_confirmation_text,
    _perform_draw,
    _perform_ten_draw,
    _prepare_draw,
)
from src.cogs.cafe_gacha_notifications import (
    _batch_summary_content,
    _configured_channels,
    _draw_marker,
    _draw_mention_content,
    _find_notification,
    _find_panel_message,
    _highest_rarity,
    _lock_notification,
    _notification_nonce,
    _publish_draw,
    _publish_draw_mention,
    _publish_draws,
    _publish_redemption,
    _redemption_detail,
    _redemption_embed,
    _result_embed,
    _retry_pending_notifications,
    _safe_card_name,
)
from src.cogs.feature_access import format_access_roles
from src.database.engine import async_session
from src.features.cafe_gacha import service
from src.features.feature_access import service as feature_access_service

logger = logging.getLogger(__name__)

__all__ = [
    "ASSET_DIR",
    "COUNTER_NAME",
    "LEDGER_NAME",
    "MAX_DRAW_REWARD_XP",
    "MIN_DRAW_REWARD_XP",
    "NOTIFICATION_RETRY_MINUTES",
    "PANEL_TITLE",
    "PUBLIC_MENTION_RARITY_RANK",
    "RARITY_XP_TEXT",
    "BulkExchangeButton",
    "BulkRedemptionConfirmView",
    "CafeGachaCog",
    "CafeGachaPanelView",
    "CollectionChoice",
    "CollectionRaritySelect",
    "CollectionRaritySelectView",
    "CollectionView",
    "CustomQuantityModal",
    "DrawConfirmView",
    "DynamicCafeBalanceButton",
    "DynamicCafeCatalogButton",
    "DynamicCafeCollectionButton",
    "DynamicCafeDrawButton",
    "DynamicCafeTenDrawButton",
    "FavoriteSelect",
    "FavoriteSelectView",
    "IndividualExchangeButton",
    "RedemptionConfirmView",
    "RedemptionQuantityView",
    "RedemptionSelect",
    "RedemptionSelectView",
    "_affordable_batch_count",
    "_batch_summary_content",
    "_collection_rarity_description",
    "_configured_channels",
    "_draw_confirmation_text",
    "_draw_marker",
    "_draw_mention_content",
    "_earned_xp",
    "_ensure_setup",
    "_exchange_guidance",
    "_find_notification",
    "_find_or_create_channel",
    "_find_panel_message",
    "_highest_rarity",
    "_lock_notification",
    "_n_collection_milestone",
    "_next_hour_label",
    "_notification_nonce",
    "_parse_rarity",
    "_perform_draw",
    "_perform_ten_draw",
    "_prepare_draw",
    "_publish_draw",
    "_publish_draw_mention",
    "_publish_draws",
    "_publish_redemption",
    "_redemption_detail",
    "_redemption_embed",
    "_repair_configured_setup",
    "_request_level_sync",
    "_result_embed",
    "_retry_pending_notifications",
    "_safe_card_name",
    "_send_redemption_confirmation",
    "_show_collection",
    "_upsert_panel",
    "build_panel_embed",
    "register_cafe_gacha_dynamic_items",
    "setup",
]


async def _find_or_create_channel(
    guild: discord.Guild, name: str, configured_id: str | None = None
) -> discord.TextChannel:
    configured = (
        guild.get_channel(int(configured_id)) if configured_id is not None else None
    )
    existing = (
        configured
        if isinstance(configured, discord.TextChannel)
        else discord.utils.get(guild.text_channels, name=name)
    )
    me = guild.me
    overwrites: dict[
        discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite
    ] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False
        )
    }
    if me is not None:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
        )
    channel = (
        existing
        if existing is not None
        else await guild.create_text_channel(name, overwrites=overwrites)
    )
    default_permissions = channel.overwrites_for(guild.default_role)
    default_permissions.update(
        view_channel=True, read_message_history=True, send_messages=False
    )
    await channel.set_permissions(guild.default_role, overwrite=default_permissions)
    if me is not None:
        bot_permissions = channel.overwrites_for(me)
        bot_permissions.update(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
        )
        await channel.set_permissions(me, overwrite=bot_permissions)
    return channel


async def _upsert_panel(
    guild: discord.Guild,
    counter: discord.TextChannel,
    panel_message_id: str | None,
) -> discord.Message:
    message: discord.Message | None = None
    if panel_message_id is not None:
        with contextlib.suppress(discord.NotFound):
            message = await counter.fetch_message(int(panel_message_id))
    if message is None:
        message = await _find_panel_message(counter)
    image_path = ASSET_DIR / "panel-cabinet.jpg"
    files = (
        [discord.File(image_path, filename="panel-cabinet.jpg")]
        if image_path.is_file()
        else []
    )
    if message is None:
        return await counter.send(
            embed=build_panel_embed(with_image=bool(files)),
            files=files,
            view=CafeGachaPanelView(guild.id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    await message.edit(
        content=None,
        embed=build_panel_embed(with_image=bool(files)),
        attachments=files,
        suppress=False,
        view=CafeGachaPanelView(guild.id),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return message


async def _ensure_setup(
    guild: discord.Guild, *, require_existing: bool
) -> tuple[discord.TextChannel, discord.TextChannel] | None:
    async with async_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:setup_key))"),
            {"setup_key": f"cafe-setup:{guild.id}"},
        )
        config = await service.get_guild_config(session, str(guild.id))
        if config is None and require_existing:
            await session.rollback()
            return None
        counter = await _find_or_create_channel(
            guild,
            COUNTER_NAME,
            config.counter_channel_id if config is not None else None,
        )
        ledger = await _find_or_create_channel(
            guild,
            LEDGER_NAME,
            config.ledger_channel_id if config is not None else None,
        )
        panel = await _upsert_panel(
            guild,
            counter,
            config.panel_message_id if config is not None else None,
        )
        await service.save_guild_config(
            session,
            guild_id=str(guild.id),
            counter_channel_id=str(counter.id),
            ledger_channel_id=str(ledger.id),
            panel_message_id=str(panel.id),
        )
        return counter, ledger


async def _repair_configured_setup(guild: discord.Guild) -> None:
    await _ensure_setup(guild, require_existing=True)


class CafeGachaCog(commands.Cog):
    cafe_group = app_commands.Group(
        name="cafe-gacha",
        description="カフェガチャの管理",
        default_permissions=discord.Permissions(administrator=True),
    )
    cafe_access_group = app_commands.Group(
        name="access-role",
        description="カフェ・コレクションの利用ロール管理",
        parent=cafe_group,
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._retry_started = False

    async def cog_load(self) -> None:
        self._notification_retry_loop.start()

    async def cog_unload(self) -> None:
        self._notification_retry_loop.cancel()

    @tasks.loop(minutes=NOTIFICATION_RETRY_MINUTES)
    async def _notification_retry_loop(self) -> None:
        for guild in self.bot.guilds:
            try:
                await _retry_pending_notifications(guild)
            except SQLAlchemyError:
                logger.exception(
                    "Failed to retry cafe gacha notifications for guild %s",
                    guild.id,
                )

    @_notification_retry_loop.before_loop
    async def _before_notification_retry_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._retry_started:
            return
        self._retry_started = True
        for guild in self.bot.guilds:
            try:
                await _repair_configured_setup(guild)
            except (discord.HTTPException, OSError, SQLAlchemyError):
                logger.exception(
                    "Failed to repair cafe gacha setup for guild %s", guild.id
                )
            try:
                await _retry_pending_notifications(guild)
            except SQLAlchemyError:
                logger.exception(
                    "Failed to retry cafe gacha notifications for guild %s", guild.id
                )

    @cafe_group.command(
        name="setup", description="カウンター・台帳・常設パネルを作成または修復"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def setup_gacha(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        channels = await _ensure_setup(guild, require_existing=False)
        if channels is None:
            await interaction.followup.send(
                "セットアップできませんでした。", ephemeral=True
            )
            return
        counter, ledger = channels
        await _retry_pending_notifications(guild)
        await interaction.followup.send(
            f"セットアップしました: {counter.mention} / {ledger.mention}",
            ephemeral=True,
        )

    @cafe_access_group.command(name="add", description="利用できるロールを追加")
    @app_commands.describe(role="カフェ・コレクションの利用を許可するロール")
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
        async with async_session() as session:
            added = await feature_access_service.add_access_role(
                session,
                guild_id=str(interaction.guild.id),
                feature=feature_access_service.CAFE_GACHA,
                role_id=str(role.id),
            )
        message = (
            f"カフェ・コレクションの利用ロールに {role.mention} を追加しました。"
            if added
            else f"{role.mention} はすでに利用ロールへ追加されています。"
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @cafe_access_group.command(name="remove", description="利用ロールを削除")
    @app_commands.describe(role="カフェ・コレクションの利用許可から外すロール")
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
        async with async_session() as session:
            removed = await feature_access_service.remove_access_role(
                session,
                guild_id=str(interaction.guild.id),
                feature=feature_access_service.CAFE_GACHA,
                role_id=str(role.id),
            )
        message = (
            f"カフェ・コレクションの利用ロールから {role.mention} を削除しました。"
            if removed
            else f"{role.mention} は利用ロールに設定されていません。"
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @cafe_access_group.command(name="list", description="利用ロールを表示")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_access_roles(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        async with async_session() as session:
            role_ids = await feature_access_service.list_access_role_ids(
                session,
                guild_id=str(interaction.guild.id),
                feature=feature_access_service.CAFE_GACHA,
            )
        message = (
            "カフェ・コレクションの利用ロール: " + format_access_roles(role_ids)
            if role_ids
            else "利用ロールは未設定です。現在は全員が利用できます。"
        )
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


def register_cafe_gacha_dynamic_items(bot: commands.Bot) -> None:
    bot.add_dynamic_items(
        DynamicCafeDrawButton,
        DynamicCafeTenDrawButton,
        DynamicCafeCollectionButton,
        DynamicCafeCatalogButton,
        DynamicCafeBalanceButton,
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CafeGachaCog(bot))
