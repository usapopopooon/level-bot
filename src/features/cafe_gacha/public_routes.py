"""chill-cafe.site向けの認証不要・読み取り専用API。"""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings as app_settings
from src.database.models import CafeGachaDraw
from src.features.cafe_gacha import service as cafe_service
from src.features.cafe_gacha.catalog import (
    CARD_TAGS_BY_KEY,
    CARDS,
    ENDGAME_PITY_DUPLICATE_DRAWS,
    ENDGAME_PITY_MIN_COLLECTED,
    FOOD_CARD_KEYS,
    MAX_HOURLY_DRAWS,
    PAID_DRAW_COST_XP,
    RARITY_TOTAL_WEIGHTS,
    TOTAL_WEIGHT,
    UNOWNED_WEIGHT_MULTIPLIER,
    rarity_label,
)
from src.features.cafe_gacha.integration import (
    PUBLIC_CAFE_API_PREFIX as PUBLIC_CAFE_API_PREFIX,
)
from src.features.cafe_gacha.leaderboard import (
    CAFE_LEADERBOARD_CATEGORIES,
    CafeLeaderboardEntry,
    cafe_leaderboard_snapshot,
    rank_cafe_leaderboard,
)
from src.features.cafe_gacha.mastery import MASTERY_TIERS
from src.features.cafe_gacha.runtime import default_dependencies
from src.features.cafe_gacha.schemas import (
    CafeCatalogCardOut,
    CafeCatalogOut,
    CafeCatalogRulesOut,
    CafeCatalogSetOut,
    CafeCollectionProfileCardOut,
    CafeCollectionProfileOut,
    CafeLeaderboardCategoryOut,
    CafeLeaderboardEntryOut,
    CafeLeaderboardsOut,
    CafeMasteryTierOut,
)
from src.features.cafe_gacha.sets import SETS, completed_set_keys
from src.web.deps import get_db

PUBLIC_LEADERBOARD_LIMIT = 20
PUBLIC_LEADERBOARD_CACHE_SECONDS = 5 * 60.0
ASSET_DIR = Path(__file__).parent / "assets"
ASSET_VERSION = hashlib.sha256((ASSET_DIR / "manifest.json").read_bytes()).hexdigest()[
    :16
]

router = APIRouter(prefix=PUBLIC_CAFE_API_PREFIX, tags=["public-cafe-collection"])


@dataclass(frozen=True)
class _CachedLeaderboards:
    value: CafeLeaderboardsOut
    monotonic_at: float


@dataclass(frozen=True)
class _CachedProfile:
    value: CafeCollectionProfileOut
    monotonic_at: float


_leaderboard_cache: dict[str, _CachedLeaderboards] = {}
_leaderboard_locks: dict[str, asyncio.Lock] = {}
_profile_cache: dict[tuple[str, str], _CachedProfile] = {}


def clear_public_cafe_leaderboard_cache() -> None:
    """テストと明示的な再読込向けに公開ランキングキャッシュを空にする。"""
    _leaderboard_cache.clear()
    _leaderboard_locks.clear()
    _profile_cache.clear()


