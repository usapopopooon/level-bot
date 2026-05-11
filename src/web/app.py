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
from src.web.security import verify_external_api_key

setup_logging()
logger = logging.getLogger(__name__)


def _parse_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    if not raw:
        return ["http://localhost:3000"]
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """API 起動時にスキーマを最新にする (Railway 等 release phase 不在環境向け)。"""
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


# 認証が不要なパス (公開エンドポイント + auth API 自身 + ヘルスチェック)
_AUTH_EXEMPT_PREFIXES = (
    "/api/v1/auth/",
    "/healthz",
    "/docs",
    "/openapi.json",
    "/redoc",
)
_AUTH_EXEMPT_EXACT = {"/"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next: Any) -> Response:
    """``/api/v1/*`` を保護する。

    認証方式:
    1. ``Authorization: Bearer <key>`` ヘッダ (外部サーバー用、GET のみ)。
       一致すれば cookie 不要で通す。一致しなければ 401。
    2. ``session`` クッキー (管理画面用、JWT)。
    どちらも失敗なら 401。``/api/v1/auth/*`` 等は完全に除外。
    """
    path = request.url.path
    if path in _AUTH_EXEMPT_EXACT or any(
        path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES
    ):
        response: Response = await call_next(request)
        return response

    if path.startswith("/api/v1/"):
        # 1. 外部 API キー (Bearer)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            if request.method != "GET":
                return JSONResponse(
                    {"detail": "External API is read-only"}, status_code=405
                )
            if not verify_external_api_key(auth_header):
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)
            response = await call_next(request)
            return response

        # 2. 管理画面用 cookie
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
