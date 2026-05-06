#!/bin/sh
# Start the Discord bot worker. Long-running process, no public port.
#
# 起動前に毎回 alembic upgrade head を走らせる (start-api.sh と同じ理由)。
# 既に最新スキーマなら alembic は何もしない (no-op)。
set -e
alembic upgrade head
exec python -m src.main
