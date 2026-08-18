"""カフェ・コレクションの公開台帳通知と再送処理。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta

import discord
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.cogs.cafe_gacha_common import (
    ASSET_DIR,
    CAFE_COLLECTION_SITE_URL,
    PANEL_TITLE,
    PUBLIC_MENTION_RARITY_RANK,
)
from src.database.engine import async_session
from src.database.models import (
    CafeGachaDraw,
    CafeGachaRedemption,
    CafeGachaRedemptionItem,
)
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import CARDS, RARITY_ORDER, rarity_label

logger = logging.getLogger(__name__)


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
    batch_slot: int | None = None,
) -> discord.Embed:
    colors = {
        "C": 0x8B7D6B,
        "UC": 0x5FA36A,
        "R": 0x4C83C3,
        "SR": 0xA659C5,
        "SSR": 0xD6A72C,
        "UR": 0xA8325A,
        "MYTHIC": 0x62469B,
    }
    is_new = not draw.was_duplicate
    collection_state = " · 重複" if draw.was_duplicate else ""
    cost = "無料" if draw.draw_type == "free" else f"{draw.cost_xp:,} XP消費"
    net_xp = draw.reward_xp - draw.cost_xp
    exchange_bonus = (
        f"\n♻️ 重複カードは交換すると **さらに +{draw.exchange_xp:,} XP！**"
        if draw.was_duplicate
        else ""
    )
    card_url = f"{CAFE_COLLECTION_SITE_URL}cards/{draw.reward_key}/"
    if batch_slot is not None:
        card_url = f"{card_url}?batch_slot={batch_slot}"
    embed = discord.Embed(
        title=f"{rarity_label(draw.rarity)}｜{draw.reward_name}",
        url=card_url,
        description=(
            f"**<@{draw.user_id}> さんが一枚引きました**\n\n{draw.reward_description}"
        ),
        color=colors[draw.rarity],
    )
    embed.add_field(
        name=f"🎉 +{net_xp:,} XPの黒字！",
        value=f"{cost} → {draw.reward_xp:,} XP獲得{collection_state}{exchange_bonus}",
        inline=False,
    )
    collection_progress = (
        f"収集 **{max(0, collected_count - 1)} → {collected_count}/{len(CARDS)}種**"
        if is_new
        else f"収集 {collected_count}/{len(CARDS)}種"
    )
    embed.add_field(
        name="📚 コレクション",
        value=(
            f"所持 {owned_count}枚 · 交換可能 {max(0, owned_count - 1)}枚\n"
            f"{collection_progress}"
        ),
        inline=False,
    )
    if with_image:
        embed.set_image(
            url=f"attachment://{attachment_filename or draw.image_filename}"
        )
    if draw.rarity == "MYTHIC":
        embed.set_footer(text="🔮 存在しないはずの秘宝がカフェに現れました")
    elif draw.rarity == "UR":
        embed.set_footer(text="📜 歴史に残る一品がカフェに並びました")
    elif draw.rarity in ("SR", "SSR"):
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


def _safe_card_name(name: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(name))


def _draw_mention_content(
    draws: tuple[CafeGachaDraw, ...],
) -> str | None:
    if not draws:
        return None
    user_id = draws[0].user_id
    if any(draw.user_id != user_id for draw in draws):
        logger.error("Cafe gacha batch contains draws for multiple users")
        return None

    mentioned_rarities = [
        draw.rarity for draw in draws if draw.rarity in PUBLIC_MENTION_RARITY_RANK
    ]
    new_draws = tuple(draw for draw in draws if not draw.was_duplicate)
    if not mentioned_rarities and not new_draws:
        return None

    lines: list[str] = []
    if mentioned_rarities:
        highest_rarity = max(
            mentioned_rarities,
            key=PUBLIC_MENTION_RARITY_RANK.__getitem__,
        )
        lines.append(
            f"🎉 <@{user_id}>さん、"
            + (
                "幻のカードを獲得しました！"
                if highest_rarity == "MYTHIC"
                else f"{rarity_label(highest_rarity)}以上のカードを獲得しました！"
            )
        )
    elif len(new_draws) == 1:
        lines.append(f"✨ <@{user_id}>さん、新しいカードを獲得しました！")
    else:
        lines.append(
            f"✨ <@{user_id}>さん、コレクションに新しいカードが "
            f"**{len(new_draws)}枚** 加わりました！"
        )

    if new_draws:
        new_names = "／".join(_safe_card_name(draw.reward_name) for draw in new_draws)
        if len(new_draws) == 1:
            prefix = "✨" if mentioned_rarities else "📚"
            lines.append(f"{prefix} **{new_names}**がコレクションに加わりました！")
        else:
            if mentioned_rarities:
                lines.append(
                    f"✨ コレクションに新しいカードが **{len(new_draws)}枚** "
                    "加わりました！"
                )
            lines.append(f"📚 **{new_names}**")
    return "\n".join(lines)


def _highest_rarity(draws: tuple[CafeGachaDraw, ...]) -> str:
    return max(
        (draw.rarity for draw in draws),
        key=lambda rarity: RARITY_ORDER.index(rarity),
    )


def _batch_summary_content(draws: tuple[CafeGachaDraw, ...]) -> str:
    total_cost = sum(draw.cost_xp for draw in draws)
    total_reward = sum(draw.reward_xp for draw in draws)
    return (
        f"☕ **{len(draws)}枚まとめ引き**｜最高 "
        f"**{rarity_label(_highest_rarity(draws))}**\n"
        f"{total_cost:,} XP消費 → {total_reward:,} XP獲得 "
        f"（差引 **+{total_reward - total_cost:,} XP**）"
    )


async def _publish_draw_mention(
    ledger: discord.TextChannel,
    draws: tuple[CafeGachaDraw, ...],
) -> bool:
    content = _draw_mention_content(draws)
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
        logger.exception("Failed to publish cafe gacha draw mention")
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
                                    batch_slot=row.batch_position,
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
                mention_published = await _publish_draw_mention(ledger, rows)
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
