"""HTTP-level tests for color-role shop management routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import ChannelMeta, RoleMeta
from src.features.guilds.service import upsert_guild
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


async def test_manage_color_role_items_from_api(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add(RoleMeta(guild_id="1001", role_id="2001", name="Red", position=1))
    await db_session.commit()

    create_resp = await api_client.put(
        "/api/v1/guilds/1001/color-role-shop/items/2001",
        json={"role_id": "2001", "cost_xp": 500, "description": "赤色"},
    )
    assert create_resp.status_code == 200
    assert create_resp.json() == {
        "id": 1,
        "role_id": "2001",
        "role_name": "Red",
        "label": "Red",
        "description": "赤色",
        "cost_xp": 500,
    }

    list_resp = await api_client.get("/api/v1/guilds/1001/color-role-shop/items")
    assert list_resp.status_code == 200
    assert [item["role_id"] for item in list_resp.json()] == ["2001"]

    delete_resp = await api_client.delete(
        "/api/v1/guilds/1001/color-role-shop/items/2001"
    )
    assert delete_resp.status_code == 204

    after_delete_resp = await api_client.get(
        "/api/v1/guilds/1001/color-role-shop/items"
    )
    assert after_delete_resp.status_code == 200
    assert after_delete_resp.json() == []


@pytest.mark.parametrize(
    ("path_role_id", "body", "expected_detail"),
    [
        ("2001", {"role_id": "9999", "cost_xp": 500}, "role_id path/body mismatch"),
        ("2001", {"role_id": "2001", "cost_xp": 0}, "cost_xp must be >= 1"),
        ("9999", {"role_id": "9999", "cost_xp": 500}, "Unknown role_id"),
    ],
)
async def test_put_color_role_item_rejects_invalid_input(
    api_client: AsyncClient,
    db_session: AsyncSession,
    path_role_id: str,
    body: dict[str, object],
    expected_detail: str,
) -> None:
    db_session.add(RoleMeta(guild_id="1001", role_id="2001", name="Red", position=1))
    await db_session.commit()

    resp = await api_client.put(
        f"/api/v1/guilds/1001/color-role-shop/items/{path_role_id}",
        json=body,
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == expected_detail


async def test_list_channels_returns_text_channels_only(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            ChannelMeta(
                guild_id="1001",
                channel_id="3001",
                name="general",
                channel_type="TextChannel",
            ),
            ChannelMeta(
                guild_id="1001",
                channel_id="3002",
                name="voice",
                channel_type="VoiceChannel",
            ),
        ]
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/channels")

    assert resp.status_code == 200
    assert resp.json() == [
        {
            "channel_id": "3001",
            "channel_name": "general",
            "channel_type": "TextChannel",
        }
    ]


async def test_post_color_role_panel_creates_new_message_payload(
    api_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.features.color_role_shop import routes

    await upsert_guild(
        db_session,
        guild_id="1001",
        name="Guild",
        icon_url="https://example.com/icon.png",
        member_count=1,
    )
    db_session.add_all(
        [
            RoleMeta(guild_id="1001", role_id="2001", name="Red", position=1),
            ChannelMeta(
                guild_id="1001",
                channel_id="3001",
                name="general",
                channel_type="TextChannel",
            ),
        ]
    )
    await db_session.commit()
    await api_client.put(
        "/api/v1/guilds/1001/color-role-shop/items/2001",
        json={"role_id": "2001", "cost_xp": 500, "description": "赤色"},
    )

    posted: dict[str, Any] = {}

    async def fake_post_discord_message(
        channel_id: str,
        payload: dict[str, Any],
    ) -> str:
        posted["channel_id"] = channel_id
        posted["payload"] = payload
        return "5555"

    monkeypatch.setattr(routes, "_post_discord_message", fake_post_discord_message)

    resp = await api_client.post(
        "/api/v1/guilds/1001/color-role-shop/panel",
        json={"channel_id": "3001"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"channel_id": "3001", "message_id": "5555"}
    assert posted["channel_id"] == "3001"
    payload = posted["payload"]
    assert payload["embeds"][0]["title"] == "カラーロール交換所"
    assert "thumbnail" not in payload["embeds"][0]
    assert "<@&2001>" in payload["embeds"][0]["fields"][0]["value"]
    components = payload["components"][0]["components"]
    assert [component["custom_id"] for component in components] == [
        "level:color-role:open:1001",
        "level:color-role:balance:1001",
        "level:color-role:clear:1001",
    ]
    assert components[2]["label"] == "ロールを外す"
    assert components[2]["style"] == 4


async def test_post_color_role_panel_rejects_old_panel_message_reference(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id="1001",
        name="Guild",
        icon_url=None,
        member_count=1,
    )
    db_session.add(
        ChannelMeta(
            guild_id="1001",
            channel_id="3001",
            name="general",
            channel_type="TextChannel",
        )
    )
    await db_session.commit()

    resp = await api_client.post(
        "/api/v1/guilds/1001/color-role-shop/panel",
        json={"channel_id": "3001", "message_id": "old-panel"},
    )

    assert resp.status_code == 422


async def test_post_color_role_panel_rejects_non_text_channel(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await upsert_guild(
        db_session,
        guild_id="1001",
        name="Guild",
        icon_url=None,
        member_count=1,
    )
    db_session.add(
        ChannelMeta(
            guild_id="1001",
            channel_id="3002",
            name="voice",
            channel_type="VoiceChannel",
        )
    )
    await db_session.commit()

    resp = await api_client.post(
        "/api/v1/guilds/1001/color-role-shop/panel",
        json={"channel_id": "3002"},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown text channel_id"
