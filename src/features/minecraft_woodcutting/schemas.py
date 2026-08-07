from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class MinecraftWoodcuttingComboEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    minecraft_account_id: str = Field(min_length=1, max_length=128)
    log_count: int = Field(gt=0)
    combo_count: int = Field(ge=1)
    reward_xp: int = Field(gt=0, le=10_000)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class MinecraftWoodcuttingComboEventOut(BaseModel):
    event_id: str
    log_count: int
    combo_count: int
    reward_xp: int
    duplicate: bool
