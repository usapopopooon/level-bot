"""Application settings loaded from environment / .env file."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.constants import DEFAULT_DATABASE_URL


class Settings(BaseSettings):
    """環境変数 / .env から設定を読み込む。

    - Bot トークン (DISCORD_TOKEN) が未設定なら起動を拒否する。
    - Heroku/Railway 形式の ``postgres://`` を asyncpg 用に自動変換する。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Required ---
    discord_token: str = ""

    # --- Database ---
    database_url: str = DEFAULT_DATABASE_URL

    # --- Runtime ---
    timezone_offset: int = 9  # JST デフォルト
    app_url: str = "http://localhost:8000"

    # --- Web dashboard ---
    public_dashboard: bool = True

    @model_validator(mode="after")
    def _validate_required(self) -> "Settings":
        if not self.discord_token or not self.discord_token.strip():
            raise ValueError(
                "DISCORD_TOKEN environment variable is required. "
                "Get your bot token from https://discord.com/developers/applications"
            )
        return self

    @property
    def async_database_url(self) -> str:
        """SQLAlchemy 非同期エンジン用に URL を asyncpg ドライバ形式に正規化する。"""
        url = self.database_url
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
