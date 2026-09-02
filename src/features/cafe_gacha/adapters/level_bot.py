"""Current in-process adapters for dependencies owned by other level-bot features."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import MarimoItemSpend
from src.features.cafe_gacha.ports import CafeGachaDependencies
from src.features.guilds.service import (
    get_active_guild,
    get_guild_settings,
    get_ranking_blocked_user_ids_set,
)
from src.features.meta.service import get_user_meta_map


class LevelBotExternalCardConsumption:
    async def consumed_card_counts(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
    ) -> dict[str, int]:
        rows = (
            await session.execute(
                select(MarimoItemSpend.card_key, func.sum(MarimoItemSpend.quantity))
                .where(
                    MarimoItemSpend.guild_id == guild_id,
                    MarimoItemSpend.user_id == user_id,
                    MarimoItemSpend.status == "consumed",
                )
                .group_by(MarimoItemSpend.card_key)
            )
        ).all()
        return {str(key): int(count) for key, count in rows}


class LevelBotLeaderboardAudience:
    async def blocked_user_ids(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> set[str]:
        return await get_ranking_blocked_user_ids_set(session, guild_id)


class LevelBotPublicGuildAccess:
    async def is_public_guild(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> bool:
        guild = await get_active_guild(session, guild_id)
        settings = await get_guild_settings(session, guild_id)
        return guild is not None and (settings is None or settings.public)


class LevelBotUserPresentation:
    async def avatar_urls(
        self,
        session: AsyncSession,
        *,
        user_ids: tuple[str, ...],
    ) -> dict[str, str | None]:
        user_metas = await get_user_meta_map(session, list(user_ids))
        return {
            user_id: user_meta.avatar_url for user_id, user_meta in user_metas.items()
        }


LEVEL_BOT_DEPENDENCIES = CafeGachaDependencies(
    external_consumption=LevelBotExternalCardConsumption(),
    leaderboard_audience=LevelBotLeaderboardAudience(),
    public_guild_access=LevelBotPublicGuildAccess(),
    user_presentation=LevelBotUserPresentation(),
)
