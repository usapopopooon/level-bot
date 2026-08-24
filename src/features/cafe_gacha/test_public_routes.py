from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import (
    CafeGachaDraw,
    CafeGachaRedemption,
    CafeGachaRedemptionItem,
    UserMeta,
)
from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.public_routes import (
    CATALOG_RESPONSE,
    PUBLIC_CAFE_API_PREFIX,
    clear_public_cafe_leaderboard_cache,
)
from src.features.guilds.service import get_guild_settings, upsert_guild
from src.features.meta.service import upsert_guild_member_meta
from src.web.app import app
from src.web.deps import get_db

GUILD_ID = "1001"
OTHER_GUILD_ID = "1002"


def test_catalog_response_contains_complete_rates_and_public_rules() -> None:
    body = CATALOG_RESPONSE.model_dump()

    assert len(body["cards"]) == 361
    assert sum(card["base_draw_rate_percent"] for card in body["cards"]) == (
        pytest.approx(100.0)
    )
    k_pan = next(card for card in body["cards"] if card["key"] == "k-pan")
    assert k_pan["base_draw_rate_percent"] == pytest.approx(0.72)
    assert k_pan["image_url"].startswith(
        f"{PUBLIC_CAFE_API_PREFIX}/cards/k-pan/image?v="
    )
    assert k_pan["draw_reward_xp"] == 25
    assert k_pan["exchange_xp"] == 5
    assert k_pan["tags"] == ["culture"]
    assert body["rules"]["paid_draw_cost_xp"] == 20
    assert body["rules"]["daily_draw_limit"] is None
    assert body["rules"]["first_copy_protected"] is True


@pytest_asyncio.fixture
async def public_api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    clear_public_cafe_leaderboard_cache()
    previous_site_guild_id = settings.user_stats_site_guild_id
    settings.user_stats_site_guild_id = GUILD_ID
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    settings.user_stats_site_guild_id = previous_site_guild_id
    clear_public_cafe_leaderboard_cache()


def _draw(
    *,
    event_id: str,
    user_id: str,
    reward_key: str,
    display_name: str | None = None,
    created_at: datetime | None = None,
) -> CafeGachaDraw:
    card = CARDS_BY_KEY[reward_key]
    return CafeGachaDraw(
        event_id=event_id,
        batch_id=event_id,
        batch_position=1,
        guild_id=GUILD_ID,
        user_id=user_id,
        display_name=display_name or f"客{user_id}",
        draw_type="free",
        cost_xp=0,
        reward_xp=card.draw_reward_xp,
        reward_key=card.key,
        reward_name=card.name,
        reward_description=card.description,
        rarity=card.rarity,
        image_filename=card.image_filename,
        exchange_xp=card.exchange_xp,
        was_duplicate=False,
        owned_count=1,
        collected_count=1,
        **({"created_at": created_at} if created_at is not None else {}),
    )


async def test_catalog_is_public_without_login(
    public_api_client: AsyncClient,
) -> None:
    catalog = await public_api_client.get(f"{PUBLIC_CAFE_API_PREFIX}/catalog")

    assert catalog.status_code == 200
    assert catalog.headers["cache-control"] == "public, max-age=3600"
    body = catalog.json()
    assert body["total_cards"] == 361
    assert body["food_cards"] == 126
    assert body["rarity_rates_percent"] == {
        "N": 65.0,
        "HN": 24.0,
        "R": 8.0,
        "SR": 2.5,
        "SSR": 0.4,
        "UR": 0.08,
        "幻": 0.02,
    }
    assert len(body["cards"]) == 361
    assert len(body["sets"]) == 50
    assert sum(card["base_draw_rate_percent"] for card in body["cards"]) == (
        pytest.approx(100.0)
    )
    k_pan = next(card for card in body["cards"] if card["key"] == "k-pan")
    assert k_pan["base_draw_rate_percent"] == pytest.approx(0.72)
    coffee_leaf_tea = next(
        card for card in body["cards"] if card["key"] == "coffee-leaf-tea"
    )
    assert coffee_leaf_tea["tags"] == ["coffee", "culture", "tea"]
    assert body["rules"] == {
        "free_draws_per_day": 1,
        "free_draw_reset_timezone": "Asia/Tokyo",
        "paid_draw_cost_xp": 20,
        "hourly_draw_limit": 10,
        "daily_draw_limit": None,
        "unowned_weight_multiplier": 2,
        "endgame_pity_min_collected": 166,
        "endgame_pity_duplicate_draws": 100,
        "first_copy_protected": True,
        "draw_results_public": True,
    }

    write_attempt = await public_api_client.post(f"{PUBLIC_CAFE_API_PREFIX}/catalog")
    assert write_attempt.status_code == 405


