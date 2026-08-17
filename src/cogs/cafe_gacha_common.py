"""カフェ・コレクションのDiscord共通設定と実行時ヘルパー。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import discord
from sqlalchemy.exc import SQLAlchemyError

from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.cafe_gacha import service
from src.features.cafe_gacha.catalog import (
    DRAW_REWARD_XP_BY_RARITY,
    EXCHANGE_XP_BY_RARITY,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
    RARITY_ORDER,
    Rarity,
    rarity_label,
)
from src.features.guilds.service import request_level_role_sync
from src.features.leveling.service import earned_total_xp, get_user_lifetime_levels

logger = logging.getLogger(__name__)

ASSET_DIR = Path(__file__).parent.parent / "features" / "cafe_gacha" / "assets"
COUNTER_NAME = "☕️カフェカウンター"
LEDGER_NAME = "📒カフェ台帳"
NOTIFICATION_RETRY_MINUTES = 5.0
PANEL_TITLE = "☕ カフェ・コレクション"
CAFE_COLLECTION_SITE_URL = "https://chill-cafe.site/cafe-collection/"
CAFE_RANKINGS_SITE_URL = f"{CAFE_COLLECTION_SITE_URL}rankings/"
PUBLIC_MENTION_RARITY_RANK = {"R": 0, "SR": 1, "SSR": 2}
DRAW_RARITY_XP_TEXT = " / ".join(
    f"{rarity_label(rarity)} {xp}" for rarity, xp in DRAW_REWARD_XP_BY_RARITY.items()
)
EXCHANGE_RARITY_XP_TEXT = " / ".join(
    f"{rarity_label(rarity)} {xp}" for rarity, xp in EXCHANGE_XP_BY_RARITY.items()
)
MIN_DRAW_REWARD_XP = min(DRAW_REWARD_XP_BY_RARITY.values())
MAX_DRAW_REWARD_XP = max(DRAW_REWARD_XP_BY_RARITY.values())


def _parse_rarity(value: str) -> Rarity | None:
    for rarity in RARITY_ORDER:
        if value == rarity:
            return rarity
    return None


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
            "カードを集めながら、**引くたびXPが必ず増える**コレクションです。\n\n"
            f"**🎟️ 1日1回無料** / 2回目以降 {PAID_DRAW_COST_XP} XP / "
            f"1時間{MAX_HOURLY_DRAWS}回まで / **1日の合計上限なし**\n"
            f"**必ず黒字：{MIN_DRAW_REWARD_XP}〜{MAX_DRAW_REWARD_XP} XP獲得**"
            f"（有料でも +{MIN_DRAW_REWARD_XP - PAID_DRAW_COST_XP} XP以上）\n\n"
            f"**✨ 抽選の獲得XP**　{DRAW_RARITY_XP_TEXT} XP\n"
            f"**♻️ 重複交換XP**　{EXCHANGE_RARITY_XP_TEXT} XP\n"
            "未収集カードは、同じレアリティ内で **2倍** 出やすくなります。\n"
            "最初の1枚は必ず棚に残り、**2枚目以降だけ**交換できます。\n"
            "抽選結果はカフェ台帳に公開されます。\n\n"
            "詳しい排出率・カード解説・セットメニューは、下のWeb図鑑で確認できます。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    if with_image:
        embed.set_image(url="attachment://panel-cabinet.jpg")
    embed.set_footer(text="1日1回の無料分は毎日 0:00に更新")
    return embed
