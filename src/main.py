"""Bot entry point.

データベース接続を確認し、シグナルハンドラを登録した上で Bot を起動する。
Discord の長期障害で接続が完全に途切れた場合に備え、外側に
指数バックオフ付きの再接続ループを持つ (discord.py 内部の reconnect が
諦めたケースや login() 段階での 5xx を救う)。

Examples:
    実行::

        python -m src.main

環境変数:
    - DISCORD_TOKEN: Discord Bot トークン (必須)
    - DATABASE_URL: PostgreSQL 接続 URL (必須)
    - LOG_LEVEL: ログレベル (デフォルト: INFO)
"""

import asyncio
import contextlib
import logging
import random
import signal
import sys
import time

import aiohttp
import discord

from src.bot import LevelBot
from src.config import settings
from src.database.engine import check_database_connection_with_retry
from src.logging_config import setup_logging
from src.migrations import run_migrations

setup_logging()
logger = logging.getLogger(__name__)

# Discord 長期障害時の再接続バックオフ設定。
# discord.py 内部のリコネクトはあるが、login() 段階の 5xx や WebSocket が
# 諦めて例外で抜けたケースは外側で拾う必要がある。
DISCORD_RECONNECT_BASE_DELAY = 5.0
DISCORD_RECONNECT_MAX_DELAY = 600.0  # 10 分
DISCORD_RECONNECT_JITTER_RATIO = 0.25
# これ以上連続接続できていれば「復旧した」と見なしバックオフをリセットする。
DISCORD_STABLE_RUN_SECONDS = 60.0

_bot: LevelBot | None = None


def _backoff_sleep_seconds(delay: float) -> float:
    """指数バックオフに ±JITTER_RATIO のジッタを乗せる。下限は BASE_DELAY。"""
    jitter = delay * DISCORD_RECONNECT_JITTER_RATIO * (random.random() * 2 - 1)
    return max(DISCORD_RECONNECT_BASE_DELAY, delay + jitter)


def _is_fatal_discord_error(exc: BaseException) -> bool:
    """再試行しても回復しない認証/権限系エラーか判定する。"""
    if isinstance(exc, discord.LoginFailure | discord.PrivilegedIntentsRequired):
        return True
    return isinstance(exc, discord.HTTPException) and exc.status in (401, 403)


async def _run_bot_with_backoff(shutdown_event: asyncio.Event) -> None:
    """Discord 接続を維持するメインループ。障害時は指数バックオフで再接続する。"""
    global _bot

    delay = DISCORD_RECONNECT_BASE_DELAY

    while not shutdown_event.is_set():
        _bot = LevelBot()

        # シャットダウン要求が来たら bot.close() を呼んで start() を正常復帰させる。
        async def _watch_shutdown(bot: LevelBot) -> None:
            await shutdown_event.wait()
            if not bot.is_closed():
                logger.info("Shutdown requested, closing bot connection...")
                await bot.close()

        watcher = asyncio.create_task(_watch_shutdown(_bot))
        start_time = time.monotonic()
        clean_exit = False

        try:
            async with _bot:
                await _bot.start(settings.discord_token)
            clean_exit = True
        except BaseException as exc:
            if _is_fatal_discord_error(exc):
                logger.exception("Fatal Discord error; not retrying")
                raise

            elapsed = time.monotonic() - start_time
            # 安定動作後の障害ならバックオフをリセットする。
            if elapsed >= DISCORD_STABLE_RUN_SECONDS:
                delay = DISCORD_RECONNECT_BASE_DELAY

            if shutdown_event.is_set():
                logger.info("Bot stopped during shutdown (%s)", type(exc).__name__)
                break

            if isinstance(
                exc,
                discord.GatewayNotFound
                | discord.ConnectionClosed
                | discord.HTTPException
                | aiohttp.ClientError
                | OSError
                | TimeoutError,
            ):
                sleep_for = _backoff_sleep_seconds(delay)
                logger.warning(
                    "Discord connection lost after %.1fs (%s: %s); "
                    "reconnecting in %.1fs",
                    elapsed,
                    type(exc).__name__,
                    exc,
                    sleep_for,
                )
                # シャットダウンを待ちつつ sleep。シグナル到達で即抜ける。
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(shutdown_event.wait(), timeout=sleep_for)
                delay = min(delay * 2, DISCORD_RECONNECT_MAX_DELAY)
            else:
                # 想定外の例外は上に投げて落とす。プロセスマネージャに任せる。
                raise
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            _bot = None

        if clean_exit:
            # bot.close() が正規ルートで呼ばれて start() が抜けた = シャットダウン。
            break


async def main() -> None:
    # DISCORD_TOKEN は bot プロセスのみ必須。Settings 側で validate せず
    # ここで明示チェックする (API サービスは未設定でも起動できるようにするため)。
    if not settings.discord_token or not settings.discord_token.strip():
        logger.error(
            "DISCORD_TOKEN environment variable is required. "
            "Get your bot token from https://discord.com/developers/applications"
        )
        sys.exit(1)

    if not await check_database_connection_with_retry():
        logger.error(
            "Cannot start bot: Database connection failed. "
            "Check DATABASE_URL and ensure the database is running."
        )
        sys.exit(1)

    # 起動経路に依存せず確実にスキーマを最新にする (advisory lock で並列 safe)
    try:
        run_migrations()
    except Exception:
        logger.exception("Alembic migration failed; aborting bot startup")
        sys.exit(1)

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _request_shutdown(sig: signal.Signals) -> None:
        logger.info("Received %s, initiating graceful shutdown...", sig.name)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig)
            logger.info("%s handler registered", sig.name)
        except (NotImplementedError, ValueError, OSError) as e:
            logger.warning("Could not register %s handler: %s", sig.name, e)

    if hasattr(signal, "SIGHUP"):
        with contextlib.suppress(NotImplementedError, ValueError, OSError):
            loop.add_signal_handler(signal.SIGHUP, lambda: None)

    if hasattr(signal, "SIGPIPE"):
        with contextlib.suppress(NotImplementedError, ValueError, OSError):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    await _run_bot_with_backoff(shutdown_event)


if __name__ == "__main__":
    asyncio.run(main())