def _catalog() -> CafeCatalogOut:
    rarity_counts = Counter(rarity_label(card.rarity) for card in CARDS)
    rarity_rates = {
        rarity_label(rarity): weight / TOTAL_WEIGHT * 100
        for rarity, weight in RARITY_TOTAL_WEIGHTS.items()
    }
    return CafeCatalogOut(
        total_cards=len(CARDS),
        food_cards=len(FOOD_CARD_KEYS),
        rarity_counts=dict(rarity_counts),
        rarity_rates_percent=rarity_rates,
        cards=[
            CafeCatalogCardOut(
                key=card.key,
                name=card.name,
                rarity=rarity_label(card.rarity),
                description=card.description,
                image_url=(
                    f"{PUBLIC_CAFE_API_PREFIX}/cards/{card.key}/image?v={ASSET_VERSION}"
                ),
                base_draw_rate_percent=card.weight / TOTAL_WEIGHT * 100,
                draw_reward_xp=card.draw_reward_xp,
                exchange_xp=card.exchange_xp,
                is_food=card.key in FOOD_CARD_KEYS,
                tags=sorted(CARD_TAGS_BY_KEY[card.key]),
            )
            for card in CARDS
        ],
        sets=[
            CafeCatalogSetOut(
                key=item.key,
                name=item.name,
                description=item.description,
                required_card_keys=list(item.required_keys),
            )
            for item in SETS
        ],
        mastery_tiers=[
            CafeMasteryTierOut(
                minimum_count=tier.minimum_count,
                name=tier.name,
                emoji=tier.emoji,
            )
            for tier in MASTERY_TIERS
        ],
        rules=CafeCatalogRulesOut(
            free_draws_per_day=1,
            free_draw_reset_timezone="Asia/Tokyo",
            paid_draw_cost_xp=PAID_DRAW_COST_XP,
            hourly_draw_limit=MAX_HOURLY_DRAWS,
            daily_draw_limit=None,
            unowned_weight_multiplier=UNOWNED_WEIGHT_MULTIPLIER,
            endgame_pity_min_collected=ENDGAME_PITY_MIN_COLLECTED,
            endgame_pity_duplicate_draws=ENDGAME_PITY_DUPLICATE_DRAWS,
            first_copy_protected=True,
            draw_results_public=True,
        ),
    )


CATALOG_RESPONSE = _catalog()


async def _require_public_guild(session: AsyncSession, guild_id: str) -> None:
    configured_guild_id = app_settings.user_stats_site_guild_id.strip()
    if not configured_guild_id or guild_id != configured_guild_id:
        raise HTTPException(status_code=404, detail="Guild not found")
    if not await default_dependencies().public_guild_access.is_public_guild(
        session,
        guild_id=guild_id,
    ):
        raise HTTPException(status_code=404, detail="Guild not found")


def _entry_out(
    entry: CafeLeaderboardEntry,
    *,
    guild_id: str,
    display_name: str,
    avatar_url: str | None,
) -> CafeLeaderboardEntryOut:
    return CafeLeaderboardEntryOut(
        rank=entry.rank,
        profile_id=_public_profile_id(guild_id=guild_id, user_id=entry.user_id),
        display_name=display_name,
        avatar_url=avatar_url,
        collection_count=entry.collection_count,
        total_draws=entry.total_draws,
        mastery_score=entry.mastery_score,
        discovery_cards=entry.discovery_cards,
        familiar_cards=entry.familiar_cards,
        regular_cards=entry.regular_cards,
        signature_cards=entry.signature_cards,
        completed_sets=entry.completed_sets,
        rare_collection_count=entry.rare_collection_count,
        rare_r_count=entry.rare_r_count,
        rare_sr_count=entry.rare_sr_count,
        rare_ssr_count=entry.rare_ssr_count,
        rare_ur_count=entry.rare_ur_count,
        rare_mythic_count=entry.rare_mythic_count,
        treasure_collection_count=entry.treasure_collection_count,
        n_collection_count=entry.n_collection_count,
        n_mastery_score=entry.n_mastery_score,
        n_signature_cards=entry.n_signature_cards,
        coffee_collection_count=entry.coffee_collection_count,
        coffee_mastery_score=entry.coffee_mastery_score,
        coffee_signature_cards=entry.coffee_signature_cards,
        tea_collection_count=entry.tea_collection_count,
        tea_mastery_score=entry.tea_mastery_score,
        tea_signature_cards=entry.tea_signature_cards,
        sweets_collection_count=entry.sweets_collection_count,
        sweets_mastery_score=entry.sweets_mastery_score,
        sweets_signature_cards=entry.sweets_signature_cards,
        culture_collection_count=entry.culture_collection_count,
        culture_mastery_score=entry.culture_mastery_score,
        culture_signature_cards=entry.culture_signature_cards,
    )


