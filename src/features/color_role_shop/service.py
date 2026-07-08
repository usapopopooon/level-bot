"""XP を消費して Discord のカラーロールを交換する feature service。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ColorRoleExchange, ColorRoleShopItem, RoleMeta

logger = logging.getLogger(__name__)

MAX_COLOR_ROLE_SELECT_OPTIONS = 25
MIN_COLOR_ROLE_COST_XP = 1
PANEL_ITEM_PREVIEW_LIMIT = 10

type ColorRoleExchangeStatus = Literal[
    "purchased",
    "insufficient_xp",
    "unavailable",
    "role_update_failed",
    "exchange_record_failed",
]
type RoleMutator = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class ColorRoleItemView:
    """UI に表示するカラーロール交換対象。"""

    id: int
    guild_id: str
    role_id: str
    label: str
    description: str | None
    cost_xp: int
    color: int = 0


@dataclass(frozen=True)
class Wallet:
    """ユーザーの累計 XP と交換用残高。"""

    total_xp: int
    spent_xp: int

    @property
    def available_xp(self) -> int:
        return max(0, self.total_xp - self.spent_xp)


@dataclass(frozen=True)
class ColorRoleExchangeResult:
    """カラーロール交換操作の結果。成功した交換は必ず消費済み台帳に残る。"""

    status: ColorRoleExchangeStatus
    item: ColorRoleItemView | None
    wallet_before: Wallet
    wallet_after: Wallet
    message: str


def _to_view(row: ColorRoleShopItem, *, color: int | None = None) -> ColorRoleItemView:
    return ColorRoleItemView(
        id=row.id,
        guild_id=row.guild_id,
        role_id=row.role_id,
        label=row.label,
        description=row.description,
        cost_xp=row.cost_xp,
        color=int(color or 0),
    )


async def upsert_color_role_item(
    session: AsyncSession,
    *,
    guild_id: str,
    role_id: str,
    label: str,
    cost_xp: int,
    description: str | None,
    role_color: int = 0,
) -> ColorRoleItemView:
    """管理者が交換対象ロールを追加または更新する。"""
    if cost_xp < MIN_COLOR_ROLE_COST_XP:
        msg = f"cost_xp must be greater than or equal to {MIN_COLOR_ROLE_COST_XP}"
        raise ValueError(msg)

    normalized_label = label.strip()[:80]
    normalized_description = (
        description.strip()[:160] if description and description.strip() else None
    )
    stmt = select(ColorRoleShopItem).where(
        and_(
            ColorRoleShopItem.guild_id == guild_id, ColorRoleShopItem.role_id == role_id
        )
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = ColorRoleShopItem(
            guild_id=guild_id,
            role_id=role_id,
            label=normalized_label,
            description=normalized_description,
            cost_xp=cost_xp,
            enabled=True,
        )
        session.add(row)
    else:
        row.label = normalized_label
        row.description = normalized_description
        row.cost_xp = cost_xp
        row.enabled = True
    await session.commit()
    await session.refresh(row)
    return _to_view(row, color=role_color)


async def disable_color_role_item(
    session: AsyncSession,
    *,
    guild_id: str,
    role_id: str,
) -> bool:
    """カラーロール交換対象を無効化する。交換履歴は残す。"""
    row = (
        await session.execute(
            select(ColorRoleShopItem).where(
                and_(
                    ColorRoleShopItem.guild_id == guild_id,
                    ColorRoleShopItem.role_id == role_id,
                    ColorRoleShopItem.enabled.is_(True),
                )
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    row.enabled = False
    row.updated_at = datetime.now(UTC)
    await session.commit()
    return True


async def list_enabled_color_role_items(
    session: AsyncSession,
    guild_id: str,
    *,
    limit: int | None = None,
) -> tuple[ColorRoleItemView, ...]:
    """公開パネルや選択メニューに表示する有効なカラーロールを返す。"""
    stmt = (
        select(ColorRoleShopItem, RoleMeta.color)
        .outerjoin(
            RoleMeta,
            and_(
                RoleMeta.guild_id == ColorRoleShopItem.guild_id,
                RoleMeta.role_id == ColorRoleShopItem.role_id,
            ),
        )
        .where(
            and_(
                ColorRoleShopItem.guild_id == guild_id,
                ColorRoleShopItem.enabled.is_(True),
            )
        )
        .order_by(
            ColorRoleShopItem.sort_order.asc(),
            ColorRoleShopItem.cost_xp.asc(),
            ColorRoleShopItem.id.asc(),
        )
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()
    return tuple(_to_view(item, color=role_color) for item, role_color in rows)


async def list_color_role_ids_for_guild(
    session: AsyncSession,
    guild_id: str,
) -> tuple[str, ...]:
    """ユーザーから外す候補として、登録済みカラーロール ID を返す。

    無効化済みの交換対象も、過去に付与されたまま残っている可能性があるため含める。
    """
    rows = (
        await session.execute(
            select(ColorRoleShopItem.role_id)
            .where(ColorRoleShopItem.guild_id == guild_id)
            .order_by(
                ColorRoleShopItem.sort_order.asc(),
                ColorRoleShopItem.cost_xp.asc(),
                ColorRoleShopItem.id.asc(),
            )
        )
    ).scalars()
    return tuple(str(role_id) for role_id in rows.all())


async def spent_xp_for_user(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> int:
    """成功済みのカラーロール交換から消費済み XP を集計する。"""
    spent = (
        await session.execute(
            select(func.coalesce(func.sum(ColorRoleExchange.cost_xp), 0)).where(
                and_(
                    ColorRoleExchange.guild_id == guild_id,
                    ColorRoleExchange.user_id == user_id,
                )
            )
        )
    ).scalar_one()
    return int(spent)


async def wallet_for_user(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    total_xp: int,
) -> Wallet:
    """累計 XP とカラーロール交換台帳から交換可能 XP を作る。"""
    return Wallet(
        total_xp=max(0, total_xp),
        spent_xp=await spent_xp_for_user(
            session,
            guild_id=guild_id,
            user_id=user_id,
        ),
    )


async def _lock_wallet(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> None:
    """同一ユーザーのカラーロール交換処理を直列化する。"""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:wallet_key))"),
        {"wallet_key": f"color-role-shop:{guild_id}:{user_id}"},
    )


async def _exchange_role_ids_to_remove(
    session: AsyncSession,
    *,
    guild_id: str,
    selected_role_id: str,
) -> tuple[str, ...]:
    """選択したロール以外の交換対象ロールを外す候補として返す。"""
    rows = (
        await session.execute(
            select(ColorRoleShopItem.role_id).where(
                and_(
                    ColorRoleShopItem.guild_id == guild_id,
                    ColorRoleShopItem.role_id != selected_role_id,
                )
            )
        )
    ).scalars()
    return tuple(str(role_id) for role_id in rows.all())


async def _rollback_role_changes(
    *,
    grant_role: RoleMutator,
    remove_role: RoleMutator,
    selected_role_id: str,
    selected_role_granted: bool,
    removed_role_ids: list[str],
    item_id: int,
) -> None:
    """外部APIの途中失敗後に、可能な範囲でロール状態を交換前へ戻す。"""
    if selected_role_granted:
        try:
            await remove_role(
                selected_role_id, f"color role shop rollback item={item_id}"
            )
        except Exception:
            logger.exception(
                "Failed to rollback selected color role: %s", selected_role_id
            )

    for role_id in reversed(removed_role_ids):
        try:
            await grant_role(role_id, f"color role shop rollback item={item_id}")
        except Exception:
            logger.exception("Failed to restore previous color role: %s", role_id)


async def exchange_color_role(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
    item_id: int,
    total_xp: int,
    grant_role: RoleMutator,
    remove_role: RoleMutator,
) -> ColorRoleExchangeResult:
    """XP 残高を確認し、ロール変更と交換台帳記録を 1 操作として扱う。"""
    await _lock_wallet(session, guild_id=guild_id, user_id=user_id)
    wallet_before = await wallet_for_user(
        session,
        guild_id=guild_id,
        user_id=user_id,
        total_xp=total_xp,
    )
    row = (
        await session.execute(
            select(ColorRoleShopItem).where(
                and_(
                    ColorRoleShopItem.id == item_id,
                    ColorRoleShopItem.guild_id == guild_id,
                    ColorRoleShopItem.enabled.is_(True),
                )
            )
        )
    ).scalar_one_or_none()
    if row is None:
        await session.rollback()
        return ColorRoleExchangeResult(
            status="unavailable",
            item=None,
            wallet_before=wallet_before,
            wallet_after=wallet_before,
            message="このロールは現在交換できません。",
        )

    item = _to_view(row)
    if wallet_before.available_xp < item.cost_xp:
        await session.rollback()
        shortage = item.cost_xp - wallet_before.available_xp
        return ColorRoleExchangeResult(
            status="insufficient_xp",
            item=item,
            wallet_before=wallet_before,
            wallet_after=wallet_before,
            message=(
                f"XP が {shortage:,} 不足しています。"
                f"現在の交換可能XPは {wallet_before.available_xp:,} XP です。"
            ),
        )

    role_ids_to_remove = await _exchange_role_ids_to_remove(
        session,
        guild_id=guild_id,
        selected_role_id=item.role_id,
    )
    removed_role_ids: list[str] = []
    selected_role_granted = False
    try:
        for role_id in role_ids_to_remove:
            await remove_role(role_id, f"color role shop exchange item={item.id}")
            removed_role_ids.append(role_id)
        await grant_role(item.role_id, f"color role shop item={item.id}")
        selected_role_granted = True
    except Exception:
        await session.rollback()
        await _rollback_role_changes(
            grant_role=grant_role,
            remove_role=remove_role,
            selected_role_id=item.role_id,
            selected_role_granted=selected_role_granted,
            removed_role_ids=removed_role_ids,
            item_id=item.id,
        )
        return ColorRoleExchangeResult(
            status="role_update_failed",
            item=item,
            wallet_before=wallet_before,
            wallet_after=wallet_before,
            message=(
                "ロール変更に失敗しました。Bot のロール位置と権限を確認してください。"
            ),
        )

    session.add(
        ColorRoleExchange(
            guild_id=guild_id,
            user_id=user_id,
            item_id=item.id,
            role_id=item.role_id,
            cost_xp=item.cost_xp,
        )
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        await _rollback_role_changes(
            grant_role=grant_role,
            remove_role=remove_role,
            selected_role_id=item.role_id,
            selected_role_granted=selected_role_granted,
            removed_role_ids=removed_role_ids,
            item_id=item.id,
        )
        return ColorRoleExchangeResult(
            status="exchange_record_failed",
            item=item,
            wallet_before=wallet_before,
            wallet_after=wallet_before,
            message=(
                "交換台帳の記録に失敗しました。"
                "XP は消費していません。ロール状態を確認してください。"
            ),
        )

    wallet_after = Wallet(
        total_xp=wallet_before.total_xp,
        spent_xp=wallet_before.spent_xp + item.cost_xp,
    )
    return ColorRoleExchangeResult(
        status="purchased",
        item=item,
        wallet_before=wallet_before,
        wallet_after=wallet_after,
        message=(
            f"{item.label} を {item.cost_xp:,} XP で交換しました。"
            f"残り {wallet_after.available_xp:,} XP です。"
            "他の交換ロールがある場合は外しました。"
        ),
    )
