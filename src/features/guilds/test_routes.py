"""HTTP-level tests for guild settings routes (roles / level-role-awards)."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import RoleMeta
from src.features.guilds.service import list_level_role_awards_for_grant
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


async def test_list_roles_excludes_managed_and_everyone(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            RoleMeta(guild_id="1001", role_id="1", name="@everyone", position=0),
            RoleMeta(
                guild_id="1001",
                role_id="2",
                name="Managed",
                position=5,
                is_managed=True,
            ),
            RoleMeta(
                guild_id="1001",
                role_id="3",
                name="Member",
                position=3,
                is_managed=False,
            ),
        ]
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/roles")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["role_name"] for r in body] == ["Member"]


async def test_put_level_role_awards_uses_role_id(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            RoleMeta(guild_id="1001", role_id="9001", name="Same", position=1),
            RoleMeta(guild_id="1001", role_id="9002", name="Same", position=2),
        ]
    )
    await db_session.commit()

    resp = await api_client.put(
        "/api/v1/guilds/1001/level-role-awards",
        json={
            "rules": [
                {"level": 3, "role_id": "9001"},
                {"level": 10, "role_id": "9002"},
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [(r["level"], r["role_id"], r["role_name"]) for r in body] == [
        (3, "9001", "Same"),
        (10, "9002", "Same"),
    ]

    rows = await list_level_role_awards_for_grant(db_session, "1001")
    assert [(r.level, r.role_id) for r in rows] == [(3, "9001"), (10, "9002")]


async def test_put_level_role_awards_rejects_unknown_role_id(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.put(
        "/api/v1/guilds/1001/level-role-awards",
        json={"rules": [{"level": 3, "role_id": "9999"}]},
    )
    assert resp.status_code == 422
