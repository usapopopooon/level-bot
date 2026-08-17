from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import CafeGachaDraw, UserMeta
from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.public_routes import (
    CATALOG_RESPONSE,
    PUBLIC_CAFE_API_PREFIX,
    clear_public_cafe_leaderboard_cache,
)
from src.features.guilds.service import get_guild_settings, upsert_guild
from src.web.app import app
from src.web.deps import get_db

GUILD_ID = "1001"
OTHER_GUILD_ID = "1002"


def test_catalog_response_contains_complete_rates_and_public_rules() -> None:
    body = CATALOG_RESPONSE.model_dump()

    assert len(body["cards"]) == 120
    assert sum(card["base_draw_rate_percent"] for card in body["cards"]) == (
        pytest.approx(100.0)
    )
    k_pan = next(card for card in body["cards"] if card["key"] == "k-pan")
    assert k_pan["base_draw_rate_percent"] == pytest.approx(2.1)
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


async def test_catalog_and_images_are_public_without_login(
    public_api_client: AsyncClient,
) -> None:
    catalog = await public_api_client.get(f"{PUBLIC_CAFE_API_PREFIX}/catalog")

    assert catalog.status_code == 200
    assert catalog.headers["cache-control"] == "public, max-age=3600"
    body = catalog.json()
    assert body["total_cards"] == 120
    assert body["food_cards"] == 39
    assert body["rarity_rates_percent"] == {
        "N": 65.0,
        "HN": 24.0,
        "R": 8.0,
        "SR": 2.5,
        "SSR": 0.5,
    }
    assert len(body["cards"]) == 120
    assert len(body["sets"]) == 11
    assert sum(card["base_draw_rate_percent"] for card in body["cards"]) == (
        pytest.approx(100.0)
    )
    k_pan = next(card for card in body["cards"] if card["key"] == "k-pan")
    assert k_pan["base_draw_rate_percent"] == pytest.approx(2.1)
    assert body["rules"] == {
        "free_draws_per_day": 1,
        "free_draw_reset_timezone": "Asia/Tokyo",
        "paid_draw_cost_xp": 20,
        "hourly_draw_limit": 10,
        "daily_draw_limit": None,
        "unowned_weight_multiplier": 2,
        "endgame_pity_min_collected": 108,
        "endgame_pity_duplicate_draws": 100,
        "first_copy_protected": True,
        "draw_results_public": True,
    }

    image = await public_api_client.get(f"{PUBLIC_CAFE_API_PREFIX}/cards/k-pan/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["cache-control"] == ("public, max-age=31536000, immutable")
    assert image.content.startswith(b"\xff\xd8\xff")

    write_attempt = await public_api_client.post(f"{PUBLIC_CAFE_API_PREFIX}/catalog")
    assert write_attempt.status_code == 405


async def test_unknown_card_image_returns_404(
    public_api_client: AsyncClient,
) -> None:
    response = await public_api_client.get(
        f"{PUBLIC_CAFE_API_PREFIX}/cards/not-a-card/image"
    )

    assert response.status_code == 404


async def test_public_leaderboards_include_names_and_all_five_categories(
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
        ]
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
    assert body["total_draws"] == 2
    assert [category["key"] for category in body["categories"]] == [
        "collection",
        "mastery",
        "sets",
        "rare",
        "joke",
    ]
    collection_leader = body["categories"][0]["entries"][0]
    assert collection_leader["rank"] == 1
    assert collection_leader["display_name"] == "うさぽ"
    assert "user_id" not in collection_leader
    assert "avatar_url" not in collection_leader
    assert collection_leader["collection_count"] == 2


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
    assert response.json()["categories"][0]["entries"][0]["display_name"] == "今の名前"


async def test_public_leaderboards_are_cached_for_five_minutes(
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
    db_session.add(_draw(event_id="cached-cafe-2", user_id="2001", reward_key="scone"))
    await db_session.commit()
    cached = await public_api_client.get(path)
    clear_public_cafe_leaderboard_cache()
    refreshed = await public_api_client.get(path)

    assert first.json()["total_draws"] == 1
    assert cached.json()["total_draws"] == 1
    assert refreshed.json()["total_draws"] == 2
