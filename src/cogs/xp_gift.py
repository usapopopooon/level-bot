"""XPギフトの常設パネル、確認UI、公開台帳通知。"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import re
from datetime import timedelta
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.database.models import XpGiftTransfer
from src.features.guilds import service as guilds_service
from src.features.xp_gift import service

logger = logging.getLogger(__name__)

PANEL_CHANNEL_NAME = "🎁xpギフト"
LEDGER_CHANNEL_NAME = "📒xpギフト台帳"
PANEL_TITLE = "🎁 XPギフト"
NOTIFICATION_RETRY_MINUTES = 5.0


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title=PANEL_TITLE,
        description=(
            "自分のXPを、サーバーの仲間へ贈れます。\n"
            "送る相手・金額・任意のメッセージを入力し、確認してから確定してください。\n"
            "メッセージはギフトカード風に公開台帳へ表示されます。\n\n"
            "**1回 1〜3,000 XP**\n"
            "同じ相手へ贈れるのは **1日1回**（毎日 日本時間0:00更新）\n"
            "1,000 XPまでは非課税、超えた分に **贈与税10%**\n"
            "税は送る側が追加で負担し、受け取るXPは減りません。\n\n"
            "完了したギフトは台帳へ公開され、受取人だけに通知します。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    embed.set_footer(text="確定したギフトは取り消せません")
    return embed


def _notification_nonce(event_id: str) -> int:
    digest = hashlib.blake2b(f"xp-gift:{event_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


def _gift_message_code_block(message: str) -> str:
    """ユーザー本文でコードブロックを閉じられない表示文字列を返す。"""
    safe = discord.utils.escape_mentions(message).replace("```", "``\u200b`")
    return f"```text\n{safe}\n```"


def _notification_embed(row: XpGiftTransfer) -> discord.Embed:
    embed = discord.Embed(
        title="🎁 XPギフトが届きました",
        description=(
            f"**<@{row.sender_user_id}>**さん から "
            f"**<@{row.recipient_user_id}>**さんへ\n"
            f"**{row.gift_xp:,} XP** が贈られました。"
        ),
        color=0x57F287,
    )
    if row.gift_message is not None:
        embed.add_field(
            name="✉️ メッセージ",
            value=_gift_message_code_block(row.gift_message),
            inline=False,
        )
    tax_text = (
        f"{row.tax_xp:,} XP（送る側が追加負担）" if row.tax_xp else "0 XP（非課税）"
    )
    embed.add_field(name="贈与税", value=tax_text, inline=True)
    embed.add_field(
        name="送る側の合計負担",
        value=f"{row.sender_cost_xp:,} XP",
        inline=True,
    )
    embed.set_footer(text="同じ相手への次のギフトは日本時間0:00以降")
    return embed


def _recipient_allowed_mentions(row: XpGiftTransfer) -> discord.AllowedMentions:
    """公開通知では受取人だけを実際にメンション可能にする。"""
    return discord.AllowedMentions(
        everyone=False,
        users=[discord.Object(id=int(row.recipient_user_id))],
        roles=False,
        replied_user=False,
    )


async def _configured_channels(
    guild: discord.Guild,
) -> tuple[discord.TextChannel, discord.TextChannel] | None:
    async with async_session() as session:
        config = await service.get_guild_config(session, str(guild.id))
    if config is None:
        return None
    panel_channel = guild.get_channel(int(config.panel_channel_id))
    ledger_channel = guild.get_channel(int(config.ledger_channel_id))
    if not isinstance(panel_channel, discord.TextChannel) or not isinstance(
        ledger_channel, discord.TextChannel
    ):
        return None
    return panel_channel, ledger_channel


async def _lock_notification(session: AsyncSession, transfer_id: int) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:notification_key))"),
        {"notification_key": f"xp-gift-notification:{transfer_id}"},
    )


async def _find_notification(
    channel: discord.TextChannel, row: XpGiftTransfer
) -> discord.Message | None:
    nonce = str(_notification_nonce(row.event_id))
    async for message in channel.history(
        limit=None, after=row.created_at - timedelta(minutes=1)
    ):
        if message.author.bot and str(message.nonce) == nonce:
            return message
    return None


async def _publish_transfer(guild: discord.Guild, transfer_id: int) -> bool:
    try:
        channels = await _configured_channels(guild)
    except SQLAlchemyError:
        logger.exception("Failed to load XP gift channels for guild %s", guild.id)
        return False

    try:
        async with async_session() as session:
            await _lock_notification(session, transfer_id)
            row = await session.get(XpGiftTransfer, transfer_id)
            already_delivered = row is not None and row.ledger_message_id is not None
            same_guild = row is not None and row.guild_id == str(guild.id)
            if (
                row is None
                or not same_guild
                or already_delivered
                or row.notification_attempts >= service.NOTIFICATION_RETRY_LIMIT
            ):
                await session.rollback()
                return same_guild and already_delivered

            row.notification_attempts += 1
            if channels is None:
                await session.commit()
                return False
            _panel_channel, ledger = channels
            try:
                message = await _find_notification(ledger, row)
                if message is None:
                    message = await ledger.send(
                        f"🎁 <@{row.recipient_user_id}>さん、XPが届きました！",
                        embed=_notification_embed(row),
                        nonce=_notification_nonce(row.event_id),
                        allowed_mentions=_recipient_allowed_mentions(row),
                    )
                row.ledger_message_id = str(message.id)
            except discord.HTTPException:
                logger.exception("Failed to publish XP gift transfer %s", transfer_id)
            delivered = row.ledger_message_id is not None
            await session.commit()
            return delivered
    except SQLAlchemyError:
        logger.exception("Failed to persist XP gift notification %s", transfer_id)
        return False


async def _retry_pending_notifications(guild: discord.Guild) -> None:
    async with async_session() as session:
        pending = await service.list_pending_notifications(
            session, guild_id=str(guild.id)
        )
        transfer_ids = tuple(row.id for row in pending)
    for transfer_id in transfer_ids:
        await _publish_transfer(guild, transfer_id)


async def _request_level_sync(guild_id: str) -> None:
    try:
        async with async_session() as session:
            await guilds_service.request_level_role_sync(session, guild_id)
    except SQLAlchemyError:
        logger.exception("Failed to request level-role sync for guild %s", guild_id)


async def _gift_member_error(
    *, guild_id: str, sender: discord.Member, recipient: discord.Member
) -> str | None:
    if sender.id == recipient.id:
        return "自分自身へXPを贈ることはできません。"
    if sender.bot or recipient.bot:
        return "BotへXPを贈ることはできません。"
    async with async_session() as session:
        sender_excluded = await guilds_service.is_user_excluded(
            session, guild_id, str(sender.id)
        )
        recipient_excluded = await guilds_service.is_user_excluded(
            session, guild_id, str(recipient.id)
        )
    if sender_excluded:
        return "あなたは現在XP集計の対象外です。"
    if recipient_excluded:
        return "その相手は現在XP集計の対象外です。"
    return None


class XpGiftRecipientSelect(discord.ui.UserSelect[discord.ui.View]):
    def __init__(self, *, guild_id: int, sender_user_id: int) -> None:
        self.guild_id = guild_id
        self.sender_user_id = sender_user_id
        super().__init__(placeholder="XPを贈る相手を選択", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.sender_user_id:
            await interaction.response.send_message(
                "この選択画面を使えるのは開いた本人だけです。", ephemeral=True
            )
            return
        guild = interaction.guild
        sender = interaction.user
        selected = self.values[0]
        recipient = (
            selected
            if isinstance(selected, discord.Member)
            else guild.get_member(selected.id)
            if guild is not None
            else None
        )
        if (
            guild is None
            or guild.id != self.guild_id
            or not isinstance(sender, discord.Member)
            or not isinstance(recipient, discord.Member)
        ):
            await interaction.response.send_message(
                "サーバーメンバー情報を取得できませんでした。", ephemeral=True
            )
            return
        error = await _gift_member_error(
            guild_id=str(guild.id), sender=sender, recipient=recipient
        )
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return
        await interaction.response.send_modal(
            XpGiftAmountModal(
                guild_id=guild.id,
                sender_user_id=sender.id,
                recipient_user_id=recipient.id,
            )
        )


class XpGiftRecipientView(discord.ui.View):
    def __init__(self, *, guild_id: int, sender_user_id: int) -> None:
        super().__init__(timeout=180)
        self.add_item(
            XpGiftRecipientSelect(guild_id=guild_id, sender_user_id=sender_user_id)
        )


class XpGiftAmountModal(discord.ui.Modal, title="XPとメッセージを入力"):
    amount: discord.ui.TextInput[XpGiftAmountModal] = discord.ui.TextInput(
        label="贈るXP（1〜3,000）",
        placeholder="例: 500",
        min_length=1,
        max_length=5,
    )
    gift_message: discord.ui.TextInput[XpGiftAmountModal] = discord.ui.TextInput(
        label="メッセージ（任意・公開台帳に表示）",
        placeholder="例: いつも建築を手伝ってくれてありがとう！",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=service.MAX_GIFT_MESSAGE_LENGTH,
    )

    def __init__(
        self, *, guild_id: int, sender_user_id: int, recipient_user_id: int
    ) -> None:
        super().__init__()
        self.guild_id = guild_id
        self.sender_user_id = sender_user_id
        self.recipient_user_id = recipient_user_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.sender_user_id:
            await interaction.response.send_message(
                "この入力画面を使えるのは開いた本人だけです。", ephemeral=True
            )
            return
        try:
            gift_xp = int(self.amount.value.replace(",", "").strip())
        except ValueError:
            await interaction.response.send_message(
                "XPは半角数字で入力してください。", ephemeral=True
            )
            return
        if not 1 <= gift_xp <= service.MAX_GIFT_XP:
            await interaction.response.send_message(
                "贈れるXPは1〜3,000 XPです。", ephemeral=True
            )
            return
        try:
            gift_message = service.normalize_gift_message(self.gift_message.value)
        except ValueError:
            await interaction.response.send_message(
                "メッセージは120文字・4行以内で入力してください。", ephemeral=True
            )
            return
        guild = interaction.guild
        sender = guild.get_member(self.sender_user_id) if guild is not None else None
        recipient = (
            guild.get_member(self.recipient_user_id) if guild is not None else None
        )
        if (
            guild is None
            or guild.id != self.guild_id
            or sender is None
            or recipient is None
        ):
            await interaction.response.send_message(
                "サーバーメンバー情報を取得できませんでした。", ephemeral=True
            )
            return
        error = await _gift_member_error(
            guild_id=str(guild.id), sender=sender, recipient=recipient
        )
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        async with async_session() as session:
            preview = await service.preview_xp_gift(
                session,
                guild_id=str(guild.id),
                sender_user_id=str(sender.id),
                recipient_user_id=str(recipient.id),
                gift_xp=gift_xp,
            )
        if preview.status == "already_sent":
            await interaction.response.send_message(
                "本日はすでにこの相手へXPを贈っています。次は日本時間0:00以降です。",
                ephemeral=True,
            )
            return
        if preview.status == "insufficient_xp":
            shortage = preview.sender_cost_xp - preview.wallet.available_xp
            await interaction.response.send_message(
                f"XPが **{shortage:,} XP**不足しています。"
                f"（現在 {preview.wallet.available_xp:,} XP / "
                f"必要 {preview.sender_cost_xp:,} XP）",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="XPギフトの最終確認",
            description=(
                f"**{discord.utils.escape_markdown(recipient.display_name)}さん**へ\n"
                f"**{gift_xp:,} XP** を贈ります。"
            ),
            color=DEFAULT_EMBED_COLOR,
        )
        embed.add_field(name="贈与税", value=f"{preview.tax_xp:,} XP", inline=True)
        embed.add_field(
            name="合計負担", value=f"{preview.sender_cost_xp:,} XP", inline=True
        )
        embed.add_field(
            name="確定後の現在XP",
            value=f"{preview.wallet.available_xp - preview.sender_cost_xp:,} XP",
            inline=False,
        )
        if gift_message is not None:
            embed.add_field(
                name="✉️ メッセージ",
                value=_gift_message_code_block(gift_message),
                inline=False,
            )
        embed.set_footer(text="確定後は取り消せず、結果は台帳へ公開されます")
        await interaction.response.send_message(
            embed=embed,
            view=XpGiftConfirmView(
                guild_id=guild.id,
                sender_user_id=sender.id,
                recipient_user_id=recipient.id,
                gift_xp=gift_xp,
                gift_message=gift_message,
            ),
            ephemeral=True,
        )


class XpGiftConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        guild_id: int,
        sender_user_id: int,
        recipient_user_id: int,
        gift_xp: int,
        gift_message: str | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.sender_user_id = sender_user_id
        self.recipient_user_id = recipient_user_id
        self.gift_xp = gift_xp
        self.gift_message = gift_message
        self.event_id = str(uuid4())

    @discord.ui.button(
        label="この内容で贈る",
        emoji="🎁",
        style=discord.ButtonStyle.success,
        custom_id="xp-gift-confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.sender_user_id:
            await interaction.response.send_message(
                "このギフトを確定できるのは本人だけです。", ephemeral=True
            )
            return
        guild = interaction.guild
        sender = guild.get_member(self.sender_user_id) if guild is not None else None
        recipient = (
            guild.get_member(self.recipient_user_id) if guild is not None else None
        )
        if (
            guild is None
            or guild.id != self.guild_id
            or sender is None
            or recipient is None
        ):
            await interaction.response.send_message(
                "サーバーメンバー情報を取得できませんでした。", ephemeral=True
            )
            return
        error = await _gift_member_error(
            guild_id=str(guild.id), sender=sender, recipient=recipient
        )
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session() as session:
            result = await service.create_xp_gift(
                session,
                event_id=self.event_id,
                guild_id=str(guild.id),
                sender_user_id=str(sender.id),
                sender_display_name=sender.display_name,
                recipient_user_id=str(recipient.id),
                recipient_display_name=recipient.display_name,
                gift_xp=self.gift_xp,
                gift_message=self.gift_message,
            )
            transfer_id = result.transfer.id if result.transfer is not None else None

        if result.status == "completed" and transfer_id is not None:
            await _request_level_sync(str(guild.id))
            published = await _publish_transfer(guild, transfer_id)
            notification_text = (
                "台帳にも通知しました。"
                if published
                else "台帳通知は一時的に失敗したため、自動で再試行します。"
            )
            await interaction.edit_original_response(
                content=(
                    "🎁 **"
                    f"{discord.utils.escape_markdown(recipient.display_name)}さん**へ "
                    f"**{self.gift_xp:,} XP**を贈りました。\n"
                    f"残り **{result.wallet_after.available_xp:,} XP** · "
                    f"{notification_text}"
                ),
                embed=None,
                view=None,
            )
            return

        if result.status == "already_sent":
            message = "本日はすでにこの相手へXPを贈っています。"
        elif result.status == "insufficient_xp":
            message = result.message
        else:
            message = (
                "この操作は完了できませんでした。もう一度パネルから試してください。"
            )
        await interaction.edit_original_response(content=message, embed=None, view=None)

    @discord.ui.button(
        label="やめる",
        style=discord.ButtonStyle.secondary,
        custom_id="xp-gift-cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[discord.ui.View],
    ) -> None:
        if interaction.user.id != self.sender_user_id:
            await interaction.response.send_message(
                "このギフトを取り消せるのは本人だけです。", ephemeral=True
            )
            return
        await interaction.response.edit_message(
            content="XPギフトをキャンセルしました。", embed=None, view=None
        )


class DynamicXpGiftSendButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:xp-gift:send:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="XPを贈る",
                emoji="🎁",
                style=discord.ButtonStyle.primary,
                custom_id=f"level:xp-gift:send:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicXpGiftSendButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーのパネルから操作してください。", ephemeral=True
            )
            return
        if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
            await interaction.response.send_message(
                "メンバー情報を取得できませんでした。", ephemeral=True
            )
            return
        async with async_session() as session:
            excluded = await guilds_service.is_user_excluded(
                session, str(self.guild_id), str(interaction.user.id)
            )
        if excluded:
            await interaction.response.send_message(
                "あなたは現在XP集計の対象外です。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "XPを贈る相手を選んでください。",
            view=XpGiftRecipientView(
                guild_id=self.guild_id, sender_user_id=interaction.user.id
            ),
            ephemeral=True,
        )


class DynamicXpGiftBalanceButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:xp-gift:balance:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="自分のXP",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:xp-gift:balance:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicXpGiftBalanceButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーのパネルから操作してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session() as session:
            wallet = await service.wallet_for_xp_gift(
                session,
                guild_id=str(self.guild_id),
                user_id=str(interaction.user.id),
            )
        await interaction.followup.send(
            f"獲得・受取XP: **{wallet.total_xp:,} XP**\n"
            f"使用・譲渡済み: **{wallet.spent_xp:,} XP**\n"
            f"現在XP: **{wallet.available_xp:,} XP**",
            ephemeral=True,
        )


class DynamicXpGiftHistoryButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:xp-gift:history:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="送受信履歴",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:xp-gift:history:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicXpGiftHistoryButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーのパネルから操作してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = str(interaction.user.id)
        async with async_session() as session:
            transfers = await service.list_user_transfers(
                session, guild_id=str(self.guild_id), user_id=user_id
            )
        if not transfers:
            await interaction.followup.send(
                "XPギフトの送受信履歴はまだありません。", ephemeral=True
            )
            return
        lines = []
        for row in transfers:
            timestamp = int(row.created_at.timestamp())
            if row.sender_user_id == user_id:
                recipient_name = discord.utils.escape_markdown(
                    row.recipient_display_name
                )
                lines.append(
                    f"<t:{timestamp}:d> 📤 {recipient_name}さんへ "
                    f"{row.gift_xp:,} XP（税 {row.tax_xp:,} XP）"
                )
            else:
                sender_name = discord.utils.escape_markdown(row.sender_display_name)
                lines.append(
                    f"<t:{timestamp}:d> 📥 {sender_name}さんから {row.gift_xp:,} XP"
                )
        await interaction.followup.send(
            embed=discord.Embed(
                title="自分のXPギフト履歴",
                description="\n".join(lines),
                color=DEFAULT_EMBED_COLOR,
            ),
            ephemeral=True,
        )


class DynamicXpGiftRulesButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:xp-gift:rules:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="仕組みを見る",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:xp-gift:rules:{guild_id}",
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicXpGiftRulesButton:
        return cls(int(match["guild_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーのパネルから操作してください。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=build_panel_embed(), ephemeral=True
        )


class XpGiftPanelView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(DynamicXpGiftSendButton(guild_id))
        self.add_item(DynamicXpGiftBalanceButton(guild_id))
        self.add_item(DynamicXpGiftHistoryButton(guild_id))
        self.add_item(DynamicXpGiftRulesButton(guild_id))


async def _find_panel_message(
    channel: discord.TextChannel,
) -> discord.Message | None:
    async for message in channel.history(limit=None):
        if message.author.bot and any(
            embed.title == PANEL_TITLE for embed in message.embeds
        ):
            return message
    return None


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
        )
        await channel.set_permissions(me, overwrite=bot_permissions)
    return channel


async def _upsert_panel(
    guild: discord.Guild,
    channel: discord.TextChannel,
    panel_message_id: str | None,
) -> discord.Message:
    message: discord.Message | None = None
    if panel_message_id is not None:
        with contextlib.suppress(discord.NotFound):
            message = await channel.fetch_message(int(panel_message_id))
    if message is None:
        message = await _find_panel_message(channel)
    if message is None:
        return await channel.send(
            embed=build_panel_embed(),
            view=XpGiftPanelView(guild.id),
            allowed_mentions=discord.AllowedMentions.none(),
        )
    await message.edit(
        content=None,
        embed=build_panel_embed(),
        view=XpGiftPanelView(guild.id),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return message


async def _ensure_setup(
    guild: discord.Guild, *, require_existing: bool
) -> tuple[discord.TextChannel, discord.TextChannel] | None:
    async with async_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:setup_key))"),
            {"setup_key": f"xp-gift-setup:{guild.id}"},
        )
        config = await service.get_guild_config(session, str(guild.id))
        if config is None and require_existing:
            await session.rollback()
            return None
        panel_channel = await _find_or_create_channel(
            guild,
            PANEL_CHANNEL_NAME,
            config.panel_channel_id if config is not None else None,
        )
        ledger_channel = await _find_or_create_channel(
            guild,
            LEDGER_CHANNEL_NAME,
            config.ledger_channel_id if config is not None else None,
        )
        panel = await _upsert_panel(
            guild,
            panel_channel,
            config.panel_message_id if config is not None else None,
        )
        await service.save_guild_config(
            session,
            guild_id=str(guild.id),
            panel_channel_id=str(panel_channel.id),
            ledger_channel_id=str(ledger_channel.id),
            panel_message_id=str(panel.id),
        )
        return panel_channel, ledger_channel


class XpGiftCog(commands.Cog):
    xp_gift_group = app_commands.Group(
        name="xp-gift",
        description="XPギフトの管理",
        default_permissions=discord.Permissions(administrator=True),
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._ready_handled = False

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
                    "Failed to retry XP gift notifications for guild %s", guild.id
                )

    @_notification_retry_loop.before_loop
    async def _before_notification_retry_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._ready_handled:
            return
        self._ready_handled = True
        for guild in self.bot.guilds:
            try:
                await _ensure_setup(guild, require_existing=True)
                await _retry_pending_notifications(guild)
            except (discord.HTTPException, SQLAlchemyError):
                logger.exception(
                    "Failed to repair XP gift setup for guild %s", guild.id
                )

    @xp_gift_group.command(
        name="setup", description="XPギフトのパネルと公開台帳を作成または修復"
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def setup_xp_gift(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        channels = await _ensure_setup(interaction.guild, require_existing=False)
        if channels is None:
            await interaction.followup.send(
                "セットアップできませんでした。", ephemeral=True
            )
            return
        panel_channel, ledger_channel = channels
        await _retry_pending_notifications(interaction.guild)
        await interaction.followup.send(
            f"セットアップしました: {panel_channel.mention} / {ledger_channel.mention}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @xp_gift_group.command(
        name="retry-notifications",
        description="停止済みを再開し、未配信のXPギフト台帳通知を再試行",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def retry_notifications(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        async with async_session() as session:
            rearmed_ids = await service.rearm_failed_notifications(
                session,
                guild_id=str(guild.id),
            )
            pending = await service.list_pending_notifications(
                session,
                guild_id=str(guild.id),
            )
            pending_ids = tuple(row.id for row in pending)

        delivered = 0
        for transfer_id in pending_ids:
            delivered += int(await _publish_transfer(guild, transfer_id))
        if not pending_ids:
            message = "再試行対象のXPギフト台帳通知はありません。"
        else:
            message = (
                f"停止済み **{len(rearmed_ids)}件**を再開し、"
                f"未配信 **{len(pending_ids)}件**を再試行しました。\n"
                f"今回の配信成功: **{delivered}件**"
            )
        await interaction.followup.send(message, ephemeral=True)


def register_xp_gift_dynamic_items(bot: commands.Bot) -> None:
    bot.add_dynamic_items(
        DynamicXpGiftSendButton,
        DynamicXpGiftBalanceButton,
        DynamicXpGiftHistoryButton,
        DynamicXpGiftRulesButton,
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(XpGiftCog(bot))
