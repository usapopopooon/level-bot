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
    ENDGAME_PITY_DUPLICATE_DRAWS,
    ENDGAME_PITY_MIN_COLLECTED,
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
PUBLIC_MENTION_RARITY_RANK = {"R": 0, "SR": 1, "SSR": 2}
RARITY_XP_TEXT = " / ".join(
    f"{rarity_label(rarity)} {xp}" for rarity, xp in DRAW_REWARD_XP_BY_RARITY.items()
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
