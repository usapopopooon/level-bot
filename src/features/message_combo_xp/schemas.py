from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MessageComboXpEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    channel_id: str = Field(pattern=r"^\d+$")
    config_id: str = Field(min_length=1, max_length=64)
    streak_days: int = Field(ge=1)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            msg = "observed_at must include a timezone"
            raise ValueError(msg)
        return value


class MessageComboXpEventOut(BaseModel):
    event_id: str
    streak_days: int
    awarded_xp: int
    duplicate: bool
