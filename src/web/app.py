"""FastAPI application entry point.

公開ダッシュボード用の JSON API を提供する。フロントエンド (Next.js) は
``/api/v1/*`` を rewrite で叩くか、本番では同じ Railway プロジェクト内で
内部 URL から直接叩く。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response

from src.features.auth.routes import router as auth_router
from src.features.guilds.routes import router as guilds_router
from src.features.leveling.routes import router as leveling_router
from src.features.ranking.routes import router as ranking_router
from src.features.stats.routes import router as stats_router
from src.features.user_profile.routes import router as user_profile_router
from src.logging_config import setup_logging
from src.migrations import run_migrations
from src.web.jwt_auth import verify_jwt_token
from src.web.security import (
    check_production_safety,
    is_external_api_rate_limited,
    record_external_api_failure,
    verify_external_api_key,
)

setup_logging()
logger = logging.getLogger(__name__)


def _parse_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    if not raw:
        return ["http://localhost:3000"]
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """API 起動時にスキーマを最新にする (Railway 等 release phase 不在環境向け)。

    本番環境では必須 env (SESSION_SECRET_KEY 等) の不在で起動を拒否する。
    """
    check_production_safety()
    try:
        run_migrations()
    except Exception:
        logger.exception("Alembic migration failed during API startup")
        raise
    yield


app = FastAPI(
    title="Level Bot Stats API",
    description="Public read-only API for Discord server statistics.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    # 認証付き fetch (cookie 同送) を許可するため credentials を有効化。
    # allow_origins=["*"] と credentials は併用不可なので、CORS_ORIGINS で
    # 明示的なオリジン列挙が必要。
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# 500 バイト以上のレスポンスを gzip 圧縮。レベルランキング等の JSON で効く。
app.add_middleware(GZipMiddleware, minimum_size=500)


# 認証が不要なパス (auth API 自身 + ヘルスチェック + ルート)
# /docs /openapi.json /redoc は **意図的に保護** している (情報源として
# 外部に公開しない方針)。管理者ログイン済みなら閲覧可能。
_AUTH_EXEMPT_PREFIXES = (
    "/api/v1/auth/",
    "/healthz",
)
_AUTH_EXEMPT_EXACT = {"/"}


def _client_ip_from_request(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def auth_middleware(request: Request, call_next: Any) -> Response:
    """``/api/v1/*`` と OpenAPI ドキュメントを保護する。

    認証方式:
    1. ``Authorization: Bearer <key>`` ヘッダ (外部サーバー用、GET のみ)。
       不一致連発で 429 レート制限。
    2. ``session`` クッキー (管理画面 + OpenAPI docs 用、JWT)。
    どちらも失敗なら 401。``/api/v1/auth/*`` 等は完全に除外。
    """
    path = request.url.path
    if path in _AUTH_EXEMPT_EXACT or any(
        path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES
    ):
        response: Response = await call_next(request)
        return response

    if request.method == "OPTIONS":
        response = await call_next(request)
        return response

    needs_auth = path.startswith("/api/v1/") or path in {
        "/docs",
        "/redoc",
        "/openapi.json",
    }
    if needs_auth:
        # 1. 外部 API キー (Bearer)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            if request.method != "GET":
                return JSONResponse(
                    {"detail": "External API is read-only"}, status_code=405
                )
            ip = _client_ip_from_request(request)
            if is_external_api_rate_limited(ip):
                logger.warning("[ext-api] rate-limited ip=%s path=%s", ip, path)
                return JSONResponse(
                    {"detail": "Too many failed attempts."}, status_code=429
                )
            if not verify_external_api_key(auth_header):
                record_external_api_failure(ip)
                logger.info("[ext-api] invalid key ip=%s path=%s", ip, path)
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)
            logger.info("[ext-api] ok ip=%s path=%s", ip, path)
            response = await call_next(request)
            return response

        # 2. 管理画面用 cookie (OpenAPI docs もこちらで保護)
        token = request.cookies.get("session", "")
        if verify_jwt_token(token) is None:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    response = await call_next(request)
    return response


app.include_router(auth_router)
app.include_router(guilds_router)
app.include_router(stats_router)
app.include_router(ranking_router)
app.include_router(user_profile_router)
app.include_router(leveling_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": "level-bot", "status": "ok"}


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
