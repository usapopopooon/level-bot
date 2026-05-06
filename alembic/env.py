"""Alembic environment configuration."""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from src.constants import MIGRATION_ADVISORY_LOCK_KEY, MIGRATION_LOCK_TIMEOUT
from src.database.models import Base

config = context.config

# disable_existing_loggers=False で起動時に bot/api 側で構成済みのロガーを
# 殺さないようにする (デフォルト True だと root 含め全ロガーが reset される)。
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# DATABASE_URL があれば alembic.ini を上書き
database_url = os.environ.get("DATABASE_URL")
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    elif database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    config.set_main_option("sqlalchemy.url", database_url)
else:
    from src.config import settings

    sync_url = settings.async_database_url.replace("+asyncpg", "")
    config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # SET / advisory lock は migration 用 transaction より外側で実行する。
        # SQLAlchemy 2.0 の autobegin で暗黙トランザクションが開いたままだと
        # context.begin_transaction() が機能せず、migration が rollback される。
        # 明示 commit して以降は alembic に委ねる (lock_timeout / advisory lock は
        # session レベルの設定なので commit しても残る)。
        connection.execute(text(f"SET lock_timeout = '{MIGRATION_LOCK_TIMEOUT}'"))
        connection.execute(
            text("SELECT pg_advisory_lock(:k)").bindparams(
                k=MIGRATION_ADVISORY_LOCK_KEY
            )
        )
        connection.commit()

        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            # advisory lock は session スコープ。connection 終了時にも自動解放される
            # が、明示的に外しておく方が pg_locks が綺麗。
            connection.execute(
                text("SELECT pg_advisory_unlock(:k)").bindparams(
                    k=MIGRATION_ADVISORY_LOCK_KEY
                )
            )
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
