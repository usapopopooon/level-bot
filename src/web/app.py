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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.features.guilds.routes import router as guilds_router
from src.features.ranking.routes import router as ranking_router
from src.features.stats.routes import router as stats_router
from src.features.user_profile.routes import router as user_profile_router
from src.logging_config import setup_logging
from src.migrations import run_migrations

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
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(guilds_router)
app.include_router(stats_router)
app.include_router(ranking_router)
app.include_router(user_profile_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": "level-bot", "status": "ok"}


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
