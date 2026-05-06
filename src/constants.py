"""Application constants."""

# =============================================================================
# Embed defaults
# =============================================================================

DEFAULT_EMBED_COLOR = 0x5865F2  # Discord blurple

# =============================================================================
# Application basics
# =============================================================================

APP_NAME = "level-bot"
DB_NAME = APP_NAME.replace("-", "_")
TEST_DB_NAME = f"{DB_NAME}_test"

# =============================================================================
# Default database URLs (overridden by DATABASE_URL env var in production)
# =============================================================================

DEFAULT_DATABASE_URL = f"postgresql+asyncpg://user:password@localhost/{DB_NAME}"
DEFAULT_TEST_DATABASE_URL = (
    f"postgresql+asyncpg://user:password@localhost/{TEST_DB_NAME}"
)
DEFAULT_TEST_DATABASE_URL_SYNC = f"postgresql://user:password@localhost/{TEST_DB_NAME}"

# =============================================================================
# Database connection pool defaults
# =============================================================================

DEFAULT_DB_POOL_SIZE = 5
DEFAULT_DB_MAX_OVERFLOW = 10

# =============================================================================
# Stats tracking
# =============================================================================

# Bot メッセージ・空メッセージなどはカウントに含めない
MIN_MESSAGE_LENGTH = 1

# 1 日 = 86400 秒。バリデーション用
SECONDS_PER_DAY = 86400

# Voice セッションの最大持続時間 (秒)。Bot 落ち時の暴走防止クランプ
MAX_VOICE_SESSION_SECONDS = 24 * 60 * 60

# Leaderboard のデフォルト件数
DEFAULT_LEADERBOARD_LIMIT = 10
MAX_LEADERBOARD_LIMIT = 50

# Web ダッシュボードのデフォルト表示日数
DEFAULT_DASHBOARD_DAYS = 30
MAX_DASHBOARD_DAYS = 365

# =============================================================================
# Alembic
# =============================================================================

# bot/api が同時に migrate を走らせても直列化されるよう、PG advisory lock のキー。
# 値は任意の固定 64bit 整数。"LVLBOT" 風の ASCII。
MIGRATION_ADVISORY_LOCK_KEY = 0x4C564C424F54

# advisory lock 待ちのタイムアウト。重い migration でも余裕を見て 5 分。
MIGRATION_LOCK_TIMEOUT = "300s"
