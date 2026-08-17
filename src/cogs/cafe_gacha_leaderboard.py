"""カフェ・コレクションの公開ランキングパネルと詳細UI。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import discord

from src.cogs.cafe_gacha_common import CAFE_RANKINGS_SITE_URL
from src.cogs.feature_access import ensure_feature_access
from src.constants import DEFAULT_EMBED_COLOR
from src.database.engine import async_session
from src.features.cafe_gacha.catalog import CARDS, CARDS_BY_KEY
from src.features.cafe_gacha.leaderboard import (
    CAFE_LEADERBOARD_CATEGORIES,
    CafeLeaderboardCategory,
    CafeLeaderboardEntry,
    CafeLeaderboardSnapshot,
    cafe_leaderboard_snapshot,
    parse_cafe_leaderboard_category,
    rank_cafe_leaderboard,
)
from src.features.cafe_gacha.sets import SETS
from src.features.feature_access import service as feature_access_service

logger = logging.getLogger(__name__)

LEADERBOARD_PANEL_TITLE = "☕ カフェ・コレクションランキング"
LEADERBOARD_CACHE_SECONDS = 5 * 60.0
LEADERBOARD_PUBLIC_LIMIT = 3
LEADERBOARD_DETAIL_LIMIT = 20
TOKYO = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class CategoryPresentation:
    button_label: str
    emoji: str
    title: str
    explanation: str
    tiebreaker: str


CATEGORY_PRESENTATIONS: dict[CafeLeaderboardCategory, CategoryPresentation] = {
    "collection": CategoryPresentation(
        "図鑑",
        "📚",
        "図鑑ランキング",
        "異なるカードの収集種類数を競います。",
        "同数の場合はレア棚、セット、熟練度の順で決まります。",
    ),
    "mastery": CategoryPresentation(
        "熟練度",
        "☕",
        "熟練度ランキング",
        "各カードの最高熟練度（発見1・なじみ3・常連10・看板25 pt）を合計します。",
        "同点の場合は図鑑収集数、累計抽選数の順で決まります。",
    ),
    "sets": CategoryPresentation(
        "セット",
        "🍽️",
        "セットメニューランキング",
        "完成したセットメニュー数を競います。",
        "同数の場合は図鑑収集数、熟練度の順で決まります。",
    ),
    "rare": CategoryPresentation(
        "レア棚",
        "💎",
        "レア棚ランキング",
        "R・SR・SSRの異なるカード種類数を競います。",
        "同数の場合は図鑑収集数、熟練度の順で決まります。",
    ),
    "joke": CategoryPresentation(
        "ネタ棚",
        "🥖",
        "ネタ棚ランキング",
        "Nカードだけの熟練ポイント（発見1〜看板25 pt）を競います。",
        "同点の場合はN収集数、全図鑑収集数の順で決まります。",
    ),
}


@dataclass(frozen=True)
class CachedCafeLeaderboard:
    snapshot: CafeLeaderboardSnapshot
    captured_at: datetime
    monotonic_at: float


_leaderboard_cache: dict[int, CachedCafeLeaderboard] = {}
_leaderboard_locks: dict[int, asyncio.Lock] = {}


def clear_cafe_leaderboard_cache() -> None:
    """テストと明示的な再読込向けにプロセス内キャッシュを空にする。"""
    _leaderboard_cache.clear()
    _leaderboard_locks.clear()


async def _read_leaderboard_snapshot(guild_id: int) -> CafeLeaderboardSnapshot:
    async with async_session() as session:
        return await cafe_leaderboard_snapshot(session, guild_id=str(guild_id))


async def get_cached_cafe_leaderboard(
    guild_id: int,
    *,
    force: bool = False,
) -> tuple[CachedCafeLeaderboard, bool]:
    """5分以内の同一ギルド集計を再利用し、同時更新も1本へまとめる。"""
    now = monotonic()
    cached = _leaderboard_cache.get(guild_id)
    if (
        not force
        and cached is not None
        and now - cached.monotonic_at < LEADERBOARD_CACHE_SECONDS
    ):
        return cached, False

    lock = _leaderboard_locks.setdefault(guild_id, asyncio.Lock())
    async with lock:
        cached = _leaderboard_cache.get(guild_id)
        if (
            not force
            and cached is not None
            and now - cached.monotonic_at < LEADERBOARD_CACHE_SECONDS
        ):
            return cached, False
        snapshot = await _read_leaderboard_snapshot(guild_id)
        refreshed = CachedCafeLeaderboard(
            snapshot=snapshot,
            captured_at=datetime.now(UTC),
            monotonic_at=now,
        )
        _leaderboard_cache[guild_id] = refreshed
        return refreshed, True


def _rank_prefix(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**#{rank}**")


def _entry_value(
    entry: CafeLeaderboardEntry,
    category: CafeLeaderboardCategory,
) -> str:
    if category == "collection":
        percentage = entry.collection_count / len(CARDS) * 100
        return f"**{entry.collection_count}/{len(CARDS)}種**（{percentage:.1f}%）"
    if category == "mastery":
        return (
            f"**{entry.mastery_score:,} pt**（看板 {entry.signature_cards} / "
            f"常連 {entry.regular_cards} / なじみ {entry.familiar_cards}）"
        )
    if category == "sets":
        return (
            f"**{entry.completed_sets}/{len(SETS)}セット**"
            f"（図鑑 {entry.collection_count}種）"
        )
    if category == "rare":
        rare_total = sum(
            card.rarity in {"R", "SR", "SSR"} for card in CARDS_BY_KEY.values()
        )
        return (
            f"**{entry.rare_collection_count}/{rare_total}種**"
            f"（R {entry.rare_r_count} / SR {entry.rare_sr_count} / "
            f"SSR {entry.rare_ssr_count}）"
        )
    n_total = sum(card.rarity == "C" for card in CARDS_BY_KEY.values())
    return (
        f"**{entry.n_mastery_score:,} pt**"
        f"（N {entry.n_collection_count}/{n_total}種・看板 {entry.n_signature_cards}）"
    )


def _entry_line(
    entry: CafeLeaderboardEntry,
    category: CafeLeaderboardCategory,
) -> str:
    return (
        f"{_rank_prefix(entry.rank)} <@{entry.user_id}> — "
        f"{_entry_value(entry, category)}"
    )


def _updated_footer(cached: CachedCafeLeaderboard) -> str:
    updated = cached.captured_at.astimezone(TOKYO).strftime("%m/%d %H:%M")
    return f"ボタン操作時に更新 · 集計は最大5分間キャッシュ · 最終集計 {updated} JST"


def build_cafe_leaderboard_panel_embed(
    cached: CachedCafeLeaderboard,
) -> discord.Embed:
    embed = discord.Embed(
        title=LEADERBOARD_PANEL_TITLE,
        description=(
            "全5部門のTOP 3を常に表示しています。\n"
            "各ボタンではTOP 20と自分の順位、Web版では全5部門をまとめて確認できます。"
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    for category in CAFE_LEADERBOARD_CATEGORIES:
        presentation = CATEGORY_PRESENTATIONS[category]
        ranked = rank_cafe_leaderboard(cached.snapshot, category)
        lines = [
            _entry_line(entry, category) for entry in ranked[:LEADERBOARD_PUBLIC_LIMIT]
        ]
        embed.add_field(
            name=(
                f"{presentation.emoji} {presentation.button_label} "
                f"TOP {LEADERBOARD_PUBLIC_LIMIT}"
            ),
            value="\n".join(lines) if lines else "まだ抽選記録がありません。",
            inline=False,
        )
    embed.set_footer(text=_updated_footer(cached))
    return embed


def build_cafe_leaderboard_detail_embed(
    cached: CachedCafeLeaderboard,
    *,
    category: CafeLeaderboardCategory,
    viewer_id: str,
) -> discord.Embed:
    presentation = CATEGORY_PRESENTATIONS[category]
    ranked = rank_cafe_leaderboard(cached.snapshot, category)
    lines = [
        _entry_line(entry, category) for entry in ranked[:LEADERBOARD_DETAIL_LIMIT]
    ]
    embed = discord.Embed(
        title=f"{presentation.emoji} {presentation.title}",
        description=(
            f"{presentation.explanation}\n\n"
            + ("\n".join(lines) if lines else "まだ抽選記録がありません。")
        ),
        color=DEFAULT_EMBED_COLOR,
    )
    viewer_entry = next(
        (entry for entry in ranked if entry.user_id == viewer_id),
        None,
    )
    if viewer_entry is None:
        own_rank = "まだ抽選記録がありません。"
    else:
        own_rank = _entry_line(viewer_entry, category)
    embed.add_field(name="あなたの順位", value=own_rank, inline=False)
    embed.set_footer(text=f"{presentation.tiebreaker} · {_updated_footer(cached)}")
    return embed


async def _find_leaderboard_panel_message(
    channel: discord.TextChannel,
) -> discord.Message | None:
    async for message in channel.history(limit=None):
        if not message.author.bot:
            continue
        if LEADERBOARD_PANEL_TITLE in message.content or any(
            embed.title == LEADERBOARD_PANEL_TITLE for embed in message.embeds
        ):
            return message
    return None


async def upsert_cafe_leaderboard_panel(
    counter: discord.TextChannel,
    *,
    guild_id: int,
    panel_message_id: str | None,
) -> discord.Message:
    cached, _ = await get_cached_cafe_leaderboard(guild_id)
    message: discord.Message | None = None
    if panel_message_id is not None:
        with contextlib.suppress(discord.NotFound):
            message = await counter.fetch_message(int(panel_message_id))
    if message is None:
        message = await _find_leaderboard_panel_message(counter)
    embed = build_cafe_leaderboard_panel_embed(cached)
    view = CafeLeaderboardPanelView(guild_id)
    if message is None:
        return await counter.send(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    await message.edit(
        content=None,
        embed=embed,
        view=view,
        suppress=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return message


class DynamicCafeLeaderboardButton(
    discord.ui.DynamicItem[discord.ui.Button[discord.ui.View]],
    template=(
        r"level:cafe:leaderboard:"
        r"(?P<category>collection|mastery|sets|rare|joke):(?P<guild_id>\d+)"
    ),
):
    def __init__(
        self,
        guild_id: int,
        category: CafeLeaderboardCategory,
    ) -> None:
        self.guild_id = guild_id
        self.category = category
        presentation = CATEGORY_PRESENTATIONS[category]
        super().__init__(
            discord.ui.Button(
                label=presentation.button_label,
                emoji=presentation.emoji,
                style=(
                    discord.ButtonStyle.primary
                    if category == "collection"
                    else discord.ButtonStyle.secondary
                ),
                custom_id=f"level:cafe:leaderboard:{category}:{guild_id}",
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        _interaction: discord.Interaction,
        _item: discord.ui.Item[discord.ui.View],
        match: re.Match[str],
    ) -> DynamicCafeLeaderboardButton:
        category = parse_cafe_leaderboard_category(match["category"])
        if category is None:  # pragma: no cover - templateが許可値だけを受け付ける
            raise ValueError("unsupported cafe leaderboard category")
        return cls(int(match["guild_id"]), category)

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "このサーバーでは利用できません。", ephemeral=True
            )
            return
        if not await ensure_feature_access(
            interaction,
            guild_id=self.guild_id,
            feature=feature_access_service.CAFE_GACHA,
        ):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        cached, refreshed = await get_cached_cafe_leaderboard(self.guild_id)
        if refreshed and interaction.message is not None:
            try:
                await interaction.message.edit(
                    embed=build_cafe_leaderboard_panel_embed(cached),
                    view=CafeLeaderboardPanelView(self.guild_id),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.HTTPException:
                logger.exception(
                    "Failed to refresh cafe leaderboard panel for guild %s",
                    self.guild_id,
                )
        await interaction.followup.send(
            embed=build_cafe_leaderboard_detail_embed(
                cached,
                category=self.category,
                viewer_id=str(interaction.user.id),
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class CafeLeaderboardPanelView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        for category in CAFE_LEADERBOARD_CATEGORIES:
            self.add_item(DynamicCafeLeaderboardButton(guild_id, category))
        self.add_item(
            discord.ui.Button(
                label="全ランキングをWebで見る",
                emoji="🌐",
                url=CAFE_RANKINGS_SITE_URL,
                row=1,
            )
        )
