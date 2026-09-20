"""ユーザープロフィールAPIとCafe Collection導線の結合テスト。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database.models import CafeGachaDraw, DailyStat
from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.public_profile import public_cafe_profile_id
from src.features.guilds.service import upsert_guild
from src.features.meta.service import upsert_guild_member_meta
from src.utils import today_local
from src.web.app import app
from src.web.deps import get_db
from src.web.jwt_auth import create_jwt_token

GUILD_ID = "1001"
USER_ID = "2001"


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    previous_site_guild_id = settings.user_stats_site_guild_id
    settings.user_stats_site_guild_id = GUILD_ID
    await upsert_guild(
        db_session,
        guild_id=GUILD_ID,
        name="CHILLカフェ",
        icon_url=None,
        member_count=1,
    )
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session", create_jwt_token("tester"))
        yield client
    app.dependency_overrides.clear()
    settings.user_stats_site_guild_id = previous_site_guild_id


def _profile_activity() -> DailyStat:
    return DailyStat(
        guild_id=GUILD_ID,
        user_id=USER_ID,
        channel_id="3001",
        stat_date=today_local(),
        message_count=1,
    )


def _cafe_draw(reward_key: str = "spent-tea") -> CafeGachaDraw:
    card = CARDS_BY_KEY[reward_key]
    return CafeGachaDraw(
        event_id="profile-cafe-draw",
        batch_id="profile-cafe-draw",
        batch_position=1,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        display_name="カフェ参加者",
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
    )


@pytest.mark.parametrize("reward_key", ["spent-tea", "sakura-white-chocolate-latte"])
async def test_profile_exposes_public_cafe_id_for_participant(
    api_client: AsyncClient,
    db_session: AsyncSession,
    reward_key: str,
) -> None:
    db_session.add_all([_profile_activity(), _cafe_draw(reward_key)])
    await db_session.commit()

    response = await api_client.get(f"/api/v1/guilds/{GUILD_ID}/users/{USER_ID}?days=1")

    assert response.status_code == 200
    assert response.json()["cafe_collection_profile_id"] == public_cafe_profile_id(
        guild_id=GUILD_ID,
        user_id=USER_ID,
    )


async def test_profile_hides_cafe_link_for_nonparticipant(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(_profile_activity())
    await db_session.commit()

    response = await api_client.get(f"/api/v1/guilds/{GUILD_ID}/users/{USER_ID}?days=1")

    assert response.status_code == 200
    assert response.json()["cafe_collection_profile_id"] is None


async def test_profile_hides_cafe_link_when_public_profile_is_blocked(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add_all([_profile_activity(), _cafe_draw()])
    await db_session.commit()
    await upsert_guild_member_meta(
        db_session,
        guild_id=GUILD_ID,
        user_id=USER_ID,
        is_active=False,
    )

    response = await api_client.get(f"/api/v1/guilds/{GUILD_ID}/users/{USER_ID}?days=1")

    assert response.status_code == 200
    assert response.json()["cafe_collection_profile_id"] is None
