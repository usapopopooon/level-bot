"""SQLAlchemy async engine setup.

非同期エンジンとセッションファクトリを作成する。Bot と Web 両方で共有される。
"""

import asyncio
import logging
import os
import ssl
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.constants import DEFAULT_DB_MAX_OVERFLOW, DEFAULT_DB_POOL_SIZE
from src.database.models import Base

logger = logging.getLogger(__name__)

CONNECTION_TIMEOUT = 10
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


def _parse_int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(
            "Invalid value for %s: %r (expected integer). Using default: %d",
            name,
            value,
            default,
        )
        return default


POOL_SIZE = _parse_int_env("DB_POOL_SIZE", DEFAULT_DB_POOL_SIZE)
MAX_OVERFLOW = _parse_int_env("DB_MAX_OVERFLOW", DEFAULT_DB_MAX_OVERFLOW)
DATABASE_REQUIRE_SSL = os.environ.get("DATABASE_REQUIRE_SSL", "").lower() == "true"


def _get_connect_args() -> dict[str, Any]:
    """asyncpg 用の接続引数。Railway/Heroku Postgres では SSL を有効化。"""
    connect_args: dict[str, Any] = {}
    if DATABASE_REQUIRE_SSL:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_context
        logger.info("Database SSL enabled")
    return connect_args


engine = create_async_engine(
    settings.async_database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    connect_args=_get_connect_args(),
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """テーブルを作成する。Alembic を使う前のローカル動作確認用。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_database_connection(
    timeout: float = CONNECTION_TIMEOUT,
    retries: int = 1,
    retry_delay: float = RETRY_DELAY,
) -> bool:
    """``SELECT 1`` で接続を確認する。リトライ付き。"""

    async def _check() -> bool:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    url = settings.database_url
    db_host = url.split("@")[-1] if "@" in url else "unknown"

    for attempt in range(1, retries + 1):
        try:
            await asyncio.wait_for(_check(), timeout=timeout)
            logger.info("Database connection successful")
            return True
        except TimeoutError:
            logger.warning(
                "Database connection timed out (attempt %d/%d) at %s",
                attempt,
                retries,
                db_host,
            )
        except Exception as e:
            logger.exception(
                "Failed to connect to database (attempt %d/%d) at %s: %s",
                attempt,
                retries,
                db_host,
                e,
            )

        if attempt < retries:
            logger.info("Retrying in %s seconds...", retry_delay)
            await asyncio.sleep(retry_delay)

    logger.error("Database connection failed after %d attempts at %s", retries, db_host)
    return False


async def check_database_connection_with_retry() -> bool:
    """Bot 起動時に使う、デフォルト回数リトライ付きの接続確認。"""
    return await check_database_connection(retries=MAX_RETRIES)
