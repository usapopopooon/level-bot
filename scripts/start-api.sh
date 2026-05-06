#!/bin/sh
# Start FastAPI (level-bot stats API).
# PORT は Railway / Heroku が注入する。未設定なら 8000 にフォールバック。
set -e
exec uvicorn src.web.app:app --host 0.0.0.0 --port "${PORT:-8000}"
