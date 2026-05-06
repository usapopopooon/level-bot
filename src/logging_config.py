"""Shared logging setup for bot / API processes.

両プロセスで同じフォーマット・出力先 (stdout) に揃えるため共通化する。
``LOG_LEVEL`` 環境変数 (DEBUG / INFO / WARNING / ERROR / CRITICAL) でレベル可変。
"""

from __future__ import annotations

import logging
import os
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging() -> None:
    """ルートロガーを stdout + 共通フォーマットで構成する。

    - 既に handler がついている場合 (uvicorn が先に仕込んだ等) は再設定しない
      ように ``force=True`` で上書きしておく。
    - 不正な ``LOG_LEVEL`` は INFO にフォールバック。
    """
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, None)
    if not isinstance(log_level, int):
        log_level = logging.INFO
        print(f"Warning: Invalid LOG_LEVEL '{log_level_name}', using INFO")

    logging.basicConfig(
        level=log_level,
        format=_LOG_FORMAT,
        stream=sys.stdout,
        force=True,
    )
