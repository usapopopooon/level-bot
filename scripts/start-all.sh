#!/bin/sh
# Bot + API を 1 コンテナで起動する場合のエントリポイント。
# Dockerfile のデフォルト CMD として使う。
#
# alembic upgrade は bot (src/main.py) と api (lifespan) のどちらか先に
# 起動した側が advisory lock を取って実行し、もう片方は no-op する。
#
# python:3.12-slim の /bin/sh は dash で `wait -n` を持たないため、
# 子プロセスの監視は kill -0 + sleep のポーリングで行う (POSIX 互換)。
set -e

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
