"""Alembic environment configuration."""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
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


# 複数コンテナが同時にマイグレーションを実行してもデッドロックしないよう、
# PostgreSQL の advisory lock で直列化する。値は固定の任意 64bit 整数。
_MIGRATION_ADVISORY_LOCK_KEY = 0x4C56_4C42_4F54  # ASCII "LVLBOT" 風


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # ハングしないようタイムアウトを設定 (60s 待っても lock 取れなければ失敗)
        connection.execute(text("SET lock_timeout = '60s'"))
        # advisory lock。同時に走っても先着優先で他はここで待機する。
        # 接続が閉じれば自動解放されるので zombie lock の心配なし。
        connection.execute(
            text("SELECT pg_advisory_lock(:k)").bindparams(
                k=_MIGRATION_ADVISORY_LOCK_KEY
            )
        )
        try:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:k)").bindparams(
                    k=_MIGRATION_ADVISORY_LOCK_KEY
                )
            )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
