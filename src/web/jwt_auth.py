"""JWT 認証ユーティリティ。

セッションを HS256 で署名した JWT として ``session`` クッキーに格納する。
FastAPI 依存 ``get_current_user_jwt`` で payload を取り出せる。
"""

from __future__ import annotations

import time
from typing import Annotated, Any

import jwt
from fastapi import Cookie

from src.constants import SESSION_MAX_AGE_SECONDS
from src.web.security import SECRET_KEY

_ALGORITHM = "HS256"


def create_jwt_token(subject: str) -> str:
    """指定 ``subject`` の JWT を発行する (HS256)。"""
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + SESSION_MAX_AGE_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=_ALGORITHM)


def verify_jwt_token(token: str) -> dict[str, Any] | None:
    """JWT を検証して payload を返す。失敗時は None。"""
    if not token or not token.strip():
        return None
    try:
        payload: dict[str, Any] = jwt.decode(token, SECRET_KEY, algorithms=[_ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def get_current_user_jwt(
    session: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict[str, Any] | None:
    """FastAPI 依存: ``session`` クッキーから JWT payload を取り出す。"""
    if not session:
        return None
    return verify_jwt_token(session)
