#!/bin/sh
# Start FastAPI (level-bot stats API).
# alembic upgrade は src/web/app.py の lifespan で起動時に走る。
set -e
exec uvicorn src.web.app:app --host 0.0.0.0 --port "${PORT:-8000}"
