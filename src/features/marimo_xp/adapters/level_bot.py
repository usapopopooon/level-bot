"""Current in-process adapter for Cafe Collection inventory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.features.cafe_gacha.service import list_collection
from src.features.guilds.service import get_ranking_blocked_user_ids_set
from src.features.marimo_xp.ports import CafeCardBalance, MarimoXpDependencies


class LevelBotCafeCardInventory:
    async def card_balance(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
        user_id: str,
        card_key: str,
    ) -> CafeCardBalance:
        collection = await list_collection(
            session,
            guild_id=guild_id,
            user_id=user_id,
        )
        item = next(item for item in collection if item.card.key == card_key)
        return CafeCardBalance(
            current_count=item.count,
            redeemable_count=item.redeemable_count,
        )


class LevelBotRankingAudience:
    async def blocked_user_ids(
        self,
        session: AsyncSession,
        *,
        guild_id: str,
    ) -> set[str]:
        return await get_ranking_blocked_user_ids_set(session, guild_id)


LEVEL_BOT_DEPENDENCIES = MarimoXpDependencies(
    cafe_card_inventory=LevelBotCafeCardInventory(),
    ranking_audience=LevelBotRankingAudience(),
)
