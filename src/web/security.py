"""Web 認証ユーティリティ。

責務:
    - ``SECRET_KEY``: JWT 署名鍵 (環境変数 ``SESSION_SECRET_KEY`` または乱数)
    - ``verify_admin_credentials``: 単一管理者の資格情報照合 (定数時間比較)

シングル管理者前提のシンプル設計。複数ユーザー化したくなったら DB 化する。
"""

from __future__ import annotations

import hmac
import logging
import secrets

from src.config import settings

logger = logging.getLogger(__name__)

# JWT 署名鍵。未設定で起動した場合は起動毎に乱数を生成するため、
# 再起動でセッションが無効化される。本番では SESSION_SECRET_KEY を必ず設定する。
_session_secret_from_env = settings.session_secret_key.strip()
if not _session_secret_from_env:
    logger.warning(
        "SESSION_SECRET_KEY is not set. Using a random key. "
        "Sessions will be invalidated on restart."
    )
    SECRET_KEY: str = secrets.token_hex(32)
else:
    SECRET_KEY = _session_secret_from_env

ADMIN_USER: str = (settings.admin_user or "").strip()
ADMIN_PASSWORD: str = settings.admin_password
SECURE_COOKIE: bool = settings.secure_cookie


def verify_admin_credentials(user: str, password: str) -> bool:
    """環境変数の単一管理者と入力を定数時間比較する。

    ADMIN_USER / ADMIN_PASSWORD のいずれかが空のときは常に失敗。
    """
    if not ADMIN_USER or not ADMIN_PASSWORD:
        return False
    user_ok = hmac.compare_digest(user, ADMIN_USER)
    pw_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
    return user_ok and pw_ok
