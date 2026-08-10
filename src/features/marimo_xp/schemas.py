from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MarimoXpEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    channel_id: str = Field(pattern=r"^\d+$")
    awarded_xp: int = Field(ge=1, le=1000)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class MarimoXpEventOut(BaseModel):
    event_id: str
    awarded_xp: int
    duplicate: bool