async def test_level_bot_no_longer_serves_card_images(
    public_api_client: AsyncClient,
) -> None:
    response = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/cards/k-pan/image"
    )

    assert response.status_code == 404


async def test_public_leaderboards_include_names_and_all_ten_categories(
    public_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="CHILLカフェ",
        icon_url=None,
        member_count=2,
    )
    db_session.add_all(
        [
            UserMeta(
                user_id="2001",
                display_name="別ギルドでの名前",
                avatar_url="https://cdn.example/avatar.png",
            ),
            _draw(
                event_id="public-cafe-1",
                user_id="2001",
                reward_key="k-pan",
                display_name="うさぽ",
            ),
            _draw(
                event_id="public-cafe-2",
                user_id="2001",
                reward_key="scone",
                display_name="うさぽ",
            ),
            _draw(
                event_id="public-cafe-3",
                user_id="2001",
                reward_key="k-pan",
                display_name="うさぽ",
            ),
        ]
    )
    await db_session.flush()
    redemption = CafeGachaRedemption(
        event_id="public-cafe-redemption",
        guild_id=GUILD_ID,
        user_id="2001",
        display_name="うさぽ",
        reward_xp=CARDS_BY_KEY["k-pan"].exchange_xp,
    )
    db_session.add(redemption)
    await db_session.flush()
    db_session.add(
        CafeGachaRedemptionItem(
            redemption_id=redemption.id,
            reward_key="k-pan",
            reward_name=CARDS_BY_KEY["k-pan"].name,
            rarity=CARDS_BY_KEY["k-pan"].rarity,
            quantity=1,
            xp_per_card=CARDS_BY_KEY["k-pan"].exchange_xp,
            reward_xp=CARDS_BY_KEY["k-pan"].exchange_xp,
        )
    )
    await db_session.commit()

    response = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/leaderboards"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == (
        "public, max-age=300, stale-while-revalidate=60"
    )
    body = response.json()
    assert body["participant_count"] == 1
    assert body["total_draws"] == 3
    assert [category["key"] for category in body["categories"]] == [
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
    collection_leader = body["categories"][0]["entries"][0]
    assert collection_leader["rank"] == 1
    assert len(collection_leader["profile_id"]) == 24
    assert set(collection_leader["profile_id"]) <= set("0123456789abcdef")
    assert collection_leader["display_name"] == "うさぽ"
    assert collection_leader["avatar_url"] == "https://cdn.example/avatar.png"
    assert "user_id" not in collection_leader
    assert collection_leader["collection_count"] == 2
    treasure_category = next(
        category for category in body["categories"] if category["key"] == "treasure"
    )
    assert treasure_category["entries"] == []

    profile = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/profiles/"
        f"{collection_leader['profile_id']}"
    )

    assert profile.status_code == 200
    assert profile.headers["cache-control"] == (
        "public, max-age=300, stale-while-revalidate=60"
    )
    profile_body = profile.json()
    assert profile_body["profile_id"] == collection_leader["profile_id"]
    assert profile_body["display_name"] == "うさぽ"
    assert profile_body["avatar_url"] == "https://cdn.example/avatar.png"
    assert profile_body["total_cards"] == 361
    assert profile_body["total_sets"] == 50
    assert profile_body["collection_count"] == 2
    assert profile_body["total_draws"] == 3
    assert profile_body["mastery_score"] == 2
    assert profile_body["completed_set_keys"] == []
    assert profile_body["ranks"] == {
        "collection": 1,
        "mastery": 1,
        "sets": 1,
        "rare": 1,
        "joke": 1,
        "coffee": 1,
        "tea": 1,
        "sweets": 1,
        "culture": 1,
    }
    assert {
        item["card_key"]: (item["count"], item["lifetime_count"])
        for item in profile_body["cards"]
    } == {
        "k-pan": (1, 2),
        "scone": (1, 1),
    }
    assert "user_id" not in profile_body

    unknown_profile = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/profiles/000000000000000000000000"
    )
    malformed_profile = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/profiles/not-a-profile"
    )
    assert unknown_profile.status_code == 404
    assert malformed_profile.status_code == 404


