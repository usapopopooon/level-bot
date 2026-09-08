"""Cafe Collection の公開プロフィール識別子と公開可否。"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings as app_settings
from src.database.models import CafeGachaDraw
from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.runtime import default_dependencies


def public_cafe_profile_id(*, guild_id: str, user_id: str) -> str:
    """Discord IDを直接公開せず、安定した公開ページ識別子へ変換する。"""
    value = f"cafe-profile-v1:{guild_id}:{user_id}".encode()
    return hashlib.sha256(value).hexdigest()[:24]


async def available_public_cafe_profile_id(
    session: AsyncSession,
    *,
    guild_id: str,
    user_id: str,
) -> str | None:
    """公開プロフィールが存在する参加者にだけ、その識別子を返す。"""
    configured_guild_id = app_settings.user_stats_site_guild_id.strip()
    if not configured_guild_id or guild_id != configured_guild_id:
        return None

    draw_id = await session.scalar(
        select(CafeGachaDraw.id)
        .where(
            CafeGachaDraw.guild_id == guild_id,
            CafeGachaDraw.user_id == user_id,
            CafeGachaDraw.reward_key.in_(tuple(CARDS_BY_KEY)),
        )
        .limit(1)
    )
    if draw_id is None:
        return None

    dependencies = default_dependencies()
    if not await dependencies.public_guild_access.is_public_guild(
        session, guild_id=guild_id
    ):
        return None

    blocked_user_ids = await dependencies.leaderboard_audience.blocked_user_ids(
        session, guild_id=guild_id
    )
    if user_id in blocked_user_ids:
        return None

    return public_cafe_profile_id(guild_id=guild_id, user_id=user_id)