def _public_profile_id(*, guild_id: str, user_id: str) -> str:
    """Discord IDを直接公開せず、安定した公開ページ識別子へ変換する。"""
    value = f"cafe-profile-v1:{guild_id}:{user_id}".encode()
    return hashlib.sha256(value).hexdigest()[:24]


async def _build_profile(
    session: AsyncSession,
    *,
    guild_id: str,
    profile_id: str,
) -> CafeCollectionProfileOut | None:
    dependencies = default_dependencies()
    snapshot = await cafe_leaderboard_snapshot(
        session,
        guild_id=guild_id,
        dependencies=dependencies,
    )
    entry = next(
        (
            item
            for item in snapshot.entries
            if _public_profile_id(guild_id=guild_id, user_id=item.user_id) == profile_id
        ),
        None,
    )
    if entry is None:
        return None

    collection = await cafe_service.list_collection(
        session,
        guild_id=guild_id,
        user_id=entry.user_id,
        dependencies=dependencies,
    )
    latest_display_name = await session.scalar(
        select(CafeGachaDraw.display_name)
        .where(
            CafeGachaDraw.guild_id == guild_id,
            CafeGachaDraw.user_id == entry.user_id,
        )
        .order_by(CafeGachaDraw.created_at.desc(), CafeGachaDraw.id.desc())
        .limit(1)
    )
    avatar_urls = await dependencies.user_presentation.avatar_urls(
        session,
        user_ids=(entry.user_id,),
    )
    ranks: dict[str, int] = {}
    for category in CAFE_LEADERBOARD_CATEGORIES:
        own_entry = next(
            (
                ranked
                for ranked in rank_cafe_leaderboard(snapshot, category)
                if ranked.user_id == entry.user_id
            ),
            None,
        )
        if own_entry is not None:
            ranks[category] = own_entry.rank

    return CafeCollectionProfileOut(
        profile_id=profile_id,
        display_name=str(latest_display_name or entry.user_id),
        avatar_url=avatar_urls.get(entry.user_id),
        total_cards=len(CARDS),
        total_sets=len(SETS),
        collection_count=entry.collection_count,
        total_draws=entry.total_draws,
        mastery_score=entry.mastery_score,
        completed_set_keys=sorted(
            completed_set_keys(
                {item.card.key for item in collection if item.lifetime_count > 0}
            )
        ),
        ranks=ranks,
        cards=[
            CafeCollectionProfileCardOut(
                card_key=item.card.key,
                count=item.count,
                lifetime_count=item.lifetime_count,
            )
            for item in collection
            if item.lifetime_count > 0
        ],
        captured_at=datetime.now(UTC),
    )


async def _cached_profile(
    session: AsyncSession,
    *,
    guild_id: str,
    profile_id: str,
) -> CafeCollectionProfileOut | None:
    cache_key = (guild_id, profile_id)
    now = monotonic()
    cached = _profile_cache.get(cache_key)
    if (
        cached is not None
        and now - cached.monotonic_at < PUBLIC_LEADERBOARD_CACHE_SECONDS
    ):
        return cached.value
    value = await _build_profile(session, guild_id=guild_id, profile_id=profile_id)
    if value is not None:
        _profile_cache[cache_key] = _CachedProfile(value=value, monotonic_at=now)
    return value