async def test_leaderboards_hide_private_or_unknown_guilds(
    public_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    unknown = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/9999/leaderboards"
    )
    assert unknown.status_code == 404

    await upsert_guild(
        db_session,
        guild_id=OTHER_GUILD_ID,
        name="別の公開ギルド",
        icon_url=None,
        member_count=1,
    )
    other_public = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{OTHER_GUILD_ID}/leaderboards"
    )
    assert other_public.status_code == 404

    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="private",
        icon_url=None,
        member_count=1,
    )
    settings = await get_guild_settings(db_session, GUILD_ID)
    assert settings is not None
    settings.public = False
    await db_session.commit()

    private = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/leaderboards"
    )
    assert private.status_code == 404


async def test_leaderboards_are_disabled_without_an_explicit_guild_id(
    public_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="CHILLカフェ",
        icon_url=None,
        member_count=1,
    )
    settings.user_stats_site_guild_id = ""

    response = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/leaderboards"
    )

    assert response.status_code == 404


async def test_public_profile_hides_a_departed_member(
    public_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="CHILLカフェ",
        icon_url=None,
        member_count=1,
    )
    db_session.add(_draw(event_id="departed-cafe", user_id="2001", reward_key="k-pan"))
    await db_session.commit()
    leaderboard = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/leaderboards"
    )
    profile_id = leaderboard.json()["categories"][0]["entries"][0]["profile_id"]

    await upsert_guild_member_meta(
        db_session,
        guild_id=GUILD_ID,
        user_id="2001",
        is_active=False,
    )
    clear_public_cafe_leaderboard_cache()
    profile = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/profiles/{profile_id}"
    )

    assert profile.status_code == 404


async def test_public_leaderboards_fall_back_to_latest_draw_name(
    public_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="CHILLカフェ",
        icon_url=None,
        member_count=1,
    )
    db_session.add_all(
        [
            _draw(
                event_id="old-name",
                user_id="2001",
                reward_key="k-pan",
                display_name="旧い名前",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            _draw(
                event_id="new-name",
                user_id="2001",
                reward_key="scone",
                display_name="今の名前",
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    response = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/leaderboards"
    )

    assert response.status_code == 200
    entry = response.json()["categories"][0]["entries"][0]
    assert entry["display_name"] == "今の名前"
    assert entry["avatar_url"] is None


async def test_public_leaderboards_and_profiles_are_cached_for_five_minutes(
    public_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="CHILLカフェ",
        icon_url=None,
        member_count=1,
    )
    db_session.add(_draw(event_id="cached-cafe-1", user_id="2001", reward_key="k-pan"))
    await db_session.commit()
    path = f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/leaderboards"

    first = await public_api_client.get(path)
    profile_path = (
        f"{PUBLIC_CAFE_API_PREFIX}/guilds/{GUILD_ID}/profiles/"
        f"{first.json()['categories'][0]['entries'][0]['profile_id']}"
    )
    first_profile = await public_api_client.get(profile_path)
    db_session.add(_draw(event_id="cached-cafe-2", user_id="2001", reward_key="scone"))
    await db_session.commit()
    cached = await public_api_client.get(path)
    cached_profile = await public_api_client.get(profile_path)
    clear_public_cafe_leaderboard_cache()
    refreshed = await public_api_client.get(path)
    refreshed_profile = await public_api_client.get(profile_path)

    assert first.json()["total_draws"] == 1
    assert cached.json()["total_draws"] == 1
    assert refreshed.json()["total_draws"] == 2
    assert first_profile.json()["total_draws"] == 1
    assert cached_profile.json()["total_draws"] == 1
    assert refreshed_profile.json()["total_draws"] == 2
