"""Programmatic alembic migration runner.

Bot / API いずれの起動パスからでも、起動時に確実にマイグレーションを
適用するためのヘルパー。Railway / Heroku の Dockerfile builder には
release phase の自動実行がないため、起動コードに組み込んでおく。

並列実行 (bot と api 同時起動) は alembic env.py の advisory lock で直列化される。
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command
from src.logging_config import setup_logging

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """``alembic upgrade head`` をプロセス内で実行する。

    Raises:
        FileNotFoundError: alembic.ini が見当たらない場合。
            Docker イメージには必ず同梱しているので本番では発生しない。
        Exception: マイグレーション失敗時はそのまま伝播する。
            起動を止める判断は呼び出し側に任せる。
    """
    project_root = Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        raise FileNotFoundError(
            f"alembic.ini not found at {alembic_ini}. Migrations cannot run without it."
        )

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    logger.info("Running alembic upgrade head...")
    command.upgrade(cfg, "head")
    # alembic env.py の fileConfig が root logger を上書きしてしまうので戻す。
    # これをやらないと、以降の bot/api ログが alembic.ini の format になる。
    setup_logging()
    logger.info("Alembic migrations complete")
