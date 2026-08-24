"""XP contribution API owned by Cafe Collection.

Other features use these functions instead of knowing Cafe Collection table names or
model classes.  A later out-of-process adapter can replace this boundary without
changing wallet and leveling callers.
"""

from __future__ import annotations

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from src.database.models import CafeGachaDraw, CafeGachaRedemption


async def spent_xp_for_user(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> int:
    value = await session.scalar(
        select(func.coalesce(func.sum(CafeGachaDraw.cost_xp), 0)).where(
            CafeGachaDraw.guild_id == guild_id,
            CafeGachaDraw.user_id == user_id,
        )
    )
    return int(value or 0)


async def bonus_xp_for_user(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> int:
    draw_reward = await session.scalar(
        select(func.coalesce(func.sum(CafeGachaDraw.reward_xp), 0)).where(
            CafeGachaDraw.guild_id == guild_id,
            CafeGachaDraw.user_id == user_id,
        )
    )
    redemption_reward = await session.scalar(
        select(func.coalesce(func.sum(CafeGachaRedemption.reward_xp), 0)).where(
            CafeGachaRedemption.guild_id == guild_id,
            CafeGachaRedemption.user_id == user_id,
        )
    )
    return int(draw_reward or 0) + int(redemption_reward or 0)


def bonus_xp_by_user_subquery(guild_id: str) -> Subquery:
    draw_bonus = (
        select(
            CafeGachaDraw.user_id.label("user_id"),
            func.coalesce(func.sum(CafeGachaDraw.reward_xp), 0).label("bonus_xp"),
        )
        .where(CafeGachaDraw.guild_id == guild_id)
        .group_by(CafeGachaDraw.user_id)
        .subquery()
    )
    redemption_bonus = (
        select(
            CafeGachaRedemption.user_id.label("user_id"),
            func.coalesce(func.sum(CafeGachaRedemption.reward_xp), 0).label("bonus_xp"),
        )
        .where(CafeGachaRedemption.guild_id == guild_id)
        .group_by(CafeGachaRedemption.user_id)
        .subquery()
    )
    bonus_rows = union_all(
        select(draw_bonus.c.user_id, draw_bonus.c.bonus_xp),
        select(redemption_bonus.c.user_id, redemption_bonus.c.bonus_xp),
    ).subquery()
    return (
        select(
            bonus_rows.c.user_id,
            func.sum(bonus_rows.c.bonus_xp).label("bonus_xp"),
        )
        .group_by(bonus_rows.c.user_id)
        .subquery()
    )


def spent_xp_by_user_subquery(guild_id: str) -> Subquery:
    return (
        select(
            CafeGachaDraw.user_id.label("user_id"),
            func.coalesce(func.sum(CafeGachaDraw.cost_xp), 0).label("spent_xp"),
        )
        .where(CafeGachaDraw.guild_id == guild_id)
        .group_by(CafeGachaDraw.user_id)
        .subquery()
    )
