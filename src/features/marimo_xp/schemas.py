from datetime import datetime
from typing import Literal

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


class MarimoRevivalSpendIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    channel_id: str = Field(pattern=r"^\d+$")
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class MarimoRevivalSpendOut(BaseModel):
    event_id: str
    status: Literal["charged", "insufficient_xp"]
    cost_xp: int
    remaining_xp: int
    duplicate: bool


class MarimoRevivalItemSpendIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    channel_id: str = Field(pattern=r"^\d+$")
    card_key: Literal["moss-cola"]
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class MarimoRevivalItemSpendOut(BaseModel):
    event_id: str
    status: Literal["consumed", "insufficient_item"]
    card_key: Literal["moss-cola"]
    remaining_count: int
    duplicate: bool
