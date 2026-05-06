#!/bin/sh
# Start the Discord bot worker. Long-running process, no public port.
# alembic upgrade は src/main.py で起動時に走る。
set -e
exec python -m src.main
