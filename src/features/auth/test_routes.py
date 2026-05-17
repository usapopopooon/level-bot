"""認証 API の HTTP レベルテスト + ミドルウェアの保護動作確認。"""

import time
from collections.abc import AsyncIterator

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import src.web.security as _security
from src.constants import LOGIN_MAX_ATTEMPTS
from src.web.app import _parse_cors_origins, app
from src.web.deps import get_db
from src.web.jwt_auth import _ALGORITHM


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """テスト用 db_session を差し込んだ AsyncClient (auth クッキー無し)。

    各テストの始まりにレート制限の in-memory 状態もクリアする (テスト間漏れ防止)。
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    _security._LOGIN_ATTEMPTS.clear()
    _security._EXT_API_FAILURES.clear()
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


async def test_protected_route_401_includes_cors_headers(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.get(
        "/api/v1/guilds/1001/summary",
        headers={"Origin": "http://localhost:3000"},
    )

    assert resp.status_code == 401
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_protected_route_passes_with_cookie(
    api_client: AsyncClient, admin_creds: tuple[str, str]
) -> None:
    """ログイン後は 401 にならない (404 等は別理由なので OK)。"""
    user, pw = admin_creds
    await api_client.post("/api/v1/auth/login", json={"user": user, "password": pw})
    resp = await api_client.get("/api/v1/guilds/1001/summary")
    # 404 (guild が無い) はあり得るが、401 でないことが本質
    assert resp.status_code != 401


async def test_cors_preflight_for_protected_api_skips_auth(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.options(
        "/api/v1/guilds/1001/summary",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in resp.headers["access-control-allow-headers"].lower()


def test_parse_cors_origins_normalizes_trailing_slashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:5174/, https://chill-cafe.site/",
    )

    assert _parse_cors_origins() == [
        "http://localhost:5174",
        "https://chill-cafe.site",
    ]


async def test_healthz_remains_public(api_client: AsyncClient) -> None:
    resp = await api_client.get("/healthz")
    assert resp.status_code == 200


async def test_root_remains_public(api_client: AsyncClient) -> None:
    resp = await api_client.get("/")
    assert resp.status_code == 200


# =============================================================================
# External API key (Bearer) — server-to-server, GET only
# =============================================================================


@pytest.fixture
def external_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """テスト用の外部 API キーを有効化する。"""
    key = "test-external-key-abc123"
    monkeypatch.setattr(_security, "EXTERNAL_API_KEY", key)
    return key


async def test_bearer_token_allows_get_without_cookie(
    api_client: AsyncClient, external_key: str
) -> None:
    """有効な Bearer キーで cookie 無しでも protected GET が 401 にならない。"""
    resp = await api_client.get(
        "/api/v1/guilds/1001/summary",
        headers={"Authorization": f"Bearer {external_key}"},
    )
    # 404 (guild が無い) は OK、401 でないことが本質
    assert resp.status_code != 401


async def test_bearer_token_invalid_returns_401(api_client: AsyncClient) -> None:
    """無効な Bearer は cookie フォールバックせず即 401。"""
    resp = await api_client.get(
        "/api/v1/guilds/1001/summary",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


async def test_bearer_token_unset_key_returns_401(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``EXTERNAL_API_KEY`` が空のときは Bearer ヘッダは常に拒否。"""
    monkeypatch.setattr(_security, "EXTERNAL_API_KEY", "")
    resp = await api_client.get(
        "/api/v1/guilds/1001/summary",
        headers={"Authorization": "Bearer anything"},
    )
    assert resp.status_code == 401


async def test_bearer_token_rejects_non_get_methods(
    api_client: AsyncClient, external_key: str
) -> None:
    """外部 API は read-only。Bearer ヘッダ付きの POST は middleware が 405。

    /api/v1/auth/* は exempt なので使わない。protected ルートに POST する。
    """
    resp = await api_client.post(
        "/api/v1/guilds/1001/summary",
        headers={"Authorization": f"Bearer {external_key}"},
    )
    assert resp.status_code == 405


async def test_bearer_token_rate_limited_after_failures(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """無効 Bearer を連発すると 429。""​"""
    monkeypatch.setattr(_security, "EXTERNAL_API_KEY", "real-key")
    # 失敗閾値分 + 1 回叩いて最後が 429 になることを確認
    from src.constants import EXTERNAL_API_MAX_FAILURES

    last_status = None
    for _ in range(EXTERNAL_API_MAX_FAILURES + 1):
        r = await api_client.get(
            "/api/v1/guilds/1001/summary",
            headers={"Authorization": "Bearer wrong"},
        )
        last_status = r.status_code
    assert last_status == 429


# =============================================================================
# JWT expiry
# =============================================================================


async def test_expired_jwt_cookie_returns_401(
    api_client: AsyncClient,
) -> None:
    """有効期限切れの session JWT は middleware で 401 になる。"""
    expired = pyjwt.encode(
        {"sub": "tester", "exp": int(time.time()) - 10},
        _security.SECRET_KEY,
        algorithm=_ALGORITHM,
    )
    api_client.cookies.set("session", expired)
    resp = await api_client.get("/api/v1/guilds/1001/summary")
    assert resp.status_code == 401


# =============================================================================
# Login rate limiting
# =============================================================================


async def test_login_rate_limited_after_too_many_failures(
    api_client: AsyncClient,
    admin_creds: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一 IP がログイン連発失敗で 429 になる。"""
    # 連発失敗で _LOGIN_ATTEMPTS を貯める
    user, _ = admin_creds
    for _ in range(LOGIN_MAX_ATTEMPTS):
        await api_client.post(
            "/api/v1/auth/login", json={"user": user, "password": "wrong"}
        )
    # 次の試行はレート制限で 429 (正しい password でも弾かれる)
    r = await api_client.post(
        "/api/v1/auth/login", json={"user": user, "password": admin_creds[1]}
    )
    assert r.status_code == 429
    # cleanup
    monkeypatch.setattr(_security, "_LOGIN_ATTEMPTS", {})


# =============================================================================
# Docs require auth
# =============================================================================


async def test_openapi_docs_require_auth(api_client: AsyncClient) -> None:
    """``/docs`` と ``/openapi.json`` は未ログインだと 401。"""
    assert (await api_client.get("/docs")).status_code == 401
    assert (await api_client.get("/openapi.json")).status_code == 401


async def test_openapi_docs_accessible_after_login(
    api_client: AsyncClient, admin_creds: tuple[str, str]
) -> None:
    user, pw = admin_creds
    await api_client.post("/api/v1/auth/login", json={"user": user, "password": pw})
    assert (await api_client.get("/openapi.json")).status_code == 200
