"""Tests for ``run_migrations()``.

実 Postgres コンテナに対して alembic upgrade head を流し、テーブルが
できることと、二度呼び出しても安全 (no-op) であることを確認する。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.database.models import Base
from src.migrations import run_migrations


@pytest_asyncio.fixture
async def empty_pg_url(postgres_url: str) -> AsyncIterator[str]:
    """全スキーマを drop した「真っさら」な PG URL を返す。

    db_session fixture は drop+create で常にスキーマを用意するが、
    こちらは ``alembic_version`` も含めて完全に消す。
    """
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    yield postgres_url


def _set_database_url(url: str) -> str | None:
    """env.py が読む DATABASE_URL を一時的に差し替える。元の値を返す。"""
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    return old


def _restore_database_url(old: str | None) -> None:
    if old is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old


async def _list_tables(url: str) -> set[str]:
    """``public`` スキーマの table 名を取得する。"""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {row[0] for row in result.fetchall()}
    finally:
        await engine.dispose()


async def test_run_migrations_creates_all_tables(empty_pg_url: str) -> None:
    """空 DB に対して呼ぶと、定義済み全テーブル + alembic_version が作られる。"""
    old = _set_database_url(empty_pg_url)
    try:
        run_migrations()
    finally:
        _restore_database_url(old)

    tables = await _list_tables(empty_pg_url)
    assert "alembic_version" in tables
    # 主要テーブルがすべて存在することを確認 (全列挙すると壊れやすいので主要のみ)
    assert "guilds" in tables
    assert "guild_settings" in tables
    assert "daily_stats" in tables
    assert "voice_sessions" in tables
    assert "user_meta" in tables
    assert "channel_meta" in tables
    assert "excluded_channels" in tables
    assert "role_meta" in tables
    assert "level_role_awards" in tables


async def test_run_migrations_is_idempotent(empty_pg_url: str) -> None:
    """二度呼んでも例外を出さない (二度目は no-op)。"""
    old = _set_database_url(empty_pg_url)
    try:
        run_migrations()
        run_migrations()
    finally:
        _restore_database_url(old)

    tables = await _list_tables(empty_pg_url)
    assert "alembic_version" in tables
