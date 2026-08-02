from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MinecraftXpEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    minecraft_account_id: str = Field(min_length=1, max_length=128)
    minecraft_xp: int = Field(gt=0, le=10_000_000)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            msg = "observed_at must include a timezone"
            raise ValueError(msg)
        return value


class MinecraftXpEventOut(BaseModel):
    event_id: str
    minecraft_xp: int
    awarded_xp: int
    daily_awarded_xp: int
    daily_limit: int
    duplicate: bool
