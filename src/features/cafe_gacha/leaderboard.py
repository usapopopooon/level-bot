"""カフェ・コレクションの生涯記録を使った10部門ランキング。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import CafeGachaDraw
from src.features.cafe_gacha.catalog import CARD_KEYS_BY_TAG, CARDS_BY_KEY, CafeCardTag
from src.features.cafe_gacha.mastery import mastery_tier
from src.features.cafe_gacha.ports import CafeGachaDependencies
from src.features.cafe_gacha.runtime import default_dependencies
from src.features.cafe_gacha.sets import completed_set_keys

type CafeLeaderboardCategory = Literal[
    "collection",
    "mastery",
    "sets",
    "rare",
    "treasure",
    "joke",
    "coffee",
    "tea",
    "sweets",
    "culture",
]

CAFE_LEADERBOARD_CATEGORIES: tuple[CafeLeaderboardCategory, ...] = (
    "collection",
    "mastery",
    "sets",
    "rare",
    "treasure",
    "joke",
    "coffee",
    "tea",
    "sweets",
    "culture",
)


@dataclass(frozen=True)
class CafeLeaderboardEntry:
    user_id: str
    collection_count: int
    total_draws: int
    mastery_score: int
    discovery_cards: int
    familiar_cards: int
    regular_cards: int
    signature_cards: int
    completed_sets: int
    rare_collection_count: int
    rare_r_count: int
    rare_sr_count: int
    rare_ssr_count: int
    rare_ur_count: int
    rare_mythic_count: int
    treasure_collection_count: int
    n_collection_count: int
    n_mastery_score: int
    n_signature_cards: int
    coffee_collection_count: int = 0
    coffee_mastery_score: int = 0
    coffee_signature_cards: int = 0
    tea_collection_count: int = 0
    tea_mastery_score: int = 0
    tea_signature_cards: int = 0
    sweets_collection_count: int = 0
    sweets_mastery_score: int = 0
    sweets_signature_cards: int = 0
    culture_collection_count: int = 0
    culture_mastery_score: int = 0
    culture_signature_cards: int = 0
    rank: int = 0


@dataclass(frozen=True)
class CafeLeaderboardSnapshot:
    entries: tuple[CafeLeaderboardEntry, ...]


def parse_cafe_leaderboard_category(value: str) -> CafeLeaderboardCategory | None:
    return next(
        (category for category in CAFE_LEADERBOARD_CATEGORIES if value == category),
        None,
    )


def _mastery_score(count: int) -> int:
    tier = mastery_tier(count)
    return tier.minimum_count if tier is not None else 0


def tagged_leaderboard_values(
    entry: CafeLeaderboardEntry,
    category: CafeLeaderboardCategory,
) -> tuple[int, int, int]:
    """専門棚の収集数・熟練ポイント・看板数を返す。"""
    if category == "coffee":
        return (
            entry.coffee_collection_count,
            entry.coffee_mastery_score,
            entry.coffee_signature_cards,
        )
    if category == "tea":
        return (
            entry.tea_collection_count,
            entry.tea_mastery_score,
            entry.tea_signature_cards,
        )
    if category == "sweets":
        return (
            entry.sweets_collection_count,
            entry.sweets_mastery_score,
            entry.sweets_signature_cards,
        )
    if category == "culture":
        return (
            entry.culture_collection_count,
            entry.culture_mastery_score,
            entry.culture_signature_cards,
        )
    raise ValueError(f"{category} is not a tagged leaderboard category")


def _sort_key(
    entry: CafeLeaderboardEntry,
    category: CafeLeaderboardCategory,
) -> tuple[int, ...]:
    if category == "collection":
        return (
            entry.collection_count,
            entry.rare_collection_count,
            entry.completed_sets,
            entry.mastery_score,
            entry.total_draws,
        )
    if category == "mastery":
        return (
            entry.mastery_score,
            entry.collection_count,
            entry.total_draws,
        )
    if category == "sets":
        return (
            entry.completed_sets,
            entry.collection_count,
            entry.mastery_score,
        )
    if category == "rare":
        return (
            entry.rare_collection_count,
            entry.rare_mythic_count,
            entry.rare_ur_count,
            entry.collection_count,
            entry.mastery_score,
        )
    if category == "treasure":
        return (
            entry.treasure_collection_count,
            entry.rare_mythic_count,
            entry.rare_ur_count,
            entry.collection_count,
            entry.mastery_score,
        )
    if category == "joke":
        return (
            entry.n_mastery_score,
            entry.n_collection_count,
            entry.collection_count,
        )
    collection_count, mastery_score, signature_cards = tagged_leaderboard_values(
        entry, category
    )
    return (
        mastery_score,
        signature_cards,
        collection_count,
        entry.mastery_score,
        entry.collection_count,
    )


def rank_cafe_leaderboard(
    snapshot: CafeLeaderboardSnapshot,
    category: CafeLeaderboardCategory,
) -> tuple[CafeLeaderboardEntry, ...]:
    """部門ごとの規則で並べ、同じ評価値には同順位を付ける。"""
    candidates = (
        tuple(
            entry for entry in snapshot.entries if entry.treasure_collection_count > 0
        )
        if category == "treasure"
        else snapshot.entries
    )
    ordered = sorted(
        candidates,
        key=lambda entry: (_sort_key(entry, category), entry.user_id),
        reverse=True,
    )
    ranked: list[CafeLeaderboardEntry] = []
    previous_key: tuple[int, ...] | None = None
    previous_rank = 0
    for index, entry in enumerate(ordered, start=1):
        current_key = _sort_key(entry, category)
        rank = previous_rank if current_key == previous_key else index
        ranked.append(replace(entry, rank=rank))
        previous_key = current_key
        previous_rank = rank
    return tuple(ranked)


async def cafe_leaderboard_snapshot(
    session: AsyncSession,
    *,
    guild_id: str,
    dependencies: CafeGachaDependencies | None = None,
) -> CafeLeaderboardSnapshot:
    """全10部門に必要なユーザー・カード別累計を1度に読み出す。"""
    rows = (
        await session.execute(
            select(
                CafeGachaDraw.user_id,
                CafeGachaDraw.reward_key,
                func.count(CafeGachaDraw.id),
            )
            .where(
                CafeGachaDraw.guild_id == guild_id,
                CafeGachaDraw.reward_key.in_(tuple(CARDS_BY_KEY)),
            )
            .group_by(CafeGachaDraw.user_id, CafeGachaDraw.reward_key)
        )
    ).all()
    blocked = await (
        dependencies or default_dependencies()
    ).leaderboard_audience.blocked_user_ids(session, guild_id=guild_id)
    counts_by_user: dict[str, dict[str, int]] = {}
    for user_id, reward_key, count in rows:
        normalized_user_id = str(user_id)
        normalized_key = str(reward_key)
        if normalized_user_id in blocked:
            continue
        counts_by_user.setdefault(normalized_user_id, {})[normalized_key] = int(count)

    entries: list[CafeLeaderboardEntry] = []
    for user_id, counts in counts_by_user.items():
        tiers = {key: mastery_tier(count) for key, count in counts.items()}
        n_counts = {
            key: count
            for key, count in counts.items()
            if CARDS_BY_KEY[key].rarity == "C"
        }
        rare_keys = {
            key
            for key in counts
            if CARDS_BY_KEY[key].rarity in {"R", "SR", "SSR", "UR", "MYTHIC"}
        }
        treasure_keys = {
            key for key in counts if CARDS_BY_KEY[key].rarity in {"UR", "MYTHIC"}
        }
        tag_stats: dict[CafeCardTag, tuple[int, int, int]] = {}
        for tag, tagged_keys in CARD_KEYS_BY_TAG.items():
            tagged_counts = {
                key: count for key, count in counts.items() if key in tagged_keys
            }
            tag_stats[tag] = (
                len(tagged_counts),
                sum(_mastery_score(count) for count in tagged_counts.values()),
                sum(count >= 25 for count in tagged_counts.values()),
            )
        entries.append(
            CafeLeaderboardEntry(
                user_id=user_id,
                collection_count=len(counts),
                total_draws=sum(counts.values()),
                mastery_score=sum(_mastery_score(count) for count in counts.values()),
                discovery_cards=sum(
                    tier is not None and tier.name == "発見" for tier in tiers.values()
                ),
                familiar_cards=sum(
                    tier is not None and tier.name == "なじみ"
                    for tier in tiers.values()
                ),
                regular_cards=sum(
                    tier is not None and tier.name == "常連" for tier in tiers.values()
                ),
                signature_cards=sum(
                    tier is not None and tier.name == "看板メニュー"
                    for tier in tiers.values()
                ),
                completed_sets=len(completed_set_keys(set(counts))),
                rare_collection_count=len(rare_keys),
                rare_r_count=sum(CARDS_BY_KEY[key].rarity == "R" for key in rare_keys),
                rare_sr_count=sum(
                    CARDS_BY_KEY[key].rarity == "SR" for key in rare_keys
                ),
                rare_ssr_count=sum(
                    CARDS_BY_KEY[key].rarity == "SSR" for key in rare_keys
                ),
                rare_ur_count=sum(
                    CARDS_BY_KEY[key].rarity == "UR" for key in treasure_keys
                ),
                rare_mythic_count=sum(
                    CARDS_BY_KEY[key].rarity == "MYTHIC" for key in treasure_keys
                ),
                treasure_collection_count=len(treasure_keys),
                n_collection_count=len(n_counts),
                n_mastery_score=sum(
                    _mastery_score(count) for count in n_counts.values()
                ),
                n_signature_cards=sum(count >= 25 for count in n_counts.values()),
                coffee_collection_count=tag_stats["coffee"][0],
                coffee_mastery_score=tag_stats["coffee"][1],
                coffee_signature_cards=tag_stats["coffee"][2],
                tea_collection_count=tag_stats["tea"][0],
                tea_mastery_score=tag_stats["tea"][1],
                tea_signature_cards=tag_stats["tea"][2],
                sweets_collection_count=tag_stats["sweets"][0],
                sweets_mastery_score=tag_stats["sweets"][1],
                sweets_signature_cards=tag_stats["sweets"][2],
                culture_collection_count=tag_stats["culture"][0],
                culture_mastery_score=tag_stats["culture"][1],
                culture_signature_cards=tag_stats["culture"][2],
            )
        )
    return CafeLeaderboardSnapshot(entries=tuple(entries))
