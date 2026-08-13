"""カフェガチャの常設パネル、公開開封、コレクションUI。"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import re
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.cogs.feature_access import ensure_feature_access, format_access_roles
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
    DRAW_REWARD_XP_BY_RARITY,
    ENDGAME_PITY_DUPLICATE_DRAWS,
    ENDGAME_PITY_MIN_COLLECTED,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
    RARITY_ORDER,
    RARITY_TOTAL_WEIGHTS,
    Rarity,
    rarity_label,
)
from src.features.cafe_gacha.collection_image import render_collection_shelves
from src.features.feature_access import service as feature_access_service
from src.features.guilds.service import request_level_role_sync
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels

logger = logging.getLogger(__name__)
ASSET_DIR = Path(__file__).parent.parent / "features" / "cafe_gacha" / "assets"
COUNTER_NAME = "☕️カフェカウンター"
LEDGER_NAME = "📒カフェ台帳"
NOTIFICATION_RETRY_MINUTES = 5.0
PANEL_TITLE = "☕ カフェ・コレクション"
PUBLIC_MENTION_RARITY_RANK = {"R": 0, "SR": 1, "SSR": 2}
RARITY_XP_TEXT = " / ".join(
    f"{rarity_label(rarity)} {xp}" for rarity, xp in DRAW_REWARD_XP_BY_RARITY.items()
)
MIN_DRAW_REWARD_XP = min(DRAW_REWARD_XP_BY_RARITY.values())
MAX_DRAW_REWARD_XP = max(DRAW_REWARD_XP_BY_RARITY.values())


def _next_hour_label(now: datetime | None = None) -> str:
    local_now = now or datetime.now(service.TOKYO)
    next_hour = local_now.astimezone(service.TOKYO).replace(
        minute=0, second=0, microsecond=0
    ) + timedelta(hours=1)
    return next_hour.strftime("%H:%M")


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


def build_panel_embed(*, with_image: bool = True) -> discord.Embed:
    embed = discord.Embed(
        title=PANEL_TITLE,
        description=(
            "カードを集めながら、**引くたびXPが必ず増える**コレクションです。\n"
            "重複カードは、さらに獲得時と同額のXPへ交換できます。\n\n"
            f"**🎟️ 1日1回無料** / 2回目以降 {PAID_DRAW_COST_XP} XP / "
            f"1時間{MAX_HOURLY_DRAWS}回まで（**1日合計の上限なし**）\n"
            "まとめ引きは、残り枠とXPに合わせて最大10枚を台帳へ1投稿します。\n"
            "各カードの獲得XPは、同じまとめ引きの次の1枚にも使われます。\n"
            f"**必ず黒字：{MIN_DRAW_REWARD_XP}〜{MAX_DRAW_REWARD_XP} XP獲得"
            f"（有料でも +{MIN_DRAW_REWARD_XP - PAID_DRAW_COST_XP} XP以上）**\n\n"
            "**✨ レアリティ別XP（獲得・重複交換 共通）**\n"
            f"{RARITY_XP_TEXT} XP\n\n"
            "未収集カードは、同じレアリティ内で **2倍** 出やすくなります。\n"
            f"{ENDGAME_PITY_MIN_COLLECTED}種以上集めてから"
            f"{ENDGAME_PITY_DUPLICATE_DRAWS}回連続でNEWなしなら、次は未所持確定です。\n"
            "最初の1枚はコレクションに残り、2枚目以降を好きな枚数だけ"
            "交換できます。\n"
            "結果はカフェ台帳に公開されます。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    if with_image:
        embed.set_image(url="attachment://panel-cabinet.jpg")
    embed.set_footer(text="1日1回の無料分は毎日 0:00に更新")
    return embed


def _draw_marker(event_id: str) -> str:
    """旧形式の公開メッセージを回収するための互換マーカー。"""
    return f"cafe-draw:{event_id}"


def _notification_nonce(record_type: str, event_id: str) -> int:
    """利用者に表示しないDiscord nonceへイベント識別子を変換する。"""
    digest = hashlib.blake2b(
        f"cafe:{record_type}:{event_id}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


def _result_embed(
    draw: CafeGachaDraw,
    *,
    owned_count: int,
    collected_count: int,
    with_image: bool,
    attachment_filename: str | None = None,
) -> discord.Embed:
    colors = {
        "C": 0x8B7D6B,
        "UC": 0x5FA36A,
        "R": 0x4C83C3,
        "SR": 0xA659C5,
        "SSR": 0xD6A72C,
    }
    duplicate = " · 重複" if draw.was_duplicate else " · NEW!"
    cost = "無料" if draw.draw_type == "free" else f"{draw.cost_xp:,} XP消費"
    net_xp = draw.reward_xp - draw.cost_xp
    exchange_bonus = (
        f"\n♻️ 重複カードは交換すると **さらに +{draw.exchange_xp:,} XP！**"
        if draw.was_duplicate
        else ""
    )
    embed = discord.Embed(
        title=f"{rarity_label(draw.rarity)}｜{draw.reward_name}",
        description=(
            f"**<@{draw.user_id}> さんが一枚引きました**\n\n{draw.reward_description}"
        ),
        color=colors[draw.rarity],
    )
    embed.add_field(
        name=f"🎉 +{net_xp:,} XPの黒字！",
        value=(
            f"{cost} → {draw.reward_xp:,} XP獲得{duplicate}\n"
            f"**引くたび必ずプラス！**{exchange_bonus}"
        ),
        inline=False,
    )
    embed.add_field(
        name="📚 コレクション",
        value=(
            f"所持 {owned_count}枚 · 交換可能 {max(0, owned_count - 1)}枚\n"
            f"収集 {collected_count}/{len(CARDS)}種"
        ),
        inline=False,
    )
    if with_image:
        embed.set_image(
            url=f"attachment://{attachment_filename or draw.image_filename}"
        )
    if draw.rarity in ("SR", "SSR"):
        embed.set_footer(text="✨ カフェに珍しい一枚が並びました")
    return embed


def _redemption_embed(
    redemption: CafeGachaRedemption,
    *,
    detail: str,
) -> discord.Embed:
    return discord.Embed(
        title="♻️ 重複カード交換でXPボーナス！",
        description=(
            f"**<@{redemption.user_id}> さんが交換しました**\n\n"
            f"{detail}\n\n"
            f"**🎉 +{redemption.reward_xp:,} XPを追加獲得！**"
        ),
        color=0x57F287,
    )


def _redemption_detail(items: tuple[CafeGachaRedemptionItem, ...]) -> str:
    detail = "、".join(f"{item.reward_name}×{item.quantity}" for item in items)
    if len(detail) <= 3000:
        return detail
    lines = []
    for rarity in RARITY_ORDER:
        rarity_items = tuple(item for item in items if item.rarity == rarity)
        if not rarity_items:
            continue
        lines.append(
            f"{rarity_label(rarity)}: {len(rarity_items)}種・"
            f"合計{sum(item.quantity for item in rarity_items)}枚"
        )
    return "全カードの重複を一括交換\n" + "\n".join(lines)


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
    session: AsyncSession, *, record_type: str, record_id: int | str
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
    legacy_marker = (
        _draw_marker(event_id)
        if record_type == "draw"
        else event_id
        if record_type == "redemption"
        else None
    )
    async for message in channel.history(
        limit=None, after=created_at - timedelta(minutes=1)
    ):
        if not message.author.bot:
            continue
        if str(message.nonce) == nonce:
            return message
        if legacy_marker is not None and (
            legacy_marker in message.content
            or any(
                legacy_marker in embed.footer.text
                for embed in message.embeds
                if embed.footer.text
            )
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


def _rare_draw_mention_content(
    draws: tuple[CafeGachaDraw, ...],
) -> str | None:
    mentioned_rarities = [
        draw.rarity for draw in draws if draw.rarity in PUBLIC_MENTION_RARITY_RANK
    ]
    if not mentioned_rarities:
        return None
    user_id = draws[0].user_id
    if any(draw.user_id != user_id for draw in draws):
        logger.error("Cafe gacha batch contains draws for multiple users")
        return None
    highest_rarity = max(
        mentioned_rarities,
        key=PUBLIC_MENTION_RARITY_RANK.__getitem__,
    )
    return f"🎉 <@{user_id}>さん、{highest_rarity}以上のカードを獲得しました！"


def _highest_rarity(draws: tuple[CafeGachaDraw, ...]) -> str:
    return max(
        (draw.rarity for draw in draws),
        key=lambda rarity: RARITY_ORDER.index(rarity),
    )


def _batch_summary_content(draws: tuple[CafeGachaDraw, ...]) -> str:
    total_cost = sum(draw.cost_xp for draw in draws)
    total_reward = sum(draw.reward_xp for draw in draws)
    new_count = sum(not draw.was_duplicate for draw in draws)
    return (
        f"☕ **{len(draws)}枚まとめ引き**｜最高 "
        f"**{rarity_label(_highest_rarity(draws))}**｜NEW **{new_count}枚**\n"
        f"{total_cost:,} XP消費 → {total_reward:,} XP獲得 "
        f"（差引 **+{total_reward - total_cost:,} XP**）"
    )


async def _publish_rare_draw_mention(
    ledger: discord.TextChannel,
    draws: tuple[CafeGachaDraw, ...],
) -> bool:
    content = _rare_draw_mention_content(draws)
    if content is None:
        return True
    first_draw = draws[0]
    try:
        async with async_session() as session:
            await _lock_notification(
                session,
                record_type="draw-rare-mention",
                record_id=first_draw.batch_id,
            )
            message = await _find_notification(
                ledger,
                record_type="draw-rare-mention",
                event_id=first_draw.batch_id,
                created_at=first_draw.created_at,
            )
            if message is None:
                await ledger.send(
                    content,
                    nonce=_notification_nonce("draw-rare-mention", first_draw.batch_id),
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        users=[discord.Object(id=int(first_draw.user_id))],
                        roles=False,
                        replied_user=False,
                    ),
                )
            await session.commit()
            return True
    except (discord.HTTPException, SQLAlchemyError):
        logger.exception("Failed to publish cafe gacha rare draw mention")
        return False


async def _publish_draws(
    guild: discord.Guild, draws: tuple[CafeGachaDraw, ...]
) -> bool:
    if not draws:
        return False
    batch_id = draws[0].batch_id
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
            await _lock_notification(
                session, record_type="draw-batch", record_id=batch_id
            )
            rows = tuple(
                (
                    await session.execute(
                        select(CafeGachaDraw)
                        .where(
                            CafeGachaDraw.guild_id == str(guild.id),
                            CafeGachaDraw.batch_id == batch_id,
                        )
                        .order_by(CafeGachaDraw.batch_position.asc())
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                await session.rollback()
                return False

            ledger_message_id = next(
                (row.ledger_message_id for row in rows if row.ledger_message_id),
                None,
            )
            ledger_published = ledger_message_id is not None
            if not ledger_published:
                try:
                    is_batch = len(rows) > 1
                    message = await _find_notification(
                        ledger,
                        record_type="draw-batch" if is_batch else "draw",
                        event_id=batch_id if is_batch else rows[0].event_id,
                        created_at=rows[0].created_at,
                    )
                    if message is None and is_batch:
                        files: list[discord.File] = []
                        result_embeds: list[discord.Embed] = []
                        batch_size = len(rows)
                        try:
                            for row in rows:
                                image_path = ASSET_DIR / row.image_filename
                                if not image_path.is_file():
                                    raise OSError(f"missing cafe image: {image_path}")
                                attachment_filename = (
                                    f"{row.batch_position:02d}-{row.image_filename}"
                                )
                                files.append(
                                    discord.File(
                                        image_path,
                                        filename=attachment_filename,
                                    )
                                )
                                result_embed = _result_embed(
                                    row,
                                    owned_count=row.owned_count,
                                    collected_count=row.collected_count,
                                    with_image=True,
                                    attachment_filename=attachment_filename,
                                )
                                result_embed.title = (
                                    f"☕ {batch_size}枚まとめ "
                                    f"{row.batch_position}/{batch_size}｜"
                                    f"{rarity_label(row.rarity)}｜{row.reward_name}"
                                )
                                result_embeds.append(result_embed)
                            message = await ledger.send(
                                content=_batch_summary_content(rows),
                                embeds=result_embeds,
                                files=files,
                                nonce=_notification_nonce("draw-batch", batch_id),
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                        finally:
                            for file in files:
                                file.close()
                    elif message is None:
                        image_path = ASSET_DIR / rows[0].image_filename
                        files = (
                            [
                                discord.File(
                                    image_path,
                                    filename=rows[0].image_filename,
                                )
                            ]
                            if image_path.is_file()
                            else []
                        )
                        result_embed = _result_embed(
                            rows[0],
                            owned_count=rows[0].owned_count,
                            collected_count=rows[0].collected_count,
                            with_image=bool(files),
                        )
                        try:
                            message = await ledger.send(
                                embed=result_embed,
                                files=files,
                                nonce=_notification_nonce("draw", rows[0].event_id),
                                allowed_mentions=discord.AllowedMentions.none(),
                            )
                        finally:
                            for file in files:
                                file.close()
                    ledger_message_id = str(message.id)
                    ledger_published = True
                except (discord.HTTPException, OSError):
                    logger.exception("Failed to publish cafe gacha draw to ledger")

            if ledger_message_id is not None:
                for row in rows:
                    row.ledger_message_id = ledger_message_id
            mention_published = True
            if ledger_published:
                mention_published = await _publish_rare_draw_mention(ledger, rows)
            if ledger_published and mention_published:
                await session.commit()
                return True
            await session.rollback()
            return ledger_published
    except SQLAlchemyError:
        logger.exception("Failed to persist cafe gacha draw notifications")
        return False


async def _publish_draw(guild: discord.Guild, draw: CafeGachaDraw) -> bool:
    return await _publish_draws(guild, (draw,))


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
            notification_embed = _redemption_embed(
                row, detail=_redemption_detail(items)
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
                            embed=notification_embed,
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
    retried_batch_ids: set[str] = set()
    for draw in draws:
        if draw.batch_id in retried_batch_ids:
            continue
        retried_batch_ids.add(draw.batch_id)
        await _publish_draws(guild, (draw,))
    for redemption in redemptions:
        await _publish_redemption(guild, redemption)


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
        rarity = self.values[0]
        if rarity not in RARITY_ORDER:
            await interaction.response.send_message(
                "レアリティを選び直してください。", ephemeral=True
            )
            return
        typed_rarity = rarity
        if self.choice == "favorite":
            view: discord.ui.View = FavoriteSelectView(
                self.guild_id, self.user_id, self.collection, typed_rarity
            )
            message = "お気に入りにするカードを選んでください。"
        else:
            view = RedemptionSelectView(
                self.guild_id, self.user_id, self.collection, typed_rarity
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


def _exchange_guidance(collection: tuple[service.CollectionCard, ...]) -> str:
    redeemable_total = sum(item.redeemable_count for item in collection)
    if redeemable_total == 0:
        return (
            "交換できる重複カードはまだありません。"
            "同じカードの2枚目以降がXP交換の対象になります。"
        )
    return (
        f"交換可能なカードが合計 **{redeemable_total}枚** あります。"
        "下のボタンから個別交換または全カード一括交換を選べます。"
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
        title=f"🗃️ {interaction.user.display_name} のカード棚",
        description=(
            f"**レアリティ別収集**\n{rarity_progress}\n\n"
            f"**N 所持カード**\n{n_description}"
            if owned
            else "まだカードはありません。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    if favorite is not None:
        embed.add_field(
            name="お気に入りの一枚",
            value=f"{rarity_label(favorite.rarity)}｜{favorite.name}",
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
                f"獲得XP: **{wallet.total_xp:,} XP**\n"
                f"消費済み: **{wallet.spent_xp:,} XP**\n"
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
