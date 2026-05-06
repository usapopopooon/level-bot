#!/bin/sh
# Bot + API を 1 コンテナで起動する場合のエントリポイント。
# Dockerfile のデフォルト CMD として使う。
#
# Railway 等で bot / api を別サービスに分ける場合は start-bot.sh / start-api.sh を
# それぞれ Custom Start Command に指定する。
set -e

alembic upgrade head

python -m src.main &
bot_pid=$!

uvicorn src.web.app:app --host 0.0.0.0 --port "${PORT:-8000}" &
api_pid=$!

# どちらかが落ちたらもう片方も停止し、終了コードを伝播する。
wait -n
exit_code=$?
kill "$bot_pid" "$api_pid" 2>/dev/null || true
exit "$exit_code"
