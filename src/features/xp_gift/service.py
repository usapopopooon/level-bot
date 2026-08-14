"""XPギフトの税計算、残高移動、日次制約、通知状態を扱う。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import XpGiftGuildConfig, XpGiftTransfer
from src.features.color_role_shop.service import Wallet, lock_wallet, wallet_for_user
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels

TOKYO = ZoneInfo("Asia/Tokyo")
MAX_GIFT_XP = 3_000
MAX_GIFT_MESSAGE_LENGTH = 120
MAX_GIFT_MESSAGE_LINES = 4
TAX_EXEMPT_XP = 1_000
TAX_RATE_PERCENT = 10
NOTIFICATION_RETRY_LIMIT = 5

type GiftStatus = Literal[
    "completed",
    "already_sent",
    "insufficient_xp",
    "conflict",
]


@dataclass(frozen=True)
class GiftResult:
    status: GiftStatus
    transfer: XpGiftTransfer | None
    wallet_before: Wallet
    wallet_after: Wallet
    message: str


@dataclass(frozen=True)
class GiftPreview:
    status: Literal["ready", "already_sent", "insufficient_xp"]
    gift_xp: int
    tax_xp: int
    sender_cost_xp: int
    wallet: Wallet
    day: date


def transfer_day(now: datetime | None = None) -> date:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(TOKYO).date()


def calculate_gift_tax(gift_xp: int) -> int:
    if not 1 <= gift_xp <= MAX_GIFT_XP:
        raise ValueError(f"gift_xp must be between 1 and {MAX_GIFT_XP}")
    taxable_xp = max(0, gift_xp - TAX_EXEMPT_XP)
    return (taxable_xp * TAX_RATE_PERCENT + 99) // 100


def normalize_gift_message(message: str | None) -> str | None:
    """任意メッセージを台帳へ保存できる不変な本文へ正規化する。"""
    if message is None:
        return None
    normalized = message.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    if len(normalized) > MAX_GIFT_MESSAGE_LENGTH:
        raise ValueError(
            f"gift message must not exceed {MAX_GIFT_MESSAGE_LENGTH} characters"
        )
    if len(normalized.split("\n")) > MAX_GIFT_MESSAGE_LINES:
        raise ValueError(f"gift message must not exceed {MAX_GIFT_MESSAGE_LINES} lines")
    if any(
        ord(character) < 32 and character not in {"\n", "\t"}
        for character in normalized
    ):
        raise ValueError("gift message contains unsupported control characters")
    return normalized


async def get_guild_config(
    session: AsyncSession, guild_id: str
) -> XpGiftGuildConfig | None:
    return (
        await session.execute(
            select(XpGiftGuildConfig).where(XpGiftGuildConfig.guild_id == guild_id)
        )
    ).scalar_one_or_none()


async def save_guild_config(
    session: AsyncSession,
    *,
    guild_id: str,
    panel_channel_id: str,
    ledger_channel_id: str,
    panel_message_id: str | None,
) -> XpGiftGuildConfig:
    row = await get_guild_config(session, guild_id)
    if row is None:
        row = XpGiftGuildConfig(
            guild_id=guild_id,
            panel_channel_id=panel_channel_id,
            ledger_channel_id=ledger_channel_id,
            panel_message_id=panel_message_id,
        )
        session.add(row)
    else:
        row.panel_channel_id = panel_channel_id
        row.ledger_channel_id = ledger_channel_id
        row.panel_message_id = panel_message_id
    await session.commit()
    await session.refresh(row)
    return row


async def _lock_wallets(
    session: AsyncSession,
    *,
    guild_id: str,
    user_ids: tuple[str, ...],
) -> None:
    for user_id in sorted(set(user_ids), key=int):
        await lock_wallet(session, guild_id=guild_id, user_id=user_id)


async def wallet_for_xp_gift(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> Wallet:
    levels = await get_user_lifetime_levels(
        session,
        guild_id,
        user_id,
        include_live_voice=True,
    )
    total_xp = earned_total_xp(levels) if levels is not None else 0
    return await wallet_for_user(
        session,
        guild_id=guild_id,
        user_id=user_id,
        total_xp=total_xp,
    )


async def preview_xp_gift(
    session: AsyncSession,
    *,
    guild_id: str,
    sender_user_id: str,
    recipient_user_id: str,
    gift_xp: int,
    now: datetime | None = None,
) -> GiftPreview:
    if sender_user_id == recipient_user_id:
        raise ValueError("cannot gift XP to yourself")
    day = transfer_day(now)
    tax_xp = calculate_gift_tax(gift_xp)
    sender_cost_xp = gift_xp + tax_xp
    wallet = await wallet_for_xp_gift(
        session,
        guild_id=guild_id,
        user_id=sender_user_id,
    )
    already_sent = (
        await session.execute(
            select(XpGiftTransfer.id).where(
                XpGiftTransfer.guild_id == guild_id,
                XpGiftTransfer.sender_user_id == sender_user_id,
                XpGiftTransfer.recipient_user_id == recipient_user_id,
                XpGiftTransfer.transfer_day == day,
            )
        )
    ).first()
    if already_sent is not None:
        status: Literal["ready", "already_sent", "insufficient_xp"] = "already_sent"
    elif wallet.available_xp < sender_cost_xp:
        status = "insufficient_xp"
    else:
        status = "ready"
    return GiftPreview(
        status=status,
        gift_xp=gift_xp,
        tax_xp=tax_xp,
        sender_cost_xp=sender_cost_xp,
        wallet=wallet,
        day=day,
    )


async def create_xp_gift(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: str,
    sender_user_id: str,
    sender_display_name: str,
    recipient_user_id: str,
    recipient_display_name: str,
    gift_xp: int,
    gift_message: str | None = None,
    now: datetime | None = None,
) -> GiftResult:
    if sender_user_id == recipient_user_id:
        raise ValueError("cannot gift XP to yourself")
    day = transfer_day(now)
    normalized_message = normalize_gift_message(gift_message)
    tax_xp = calculate_gift_tax(gift_xp)
    sender_cost_xp = gift_xp + tax_xp
    await _lock_wallets(
        session,
        guild_id=guild_id,
        user_ids=(sender_user_id, recipient_user_id),
    )
    wallet_before = await wallet_for_xp_gift(
        session,
        guild_id=guild_id,
        user_id=sender_user_id,
    )
    existing_event = (
        await session.execute(
            select(XpGiftTransfer).where(XpGiftTransfer.event_id == event_id)
        )
    ).scalar_one_or_none()
    if existing_event is not None:
        same_event = (
            existing_event.guild_id == guild_id
            and existing_event.sender_user_id == sender_user_id
            and existing_event.recipient_user_id == recipient_user_id
            and existing_event.gift_xp == gift_xp
            and existing_event.gift_message == normalized_message
        )
        if not same_event:
            await session.rollback()
            return GiftResult(
                "conflict",
                None,
                wallet_before,
                wallet_before,
                "同じ操作IDが別のXPギフトに使用されています。",
            )
        return GiftResult(
            "completed",
            existing_event,
            wallet_before,
            wallet_before,
            "このXPギフトはすでに完了しています。",
        )
    existing_pair = (
        await session.execute(
            select(XpGiftTransfer).where(
                XpGiftTransfer.guild_id == guild_id,
                XpGiftTransfer.sender_user_id == sender_user_id,
                XpGiftTransfer.recipient_user_id == recipient_user_id,
                XpGiftTransfer.transfer_day == day,
            )
        )
    ).scalar_one_or_none()
    if existing_pair is not None:
        await session.rollback()
        return GiftResult(
            "already_sent",
            None,
            wallet_before,
            wallet_before,
            "本日はすでにこの相手へXPを贈っています。",
        )
    if wallet_before.available_xp < sender_cost_xp:
        await session.rollback()
        return GiftResult(
            "insufficient_xp",
            None,
            wallet_before,
            wallet_before,
            f"XPが {sender_cost_xp - wallet_before.available_xp:,} XP不足しています。",
        )
    row = XpGiftTransfer(
        event_id=event_id,
        guild_id=guild_id,
        sender_user_id=sender_user_id,
        sender_display_name=sender_display_name.strip()[:80] or sender_user_id,
        recipient_user_id=recipient_user_id,
        recipient_display_name=recipient_display_name.strip()[:80] or recipient_user_id,
        gift_message=normalized_message,
        gift_xp=gift_xp,
        tax_xp=tax_xp,
        sender_cost_xp=sender_cost_xp,
        transfer_day=day,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    wallet_after = Wallet(
        total_xp=wallet_before.total_xp,
        spent_xp=wallet_before.spent_xp + sender_cost_xp,
    )
    return GiftResult(
        "completed",
        row,
        wallet_before,
        wallet_after,
        f"{recipient_display_name}さんへ {gift_xp:,} XPを贈りました。",
    )


async def list_user_transfers(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    limit: int = 10,
) -> tuple[XpGiftTransfer, ...]:
    rows = (
        (
            await session.execute(
                select(XpGiftTransfer)
                .where(
                    XpGiftTransfer.guild_id == guild_id,
                    or_(
                        XpGiftTransfer.sender_user_id == user_id,
                        XpGiftTransfer.recipient_user_id == user_id,
                    ),
                )
                .order_by(XpGiftTransfer.created_at.desc(), XpGiftTransfer.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def list_pending_notifications(
    session: AsyncSession,
    *,
    guild_id: str,
) -> tuple[XpGiftTransfer, ...]:
    rows = (
        (
            await session.execute(
                select(XpGiftTransfer)
                .where(
                    XpGiftTransfer.guild_id == guild_id,
                    XpGiftTransfer.ledger_message_id.is_(None),
                    XpGiftTransfer.notification_attempts < NOTIFICATION_RETRY_LIMIT,
                )
                .order_by(XpGiftTransfer.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return tuple(rows)


async def rearm_failed_notifications(
    session: AsyncSession,
    *,
    guild_id: str,
) -> tuple[int, ...]:
    """上限で停止した未配信通知だけを、管理者操作で再試行可能に戻す。"""
    rows = tuple(
        (
            await session.execute(
                select(XpGiftTransfer)
                .where(
                    XpGiftTransfer.guild_id == guild_id,
                    XpGiftTransfer.ledger_message_id.is_(None),
                    XpGiftTransfer.notification_attempts >= NOTIFICATION_RETRY_LIMIT,
                )
                .order_by(XpGiftTransfer.id.asc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    rearmed_ids = tuple(row.id for row in rows)
    for row in rows:
        row.notification_attempts = 0
    await session.commit()
    return rearmed_ids
