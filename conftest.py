"""Test fixtures backed by a real PostgreSQL container (testcontainers).

なぜ Postgres か:
    集計クエリは ``ON CONFLICT DO UPDATE`` (PG 専用) を使った upsert を行うため、
    sqlite では再現できない。挙動を本番と一致させたいので、テストでも本物の
    Postgres を Docker 経由で立てる。

仕組み:
    - session スコープ: PG コンテナを 1 度だけ起動し全テストで共有
    - function スコープ: 毎テスト ``drop_all`` + ``create_all`` でクリーンスレート
"""

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, date

# import 前に必須環境変数を埋めておく (src.config / src.database.engine のロード対策)。
# PG 接続 URL は postgres_url fixture で実際のコンテナ URL に置き換わるが、
# ここで dummy URL をセットしておかないと engine.py の create_async_engine が
# 立ち上がらないため必要。
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/dummy"
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer  # noqa: E402

from src.database.models import Base  # noqa: E402
from src.database.models import LevelXpWeightLog  # noqa: E402


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Pytest セッション共有の Postgres コンテナ URL を返す。

    Docker daemon が必要。CI でも GitHub Actions のデフォルト環境で動く。
    """
    with PostgresContainer("postgres:16-alpine") as pg:
        sync_url = pg.get_connection_url()
        # testcontainers は psycopg2 形式で返すので asyncpg に揃える
        async_url = sync_url.replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        ).replace("postgresql://", "postgresql+asyncpg://")
        yield async_url


@pytest_asyncio.fixture
async def db_session(postgres_url: str) -> AsyncIterator[AsyncSession]:
    """毎テストでスキーマを drop/create したクリーンな AsyncSession を返す。

    drop_all → create_all をテスト毎に行うので、テスト間でレコードが
    漏れることはない。同時並列実行 (xdist) には未対応。
    """
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Alembic seed を使わない create_all テストでも、運用同等の重みログを用意する。
        session.add_all(
            [
                LevelXpWeightLog(
                    effective_from=date(1970, 1, 1),
                    message_weight=2.0,
                    reaction_received_weight=0.5,
                    reaction_given_weight=0.5,
                    created_at=datetime.now(UTC),
                ),
                LevelXpWeightLog(
                    effective_from=date(2026, 5, 17),
                    message_weight=30.0,
                    reaction_received_weight=20.0,
                    reaction_given_weight=20.0,
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()
