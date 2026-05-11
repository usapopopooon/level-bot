"""認証 API ルート (シングル管理者 + JWT クッキー方式)。

- ``POST /api/v1/auth/login``: user/password を JSON で受けて JWT を ``session``
  クッキーに発行
- ``POST /api/v1/auth/logout``: クッキー削除
- ``GET /api/v1/auth/me``: 認証状態の確認 (未認証は 401)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import src.web.security as _security
from src.constants import SESSION_MAX_AGE_SECONDS
from src.web.jwt_auth import create_jwt_token, get_current_user_jwt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class _LoginRequest(BaseModel):
    user: str
    password: str


def _client_ip(request: Request) -> str:
    """X-Forwarded-For を尊重しつつ ``request.client.host`` を返す。"""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=None)
async def api_login(body: _LoginRequest, request: Request) -> JSONResponse:
    """JSON で送られた資格情報を検証し、JWT クッキーを発行する。

    レート制限: 同一 IP が 5 分間に 5 回以上失敗すると 429。
    """
    ip = _client_ip(request)
    if _security.is_login_rate_limited(ip):
        logger.warning("[auth] login rate-limited ip=%s", ip)
        return JSONResponse(
            {"detail": "Too many attempts. Try again later."},
            status_code=429,
        )

    user = body.user.strip() if body.user else ""
    password = body.password

    if not _security.verify_admin_credentials(user, password):
        _security.record_failed_login(ip)
        logger.info("[auth] login failed ip=%s user=%r", ip, user)
        return JSONResponse({"detail": "Invalid user or password"}, status_code=401)

    _security.clear_login_attempts(ip)
    token = create_jwt_token(user)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        key="session",
        value=token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=_security.SECURE_COOKIE,
        # frontend と api が別ドメインになる場合 (Next の rewrite を経由しない
        # 直接 fetch) でも cookie が落ちないよう lax にしている。
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", response_model=None)
async def api_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(key="session", path="/")
    return response


@router.get("/me", response_model=None)
async def api_me(
    user: dict[str, Any] | None = Depends(get_current_user_jwt),
) -> JSONResponse:
    if not user or not user.get("sub"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return JSONResponse({"user": user["sub"]})
