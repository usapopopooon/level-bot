"""Application settings loaded from environment / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.constants import DEFAULT_DATABASE_URL


class Settings(BaseSettings):
    """環境変数 / .env から設定を読み込む。

    DISCORD_TOKEN は bot プロセスのみ必須。API は DB 接続だけで動くため、
    必須チェックはここではせず、bot 起動コード (src/main.py) で行う。
    Heroku/Railway 形式の ``postgres://`` URL は asyncpg 用に自動変換する。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # bot 専用。API では未設定で OK
    discord_token: str = ""

    # --- Database ---
    database_url: str = DEFAULT_DATABASE_URL

    # --- Runtime ---
    timezone_offset: int = 9  # JST デフォルト
    app_url: str = "http://localhost:8000"

    # --- Web dashboard ---
    public_dashboard: bool = True

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
