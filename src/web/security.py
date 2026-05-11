"""Web 認証ユーティリティ。

責務:
    - ``SECRET_KEY``: JWT 署名鍵 (環境変数 ``SESSION_SECRET_KEY`` または乱数)
    - ``verify_admin_credentials``: 単一管理者の資格情報照合 (定数時間比較)
    - ``verify_external_api_key``: Bearer ヘッダ照合 (server-to-server)
    - ログイン試行 / 外部 API キー失敗のレート制限 (in-memory)

シングル管理者前提のシンプル設計。複数ユーザー化したくなったら DB 化する。
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time

from src.config import settings
from src.constants import (
    EXTERNAL_API_MAX_FAILURES,
    EXTERNAL_API_WINDOW_SECONDS,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
)

logger = logging.getLogger(__name__)

# JWT 署名鍵。未設定だと起動毎に乱数 (再起動で全セッション失効)。
# 本番では SESSION_SECRET_KEY を必ず設定する。
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
EXTERNAL_API_KEY: str = settings.external_api_key


def verify_admin_credentials(user: str, password: str) -> bool:
    """環境変数の単一管理者と入力を定数時間比較する。

    ADMIN_USER / ADMIN_PASSWORD のいずれかが空のときは常に失敗。
    """
    if not ADMIN_USER or not ADMIN_PASSWORD:
        return False
    user_ok = hmac.compare_digest(user, ADMIN_USER)
    pw_ok = hmac.compare_digest(password, ADMIN_PASSWORD)
    return user_ok and pw_ok


def verify_external_api_key(authorization_header: str | None) -> bool:
    """``Authorization: Bearer <key>`` ヘッダを ``EXTERNAL_API_KEY`` と照合する。

    フォーマット違反 / キー未設定 / 不一致は False。定数時間比較。
    """
    if not authorization_header or not EXTERNAL_API_KEY:
        return False
    scheme, _, token = authorization_header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    token = token.strip()
    if not token:
        return False
    return hmac.compare_digest(token, EXTERNAL_API_KEY)


# ---------------------------------------------------------------------------
# レート制限 (in-memory)
# プロセス単位。スケールアウト時は外部 store (Redis 等) に切り替え必要。
# ---------------------------------------------------------------------------


def _window_check(
    store: dict[str, list[float]],
    key: str,
    *,
    max_attempts: int,
    window_seconds: int,
) -> bool:
    """``key`` の試行回数が ``window_seconds`` 内に ``max_attempts`` 以上か。"""
    now = time.time()
    attempts = store.get(key)
    if not attempts:
        return False
    valid = [t for t in attempts if now - t < window_seconds]
    if len(valid) != len(attempts):
        if valid:
            store[key] = valid
        else:
            del store[key]
    return len(valid) >= max_attempts


def _window_record(store: dict[str, list[float]], key: str) -> None:
    if not key:
        return
    store.setdefault(key, []).append(time.time())


# ---- Login attempts ----

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def is_login_rate_limited(ip: str) -> bool:
    """``ip`` がログインを連続失敗してロック中か。"""
    return _window_check(
        _LOGIN_ATTEMPTS,
        ip,
        max_attempts=LOGIN_MAX_ATTEMPTS,
        window_seconds=LOGIN_WINDOW_SECONDS,
    )


def record_failed_login(ip: str) -> None:
    _window_record(_LOGIN_ATTEMPTS, ip)


def clear_login_attempts(ip: str) -> None:
    """成功時に呼び、レコードを消す (再ログインを邪魔しない)。"""
    _LOGIN_ATTEMPTS.pop(ip, None)


# ---- External API key failures ----

_EXT_API_FAILURES: dict[str, list[float]] = {}


def is_external_api_rate_limited(ip: str) -> bool:
    return _window_check(
        _EXT_API_FAILURES,
        ip,
        max_attempts=EXTERNAL_API_MAX_FAILURES,
        window_seconds=EXTERNAL_API_WINDOW_SECONDS,
    )


def record_external_api_failure(ip: str) -> None:
    _window_record(_EXT_API_FAILURES, ip)


# ---------------------------------------------------------------------------
# 起動時の安全性チェック
# ---------------------------------------------------------------------------


def check_production_safety() -> None:
    """本番起動前に必要な env が設定されているか検証する。

    ``ENVIRONMENT`` または ``RAILWAY_ENVIRONMENT_NAME`` が ``production`` の場合:
    - ``SESSION_SECRET_KEY`` 必須 (空だと再起動で全セッション失効)
    - ``ADMIN_PASSWORD`` 必須 (空だとログイン不能)
    - ``CORS_ORIGINS`` 必須 (空だと localhost からしか叩けない)

    開発/テスト環境では警告のみ。
    """
    import os

    env_name = (
        os.environ.get("ENVIRONMENT", "")
        or os.environ.get("RAILWAY_ENVIRONMENT_NAME", "")
    ).lower()
    is_production = env_name == "production"

    missing: list[str] = []
    if not _session_secret_from_env:
        missing.append("SESSION_SECRET_KEY")
    if not ADMIN_PASSWORD:
        missing.append("ADMIN_PASSWORD")
    if not os.environ.get("CORS_ORIGINS", "").strip():
        missing.append("CORS_ORIGINS")

    if missing:
        msg = (
            f"Required env vars missing or empty: {', '.join(missing)}. "
            "See .env.example."
        )
        if is_production:
            raise RuntimeError(msg)
        logger.warning("[startup] %s (continuing in dev mode)", msg)