async def _build_leaderboards(
    session: AsyncSession,
    *,
    guild_id: str,
) -> CafeLeaderboardsOut:
    dependencies = default_dependencies()
    snapshot = await cafe_leaderboard_snapshot(
        session,
        guild_id=guild_id,
        dependencies=dependencies,
    )
    user_ids = [entry.user_id for entry in snapshot.entries]
    latest_draw_names = (
        select(
            CafeGachaDraw.user_id.label("user_id"),
            CafeGachaDraw.display_name.label("display_name"),
            func.row_number()
            .over(
                partition_by=CafeGachaDraw.user_id,
                order_by=(CafeGachaDraw.created_at.desc(), CafeGachaDraw.id.desc()),
            )
            .label("row_number"),
        )
        .where(
            CafeGachaDraw.guild_id == guild_id,
            CafeGachaDraw.user_id.in_(user_ids),
        )
        .subquery()
    )
    draw_name_rows = (
        await session.execute(
            select(latest_draw_names.c.user_id, latest_draw_names.c.display_name).where(
                latest_draw_names.c.row_number == 1
            )
        )
    ).all()
    draw_names: dict[str, str] = {
        str(user_id): str(display_name) for user_id, display_name in draw_name_rows
    }
    avatar_urls = await dependencies.user_presentation.avatar_urls(
        session,
        user_ids=tuple(user_ids),
    )

    display_names: dict[str, str] = {}
    for entry in snapshot.entries:
        display_names[entry.user_id] = str(
            draw_names.get(entry.user_id) or entry.user_id
        )

    categories: list[CafeLeaderboardCategoryOut] = []
    for category in CAFE_LEADERBOARD_CATEGORIES:
        entries = rank_cafe_leaderboard(snapshot, category)[:PUBLIC_LEADERBOARD_LIMIT]
        categories.append(
            CafeLeaderboardCategoryOut(
                key=category,
                entries=[
                    _entry_out(
                        entry,
                        guild_id=guild_id,
                        display_name=display_names[entry.user_id],
                        avatar_url=avatar_urls.get(entry.user_id),
                    )
                    for entry in entries
                ],
            )
        )
    return CafeLeaderboardsOut(
        guild_id=guild_id,
        total_cards=len(CARDS),
        total_sets=len(SETS),
        participant_count=len(snapshot.entries),
        total_draws=sum(entry.total_draws for entry in snapshot.entries),
        captured_at=datetime.now(UTC),
        categories=categories,
    )


async def _cached_leaderboards(
    session: AsyncSession,
    *,
    guild_id: str,
) -> CafeLeaderboardsOut:
    now = monotonic()
    cached = _leaderboard_cache.get(guild_id)
    if (
        cached is not None
        and now - cached.monotonic_at < PUBLIC_LEADERBOARD_CACHE_SECONDS
    ):
        return cached.value

    lock = _leaderboard_locks.setdefault(guild_id, asyncio.Lock())
    async with lock:
        now = monotonic()
        cached = _leaderboard_cache.get(guild_id)
        if (
            cached is not None
            and now - cached.monotonic_at < PUBLIC_LEADERBOARD_CACHE_SECONDS
        ):
            return cached.value
        value = await _build_leaderboards(session, guild_id=guild_id)
        _leaderboard_cache[guild_id] = _CachedLeaderboards(
            value=value,
            monotonic_at=now,
        )
        return value


@router.get(
    "/catalog",
    response_model=CafeCatalogOut,
    summary="公開カフェ・コレクション図鑑",
)
async def catalog(response: Response) -> CafeCatalogOut:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return CATALOG_RESPONSE


@router.get(
    "/cards/{card_key}/image",
    response_class=FileResponse,
    summary="公開カード画像",
)
async def card_image(card_key: str) -> FileResponse:
    card = next((card for card in CARDS if card.key == card_key), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return FileResponse(
        ASSET_DIR / card.image_filename,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get(
    "/guilds/{guild_id}/leaderboards",
    response_model=CafeLeaderboardsOut,
    summary="公開カフェ・コレクションランキング",
)
async def leaderboards(
    guild_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeLeaderboardsOut:
    await _require_public_guild(db, guild_id)
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=60"
    return await _cached_leaderboards(db, guild_id=guild_id)


@router.get(
    "/guilds/{guild_id}/profiles/{profile_id}",
    response_model=CafeCollectionProfileOut,
    summary="公開カフェ・コレクション個人棚",
)
async def collection_profile(
    guild_id: str,
    profile_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CafeCollectionProfileOut:
    await _require_public_guild(db, guild_id)
    if len(profile_id) != 24 or any(
        character not in "0123456789abcdef" for character in profile_id
    ):
        raise HTTPException(status_code=404, detail="Collection profile not found")
    profile = await _cached_profile(db, guild_id=guild_id, profile_id=profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Collection profile not found")
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=60"
    return profile
