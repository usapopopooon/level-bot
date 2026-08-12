"""機能別の利用ロールを保存し、利用可否を判定する。"""

from __future__ import annotations

from typing import Literal, TypeGuard

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import FeatureAccessRole

type FeatureKey = Literal["cafe_gacha", "color_role_shop"]

CAFE_GACHA: FeatureKey = "cafe_gacha"
COLOR_ROLE_SHOP: FeatureKey = "color_role_shop"
FEATURE_KEYS = frozenset((CAFE_GACHA, COLOR_ROLE_SHOP))


def _is_feature_key(feature: str) -> TypeGuard[FeatureKey]:
    return feature in FEATURE_KEYS


def _validate_feature(feature: str) -> FeatureKey:
    if not _is_feature_key(feature):
        msg = f"unsupported feature: {feature!r}"
        raise ValueError(msg)
    return feature


def member_has_access(
    *,
    allowed_role_ids: tuple[str, ...],
    member_role_ids: set[str],
    can_manage_guild: bool,
) -> bool:
    """未設定・管理者・許可ロールのいずれかなら利用を許可する。"""
    return (
        not allowed_role_ids
        or can_manage_guild
        or not member_role_ids.isdisjoint(allowed_role_ids)
    )


async def list_access_role_ids(
    session: AsyncSession,
    *,
    guild_id: str,
    feature: FeatureKey,
) -> tuple[str, ...]:
    feature = _validate_feature(feature)
    rows = await session.execute(
        select(FeatureAccessRole.role_id)
        .where(
            FeatureAccessRole.guild_id == guild_id,
            FeatureAccessRole.feature == feature,
        )
        .order_by(FeatureAccessRole.id.asc())
    )
    return tuple(rows.scalars().all())


async def add_access_role(
    session: AsyncSession,
    *,
    guild_id: str,
    feature: FeatureKey,
    role_id: str,
) -> bool:
    """利用ロールを重複なく追加し、新規追加なら True を返す。"""
    feature = _validate_feature(feature)
    result = await session.execute(
        insert(FeatureAccessRole)
        .values(guild_id=guild_id, feature=feature, role_id=role_id)
        .on_conflict_do_nothing(index_elements=["guild_id", "feature", "role_id"])
    )
    await session.commit()
    return bool(getattr(result, "rowcount", 0))


async def remove_access_role(
    session: AsyncSession,
    *,
    guild_id: str,
    feature: FeatureKey,
    role_id: str,
) -> bool:
    """利用ロールを削除し、対象が存在した場合は True を返す。"""
    feature = _validate_feature(feature)
    result = await session.execute(
        delete(FeatureAccessRole).where(
            FeatureAccessRole.guild_id == guild_id,
            FeatureAccessRole.feature == feature,
            FeatureAccessRole.role_id == role_id,
        )
    )
    await session.commit()
    return bool(getattr(result, "rowcount", 0))
