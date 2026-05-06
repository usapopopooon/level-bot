#!/bin/sh
# Bot + API を 1 コンテナで起動する場合のエントリポイント。
# Dockerfile のデフォルト CMD として使う。
#
# Railway 等で bot / api を別サービスに分ける場合は start-bot.sh / start-api.sh を
# それぞれ Custom Start Command に指定する。
#
# 注: python:3.12-slim の /bin/sh は dash で `wait -n` を持たないため、
# 子プロセスの監視は kill -0 + sleep のポーリングで行う (POSIX 互換)。
set -e

alembic upgrade head

bot_pid=""
api_pid=""

cleanup() {
    [ -n "$bot_pid" ] && kill "$bot_pid" 2>/dev/null || true
    [ -n "$api_pid" ] && kill "$api_pid" 2>/dev/null || true
}
trap cleanup TERM INT EXIT

python -m src.main &
bot_pid=$!

uvicorn src.web.app:app --host 0.0.0.0 --port "${PORT:-8000}" &
api_pid=$!

# どちらかが死ぬまで待機。死んだら trap で残りも止めて非ゼロ終了 → Railway 再起動。
while kill -0 "$bot_pid" 2>/dev/null && kill -0 "$api_pid" 2>/dev/null; do
    sleep 2
done

exit 1
