"""Programmatic alembic migration runner.

Bot / API いずれの起動パスからでも、起動時に確実にマイグレーションを
適用するためのヘルパー。Railway / Heroku の Dockerfile builder には
release phase の自動実行がないため、起動コードに組み込んでおく。

alembic は PostgreSQL の advisory lock を内部的に使うため、複数コンテナで
同時に呼んでも直列化される (片方が待つだけ)。
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """``alembic upgrade head`` をプロセス内で実行する。

    Raises:
        Exception: マイグレーション失敗時はそのまま伝播する。
            起動を止める判断は呼び出し側に任せる。
    """
    # alembic.ini はリポジトリ / コンテナのルートに置かれている前提
    project_root = Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        logger.warning("alembic.ini not found at %s; skipping migrations", alembic_ini)
        return

    cfg = Config(str(alembic_ini))
    # alembic/ ディレクトリは alembic.ini と同階層
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    logger.info("Running alembic upgrade head...")
    command.upgrade(cfg, "head")
    logger.info("Alembic migrations complete")
