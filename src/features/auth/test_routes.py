"""認証 API の HTTP レベルテスト + ミドルウェアの保護動作確認。"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import src.web.security as _security
from src.web.app import app
from src.web.deps import get_db


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """テスト用 db_session を差し込んだ AsyncClient (auth クッキー無し)。"""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_creds(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """テスト用の admin 資格情報を有効化する。"""
    user, password = "tester", "s3cret-pass"
    monkeypatch.setattr(_security, "ADMIN_USER", user)
    monkeypatch.setattr(_security, "ADMIN_PASSWORD", password)
    return user, password


# =============================================================================
# /api/v1/auth/login
# =============================================================================


async def test_login_success_sets_session_cookie(
    api_client: AsyncClient, admin_creds: tuple[str, str]
) -> None:
    user, pw = admin_creds
    resp = await api_client.post(
        "/api/v1/auth/login", json={"user": user, "password": pw}
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert "session" in resp.cookies


async def test_login_rejects_bad_password(
    api_client: AsyncClient, admin_creds: tuple[str, str]
) -> None:
    user, _ = admin_creds
    resp = await api_client.post(
        "/api/v1/auth/login", json={"user": user, "password": "wrong"}
    )
    assert resp.status_code == 401


async def test_login_rejects_when_admin_password_unset(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADMIN_PASSWORD が空のときはどんな入力でも 401 になる (誤起動の安全策)。"""
    monkeypatch.setattr(_security, "ADMIN_USER", "admin")
    monkeypatch.setattr(_security, "ADMIN_PASSWORD", "")
    resp = await api_client.post(
        "/api/v1/auth/login", json={"user": "admin", "password": ""}
    )
    assert resp.status_code == 401


# =============================================================================
# /api/v1/auth/me
# =============================================================================


async def test_me_returns_401_without_cookie(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_returns_user_with_cookie(
    api_client: AsyncClient, admin_creds: tuple[str, str]
) -> None:
    user, pw = admin_creds
    await api_client.post("/api/v1/auth/login", json={"user": user, "password": pw})
    resp = await api_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"user": user}


# =============================================================================
# /api/v1/auth/logout
# =============================================================================


async def test_logout_clears_cookie_and_subsequent_me_is_401(
    api_client: AsyncClient, admin_creds: tuple[str, str]
) -> None:
    user, pw = admin_creds
    await api_client.post("/api/v1/auth/login", json={"user": user, "password": pw})
    resp = await api_client.post("/api/v1/auth/logout")
    assert resp.status_code == 200

    me = await api_client.get("/api/v1/auth/me")
    assert me.status_code == 401


# =============================================================================
# Auth middleware: 全 /api/v1/* (auth 以外) は cookie 必須
# =============================================================================


async def test_protected_route_returns_401_without_cookie(
    api_client: AsyncClient,
) -> None:
    """未認証のまま叩くと 401 (例: guild summary)。"""
    resp = await api_client.get("/api/v1/guilds/1001/summary")
    assert resp.status_code == 401


async def test_protected_route_passes_with_cookie(
    api_client: AsyncClient, admin_creds: tuple[str, str]
) -> None:
    """ログイン後は 401 にならない (404 等は別理由なので OK)。"""
    user, pw = admin_creds
    await api_client.post("/api/v1/auth/login", json={"user": user, "password": pw})
    resp = await api_client.get("/api/v1/guilds/1001/summary")
    # 404 (guild が無い) はあり得るが、401 でないことが本質
    assert resp.status_code != 401


async def test_healthz_remains_public(api_client: AsyncClient) -> None:
    resp = await api_client.get("/healthz")
    assert resp.status_code == 200


async def test_root_remains_public(api_client: AsyncClient) -> None:
    resp = await api_client.get("/")
    assert resp.status_code == 200
