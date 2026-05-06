#!/bin/sh
# Start FastAPI (level-bot stats API).
#
# Railway / Heroku の Dockerfile builder には自動 release phase がないので、
# 起動前に毎回 alembic upgrade head を走らせる。
# alembic は PostgreSQL の advisory lock を使うため、bot コンテナと同時に
# 走っても直列化されるので safe (片方が待つだけ)。
set -e
alembic upgrade head
exec uvicorn src.web.app:app --host 0.0.0.0 --port "${PORT:-8000}"
