"""カフェガチャの常設パネル、公開開封、コレクションUI。"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import re
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.database.models import (
    CafeGachaDraw,
    CafeGachaRedemption,
    CafeGachaRedemptionItem,
)
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import (
    CARDS,
    CARDS_BY_KEY,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
    rarity_label,
)
from src.features.cafe_gacha.collection_image import render_collection_shelf
from src.features.color_role_shop.service import wallet_for_user
from src.features.guilds.service import request_level_role_sync
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels

logger = logging.getLogger(__name__)
ASSET_DIR = Path(__file__).parent.parent / "features" / "cafe_gacha" / "assets"
COUNTER_NAME = "☕️カフェカウンター"
LEDGER_NAME = "📒カフェ台帳"
NOTIFICATION_RETRY_MINUTES = 5.0
PANEL_TITLE = "☕ カフェ・コレクション"


async def _earned_xp(guild_id: str, user_id: str) -> int:
    async with async_session() as session:
        levels = await get_user_lifetime_levels(session, guild_id, user_id)
        return earned_total_xp(levels) if levels is not None else 0


async def _request_level_sync(guild_id: str) -> None:
    try:
        async with async_session() as session:
            await request_level_role_sync(session, guild_id)
    except SQLAlchemyError:
        logger.exception("Failed to request level-role sync for guild %s", guild_id)


def build_panel_content() -> str:
    return (
        f"# {PANEL_TITLE}\n"
        "棚からカードを一枚どうぞ。結果はカフェ台帳でみんなに公開されます。\n\n"
        f"**1時間{MAX_HOURLY_DRAWS}回まで** / 1日1回無料 / 2回目以降は **20 XP**\n"
        "獲得XP: N 25 / UC 30 / R 50 / SR 100 / SSR 300 XP\n"
        "有料でも **最低 +5 XP**（20 XP消費 → 25 XP以上獲得）\n"
        "最初の1枚はコレクション用に残り、重複分は好きな枚数だけXPへ交換できます。\n"
        "結果はすべて公開され、投稿はそのまま残ります。\n\n"
        "重複交換: N 3 / UC 10 / R 30 / SR 100 / SSR 300 XP\n"
        "※有料分の消費により総合レベルが下がる場合があります。\n"
        "-# 1日1回の無料分は毎日 0:00（日本時間）に更新"
    )


def _draw_marker(event_id: str) -> str:
    """旧形式の公開メッセージを回収するための互換マーカー。"""
    return f"cafe-draw:{event_id}"


def _notification_nonce(record_type: str, event_id: str) -> int:
    """利用者に表示しないDiscord nonceへイベント識別子を変換する。"""
    digest = hashlib.blake2b(
        f"cafe:{record_type}:{event_id}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


def _paid_draw_confirmation(available_xp: int) -> str:
    return (
        f"1日1回の無料分は使用済みです。**{PAID_DRAW_COST_XP} XP** で"
        "もう一枚引きますか？\n"
        "**最低でも差引 +5 XP** になります（25 XP以上獲得）。\n"
        f"現在XP: **{available_xp:,} XP**\n"
        f"※抽選は毎時00分リセットで、1時間{MAX_HOURLY_DRAWS}回までです。\n"
        "※XP消費により総合レベルが下がる場合があります。"
    )


def _result_content(
    draw: CafeGachaDraw,
    *,
    owned_count: int,
    collected_count: int,
) -> str:
    duplicate = " · 重複" if draw.was_duplicate else " · NEW!"
    cost = "無料" if draw.draw_type == "free" else f"{draw.cost_xp:,} XP消費"
    rare_notice = ""
    if draw.rarity in ("SR", "SSR"):
        rare_notice = "\n✨ カフェに珍しい一枚が並びました"
    net_xp = draw.reward_xp - draw.cost_xp
    return (
        f"**{draw.display_name} さんが一枚引きました**\n"
        f"## {rarity_label(draw.rarity)}｜{draw.reward_name}\n"
        f"{draw.reward_description}\n\n"
        f"**XP収支**\n{cost} → {draw.reward_xp:,} XP獲得{duplicate}\n"
        f"## 今回の収支 +{net_xp:,} XP\n\n"
        "**コレクション**\n"
        f"所持 {owned_count}枚 · 交換可能 {max(0, owned_count - 1)}枚\n"
        f"収集 {collected_count}/{len(CARDS)}種"
        f"{rare_notice}"
    )


async def _configured_channels(
    guild: discord.Guild,
) -> tuple[discord.TextChannel, discord.TextChannel] | None:
    async with async_session() as session:
        config = await service.get_guild_config(session, str(guild.id))
    if config is None:
        return None
    counter = guild.get_channel(int(config.counter_channel_id))
    ledger = guild.get_channel(int(config.ledger_channel_id))
    if not isinstance(counter, discord.TextChannel) or not isinstance(
        ledger, discord.TextChannel
    ):
        return None
    return counter, ledger


async def _lock_notification(
    session: AsyncSession, *, record_type: str, record_id: int
) -> None:
    """同じDBイベントのDiscord通知をプロセスをまたいで直列化する。"""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:notification_key))"),
        {"notification_key": f"cafe-notification:{record_type}:{record_id}"},
    )


async def _find_notification(
    channel: discord.TextChannel,
    *,
    record_type: str,
    event_id: str,
    created_at: datetime,
) -> discord.Message | None:
    """DB保存前に停止した投稿を非表示のnonceから回収する。"""
    nonce = str(_notification_nonce(record_type, event_id))
    legacy_marker = _draw_marker(event_id) if record_type == "draw" else event_id
    async for message in channel.history(
        limit=None, after=created_at - timedelta(minutes=1)
    ):
        if not message.author.bot:
            continue
        if str(message.nonce) == nonce:
            return message
        if legacy_marker in message.content or any(
            legacy_marker in embed.footer.text
            for embed in message.embeds
            if embed.footer.text
        ):
            return message
    return None


async def _find_panel_message(
    channel: discord.TextChannel,
) -> discord.Message | None:
    """設定保存前に停止した場合も既存の常設パネルを回収する。"""
    async for message in channel.history(limit=None):
        if not message.author.bot:
            continue
        if PANEL_TITLE in message.content or any(
            embed.title == PANEL_TITLE for embed in message.embeds
        ):
            return message
    return None


async def _publish_draw(guild: discord.Guild, draw: CafeGachaDraw) -> bool:
    try:
        channels = await _configured_channels(guild)
    except SQLAlchemyError:
        logger.exception("Failed to load cafe gacha channels")
        return False
    if channels is None:
        return False
    _counter, ledger = channels
    try:
        async with async_session() as session:
            await _lock_notification(session, record_type="draw", record_id=draw.id)
            row = await session.get(CafeGachaDraw, draw.id)
            if row is None:
                await session.rollback()
                return False

            ledger_published = row.ledger_message_id is not None
            if not ledger_published:
                try:
                    message = await _find_notification(
                        ledger,
                        record_type="draw",
                        event_id=row.event_id,
                        created_at=row.created_at,
                    )
                    image_path = ASSET_DIR / row.image_filename
                    files = (
                        [discord.File(image_path, filename=row.image_filename)]
                        if image_path.is_file()
                        else []
                    )
                    result_content = _result_content(
                        row,
                        owned_count=row.owned_count,
                        collected_count=row.collected_count,
                    )
                    if message is None:
                        message = await ledger.send(
                            result_content,
                            files=files,
                            nonce=_notification_nonce("draw", row.event_id),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    row.ledger_message_id = str(message.id)
                    ledger_published = True
                except (discord.HTTPException, OSError):
                    logger.exception("Failed to publish cafe gacha draw to ledger")

            await session.commit()
            return ledger_published
    except SQLAlchemyError:
        logger.exception("Failed to persist cafe gacha draw notifications")
        return False


async def _publish_redemption(
    guild: discord.Guild,
    redemption: CafeGachaRedemption,
) -> None:
    try:
        channels = await _configured_channels(guild)
    except SQLAlchemyError:
        logger.exception("Failed to load cafe gacha channels")
        return
    if channels is None:
        return
    _counter, ledger = channels
    try:
        async with async_session() as session:
            await _lock_notification(
                session, record_type="redemption", record_id=redemption.id
            )
            row = await session.get(CafeGachaRedemption, redemption.id)
            if row is None:
                await session.rollback()
                return
            items = tuple(
                (
                    await session.execute(
                        select(CafeGachaRedemptionItem).where(
                            CafeGachaRedemptionItem.redemption_id == row.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            detail = "、".join(f"{item.reward_name}×{item.quantity}" for item in items)
            notification_text = (
                f"♻️ **{row.display_name}** さんが {detail} を "
                f"**{row.reward_xp:,} XP** に交換しました。"
            )
            if row.ledger_message_id is None:
                try:
                    message = await _find_notification(
                        ledger,
                        record_type="redemption",
                        event_id=row.event_id,
                        created_at=row.created_at,
                    )
                    if message is None:
                        message = await ledger.send(
                            notification_text,
                            nonce=_notification_nonce("redemption", row.event_id),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    row.ledger_message_id = str(message.id)
                except discord.HTTPException:
                    logger.exception(
                        "Failed to publish cafe gacha redemption to ledger"
                    )
            await session.commit()
    except SQLAlchemyError:
        logger.exception("Failed to persist cafe gacha redemption notifications")


async def _retry_pending_notifications(guild: discord.Guild) -> None:
    async with async_session() as session:
        draws = tuple(
            (
                await session.execute(
                    select(CafeGachaDraw)
                    .where(
                        CafeGachaDraw.guild_id == str(guild.id),
                        CafeGachaDraw.ledger_message_id.is_(None),
                    )
                    .order_by(CafeGachaDraw.id.asc())
                )
            )
            .scalars()
            .all()
        )
        redemptions = tuple(
            (
                await session.execute(
                    select(CafeGachaRedemption)
                    .where(
                        CafeGachaRedemption.guild_id == str(guild.id),
                        CafeGachaRedemption.ledger_message_id.is_(None),
                    )
                    .order_by(CafeGachaRedemption.id.asc())
                )
            )
            .scalars()
            .all()
        )
    for draw in draws:
        await _publish_draw(guild, draw)
    for redemption in redemptions:
        await _publish_redemption(guild, redemption)


async def _perform_draw(
    interaction: discord.Interaction,
    *,
    guild_id: int,
    event_id: str,
    allow_paid: bool,
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
        )
    if result.status == "confirmation_required":
        await interaction.followup.send(
            _paid_draw_confirmation(result.wallet_before.available_xp),
            view=PaidDrawConfirmView(guild.id, interaction.user.id),
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
            "次の毎時00分（日本時間）から引けます。",
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
    if published:
        await interaction.followup.send(
            "カフェ台帳にカードを公開しました。", ephemeral=True
        )
    else:
        await interaction.followup.send(
            "抽選は確定しましたが、カフェ台帳へ投稿できませんでした。管理者に連絡してください。",
            ephemeral=True,
        )


class PaidDrawConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.event_id = str(uuid4())

    @discord.ui.button(label="20 XPで引く", style=discord.ButtonStyle.primary)
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _perform_draw(
            interaction,
            guild_id=self.guild_id,
            event_id=self.event_id,
            allow_paid=True,
        )
        self.stop()

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
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
            content="今回は見送りました。", view=None
        )
        self.stop()


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

    @discord.ui.button(label="この内容で交換", style=discord.ButtonStyle.danger)
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
        await interaction.response.defer(ephemeral=True, thinking=True)
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
        self.stop()

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
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "本人だけが操作できます。", ephemeral=True
        )
        return False

    @discord.ui.button(label="1枚", style=discord.ButtonStyle.primary)
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

    @discord.ui.button(label="重複をすべて", style=discord.ButtonStyle.secondary)
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

    @discord.ui.button(label="枚数を指定", style=discord.ButtonStyle.secondary)
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
    ) -> None:
        self.guild_id = guild_id
        self.user_id = user_id
        self.maximum_by_key = {
            item.card.key: item.redeemable_count
            for item in collection
            if item.redeemable_count > 0
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
            if item.redeemable_count > 0
        ]
        super().__init__(placeholder="交換するカードを選ぶ", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
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


class FavoriteSelect(discord.ui.Select[discord.ui.View]):
    def __init__(
        self,
        guild_id: int,
        user_id: int,
        collection: tuple[service.CollectionCard, ...],
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
                if item.count > 0
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "本人だけが操作できます。", ephemeral=True
            )
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


class BulkRedemptionConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, user_id: int, quantities: dict[str, int]) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.user_id = user_id
        self.quantities = quantities
        self.event_id = str(uuid4())

    @discord.ui.button(label="すべて交換する", style=discord.ButtonStyle.danger)
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
        await interaction.response.defer(ephemeral=True, thinking=True)
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
        self.stop()

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
            label="重複をまとめて交換",
            style=discord.ButtonStyle.secondary,
            emoji="♻️",
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
        details = [
            f"{CARDS_BY_KEY[key].name} ×{quantity}（交換後 1枚）"
            for key, quantity in self.quantities.items()
        ]
        total_xp = sum(
            CARDS_BY_KEY[key].exchange_xp * quantity
            for key, quantity in self.quantities.items()
        )
        await interaction.response.send_message(
            (
                "次の重複カードをまとめて交換します。\n"
                + "\n".join(details)
                + f"\n\n受取合計: **{total_xp:,} XP**"
            ),
            view=BulkRedemptionConfirmView(
                self.guild_id, self.user_id, self.quantities
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
            self.add_item(FavoriteSelect(guild_id, user_id, collection))
        if any(item.redeemable_count > 0 for item in collection):
            self.add_item(RedemptionSelect(guild_id, user_id, collection))
            self.add_item(BulkExchangeButton(guild_id, user_id, collection))


def _exchange_guidance(collection: tuple[service.CollectionCard, ...]) -> str:
    redeemable_total = sum(item.redeemable_count for item in collection)
    if redeemable_total == 0:
        return (
            "交換できる重複カードはまだありません。"
            "同じカードの2枚目以降がXP交換の対象になります。"
        )
    return (
        f"交換可能なカードが合計 **{redeemable_total}枚** あります。"
        "この下のメニューからカードと枚数を選べます。"
    )


async def _show_collection(interaction: discord.Interaction, guild_id: int) -> None:
    async with async_session() as session:
        collection = await service.list_collection(
            session, guild_id=str(guild_id), user_id=str(interaction.user.id)
        )
        favorite = await service.favorite_card(
            session, guild_id=str(guild_id), user_id=str(interaction.user.id)
        )
    owned = sum(item.count > 0 for item in collection)
    lines = [
        (
            f"**{rarity_label(item.card.rarity)}｜{item.card.name}** ×{item.count}"
            + (f"（交換可 {item.redeemable_count}）" if item.redeemable_count else "")
        )
        for item in collection
        if item.count > 0
    ]
    embed = discord.Embed(
        title=f"🗃️ {interaction.user.display_name} のカード棚",
        description=("\n".join(lines) if lines else "まだカードはありません。")[:4000],
        color=DEFAULT_EMBED_COLOR,
    )
    if favorite is not None:
        embed.add_field(
            name="お気に入りの一枚",
            value=f"{rarity_label(favorite.rarity)}｜{favorite.name}",
        )
    embed.add_field(name="XP交換", value=_exchange_guidance(collection), inline=False)
    embed.set_footer(
        text=f"収集 {owned}/{len(collection)}種 · 最初の1枚は交換されません"
    )
    files: list[discord.File] = []
    try:
        shelf = render_collection_shelf(
            ASSET_DIR, {item.card.key: item.count for item in collection}
        )
        files.append(discord.File(BytesIO(shelf), filename="collection.jpg"))
        embed.set_image(url="attachment://collection.jpg")
    except OSError:
        logger.exception("Failed to render cafe collection shelf")
    await interaction.followup.send(
        embed=embed,
        files=files,
        view=CollectionView(guild_id, interaction.user.id, collection),
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _perform_draw(
            interaction,
            guild_id=self.guild_id,
            event_id=str(interaction.id),
            allow_paid=False,
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
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーでは利用できません。", ephemeral=True
            )
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
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーでは利用できません。", ephemeral=True
            )
            return
        lines = [
            (
                f"**{rarity_label(card.rarity)}｜{card.name}** "
                f"{card.weight / 100:.2f}% · 獲得 {card.draw_reward_xp} XP"
                f" · 重複交換 {card.exchange_xp} XP"
            )
            for card in CARDS
        ]
        embed = discord.Embed(
            title="☕ カフェ棚の排出一覧",
            description="\n".join(lines),
            color=DEFAULT_EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class DynamicCafeBalanceButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=r"level:cafe:balance:(?P<guild_id>\d+)",
):
    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        super().__init__(
            discord.ui.Button(
                label="自分のXP",
                style=discord.ButtonStyle.secondary,
                custom_id=f"level:cafe:balance:{guild_id}",
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
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーでは利用できません。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        total_xp = await _earned_xp(str(self.guild_id), str(interaction.user.id))
        async with async_session() as session:
            wallet = await wallet_for_user(
                session,
                guild_id=str(self.guild_id),
                user_id=str(interaction.user.id),
                total_xp=total_xp,
            )
        await interaction.followup.send(
            (
                f"獲得XP: **{wallet.total_xp:,} XP**\n"
                f"消費済み: **{wallet.spent_xp:,} XP**\n"
                f"現在XP: **{wallet.available_xp:,} XP**"
            ),
            ephemeral=True,
        )


class CafeGachaPanelView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(DynamicCafeDrawButton(guild_id))
        self.add_item(DynamicCafeCollectionButton(guild_id))
        self.add_item(DynamicCafeCatalogButton(guild_id))
        self.add_item(DynamicCafeBalanceButton(guild_id))


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
    *,
    repost: bool = False,
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
    if message is None or repost:
        new_message = await counter.send(
            build_panel_content(),
            files=files,
            view=CafeGachaPanelView(guild.id),
        )
        if message is not None:
            try:
                await message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                logger.exception(
                    "Failed to delete previous cafe gacha panel %s", message.id
                )
                with contextlib.suppress(discord.HTTPException):
                    await new_message.delete()
                raise
        return new_message
    await message.edit(
        content=build_panel_content(),
        embed=None,
        attachments=files,
        view=CafeGachaPanelView(guild.id),
    )
    return message


async def _ensure_setup(
    guild: discord.Guild, *, require_existing: bool, repost_panel: bool = False
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
            repost=repost_panel,
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
    await _ensure_setup(guild, require_existing=True, repost_panel=True)


class CafeGachaCog(commands.Cog):
    cafe_group = app_commands.Group(
        name="cafe-gacha",
        description="カフェガチャの管理",
        default_permissions=discord.Permissions(administrator=True),
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


def register_cafe_gacha_dynamic_items(bot: commands.Bot) -> None:
    bot.add_dynamic_items(
        DynamicCafeDrawButton,
        DynamicCafeCollectionButton,
        DynamicCafeCatalogButton,
        DynamicCafeBalanceButton,
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CafeGachaCog(bot))
