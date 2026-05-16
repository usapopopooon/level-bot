"""HTTP-level tests for guild settings routes (roles / level-role-awards)."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import RoleMeta
from src.features.guilds.service import (
    list_guild_ids_requiring_level_role_sync,
    list_level_role_awards_for_grant,
    upsert_guild,
)
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
    await upsert_guild(
        db_session,
        guild_id="1001",
        name="Guild",
        icon_url=None,
        member_count=1,
    )
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
                {"slot": 1, "level": 3, "role_id": "9001"},
                {"slot": 2, "level": 10, "role_id": "9002"},
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [(r["slot"], r["level"], r["role_id"], r["role_name"]) for r in body] == [
        (1, 3, "9001", "Same"),
        (2, 10, "9002", "Same"),
    ]

    rows = await list_level_role_awards_for_grant(db_session, "1001")
    assert [(r.slot, r.level, r.role_id) for r in rows] == [
        (1, 3, "9001"),
        (2, 10, "9002"),
    ]
    pending_sync = await list_guild_ids_requiring_level_role_sync(db_session)
    assert "1001" in pending_sync


async def test_put_level_role_awards_rejects_unknown_role_id(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.put(
        "/api/v1/guilds/1001/level-role-awards",
        json={"rules": [{"slot": 1, "level": 3, "role_id": "9999"}]},
    )
    assert resp.status_code == 422


async def test_put_level_role_awards_defaults_slot_to_one(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await upsert_guild(
        db_session,
        guild_id="1002",
        name="Guild 2",
        icon_url=None,
        member_count=1,
    )
    db_session.add(RoleMeta(guild_id="1002", role_id="9101", name="R", position=1))
    await db_session.commit()

    resp = await api_client.put(
        "/api/v1/guilds/1002/level-role-awards",
        json={"rules": [{"level": 3, "role_id": "9101"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["slot"] == 1


async def test_put_level_role_awards_allows_level_zero(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await upsert_guild(
        db_session,
        guild_id="1003",
        name="Guild 3",
        icon_url=None,
        member_count=1,
    )
    db_session.add(RoleMeta(guild_id="1003", role_id="9201", name="Newbie", position=1))
    await db_session.commit()

    resp = await api_client.put(
        "/api/v1/guilds/1003/level-role-awards",
        json={"rules": [{"slot": 1, "level": 0, "role_id": "9201"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"slot": 1, "level": 0, "role_id": "9201", "role_name": "Newbie"}]
