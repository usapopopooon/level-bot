from datetime import datetime
from typing import Literal

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
    daily_limit: int | None
    duplicate: bool


class MinecraftVoiceHeartbeatIn(BaseModel):
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    minecraft_account_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_heartbeat_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            msg = "observed_at must include a timezone"
            raise ValueError(msg)
        return value


class MinecraftVoiceHeartbeatOut(BaseModel):
    awarded_bonus_seconds: int
    bonus_active: bool
    duplicate: bool


class MinecraftLevelUpEventOut(BaseModel):
    id: int
    guild_id: str
    guild_name: str
    user_id: str
    display_name: str
    level: int
    minecraft_delivered: bool
    discord_delivered: bool


class MinecraftLevelUpAckIn(BaseModel):
    guild_id: str = Field(pattern=r"^\d+$")
    destination: Literal["minecraft", "discord"]
