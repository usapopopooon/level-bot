"""FastAPI application entry point.

公開ダッシュボード用の JSON API を提供する。フロントエンド (Next.js) は
``/api/v1/*`` を rewrite で叩くか、本番では同じ Railway プロジェクト内で
内部 URL から直接叩く。
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.web.routes import stats as stats_routes

logger = logging.getLogger(__name__)


def _parse_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    if not raw:
        return ["http://localhost:3000"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app = FastAPI(
    title="Level Bot Stats API",
    description="Public read-only API for Discord server statistics.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(stats_routes.router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": "level-bot", "status": "ok"}


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
