"""HTTP-level tests for stats routes."""

from collections.abc import AsyncIterator
from datetime import date

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import DailyStat, SocialEdgeDaily, UserMeta
from src.web.app import app
from src.web.deps import get_db
from src.web.jwt_auth import create_jwt_token


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session", create_jwt_token("tester"))
        yield client
    app.dependency_overrides.clear()


async def test_social_graph_route_returns_nodes_and_edges(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            UserMeta(user_id="2001", display_name="Alice"),
            UserMeta(user_id="2002", display_name="Bob"),
            DailyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=date(2026, 5, 23),
                message_count=5,
                voice_seconds=600,
            ),
            DailyStat(
                guild_id="1001",
                user_id="2002",
                channel_id="3001",
                stat_date=date(2026, 5, 23),
                reactions_given=4,
            ),
            SocialEdgeDaily(
                guild_id="1001",
                source_user_id="2001",
                target_user_id="2002",
                channel_id="3001",
                stat_date=date(2026, 5, 23),
                voice_seconds=600,
                voice_sessions=1,
                replies=2,
                reactions=4,
            ),
        ]
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/social-graph?days=365")

    assert resp.status_code == 200
    body = resp.json()
    assert body["guild_id"] == "1001"
    assert body["days"] == 365
    nodes = {node["user_id"]: node for node in body["nodes"]}
    assert nodes["2001"]["display_name"] == "Alice"
    assert nodes["2002"]["display_name"] == "Bob"
    assert nodes["2001"]["message_count"] == 5
    assert nodes["2001"]["voice_seconds"] == 600
    assert len(body["edges"]) == 1
    assert body["edges"][0]["source_user_id"] == "2001"
    assert body["edges"][0]["target_user_id"] == "2002"
    assert body["edges"][0]["replies"] == 2


async def test_social_graph_route_validates_limit(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/guilds/1001/social-graph?limit=999")
    assert resp.status_code == 422
