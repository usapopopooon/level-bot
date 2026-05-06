"""Bot entry point.

データベース接続を確認し、シグナルハンドラを登録した上で Bot を起動する。

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
import signal
import sys
from types import FrameType

from src.bot import LevelBot
from src.config import settings
from src.database.engine import check_database_connection_with_retry
from src.logging_config import setup_logging
from src.migrations import run_migrations

setup_logging()
logger = logging.getLogger(__name__)

_bot: LevelBot | None = None


def _handle_shutdown_signal(signum: int, _frame: FrameType | None) -> None:
    try:
        sig_name = signal.Signals(signum).name
    except ValueError:
        sig_name = str(signum)
    logger.info("Received %s, initiating graceful shutdown...", sig_name)

    if _bot is not None:
        try:
            asyncio.create_task(_shutdown_bot())
        except RuntimeError:
            logger.warning("Event loop not running, forcing shutdown")
            sys.exit(0)


async def _shutdown_bot() -> None:
    global _bot
    if _bot is not None:
        logger.info("Closing bot connection...")
        await _bot.close()
        logger.info("Bot closed successfully")


async def main() -> None:
    global _bot

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

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_shutdown_signal)
            logger.info("%s handler registered", sig.name)
        except (ValueError, OSError) as e:
            logger.warning("Could not register %s handler: %s", sig.name, e)

    if hasattr(signal, "SIGHUP"):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signal.SIGHUP, signal.SIG_IGN)

    if hasattr(signal, "SIGPIPE"):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    _bot = LevelBot()
    async with _bot:
        await _bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
