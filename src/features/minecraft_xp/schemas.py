from datetime import date, datetime
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


class MinecraftXpExchangeOut(BaseModel):
    id: int
    event_id: str
    guild_id: str
    user_id: str
    minecraft_account_id: str
    cost_xp: int
    reward_xp: int
    status: Literal["pending", "delivering"]


class MinecraftXpExchangeActionIn(BaseModel):
    guild_id: str = Field(pattern=r"^\d+$")
    claim_token: str | None = Field(default=None, min_length=1, max_length=64)


class MinecraftXpShopWalletOut(BaseModel):
    total_xp: int
    spent_xp: int
    available_xp: int


class MinecraftXpShopPackOut(BaseModel):
    cost_xp: int
    reward_xp: int


class MinecraftXpShopOut(BaseModel):
    wallet: MinecraftXpShopWalletOut
    packs: list[MinecraftXpShopPackOut]


class MinecraftXpShopExchangeIn(BaseModel):
    request_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    cost_xp: int = Field(gt=0)
    expected_reward_xp: int = Field(gt=0)


class MinecraftXpShopExchangeOut(BaseModel):
    status: Literal["reserved", "offline", "insufficient_xp", "unavailable"]
    message: str
    wallet_before: MinecraftXpShopWalletOut
    wallet_after: MinecraftXpShopWalletOut
    pack: MinecraftXpShopPackOut | None


class MinecraftResourcePackOut(BaseModel):
    item_id: Literal["minecraft:diamond", "minecraft:emerald"]
    item_name: str
    item_count: int = Field(gt=0)
    cost_xp: int = Field(gt=0)


class MinecraftResourceShopOut(BaseModel):
    wallet: MinecraftXpShopWalletOut
    packs: list[MinecraftResourcePackOut]


class MinecraftResourceShopExchangeIn(BaseModel):
    request_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    item_id: Literal["minecraft:diamond", "minecraft:emerald"]
    item_count: int = Field(gt=0, le=64)
    expected_cost_xp: int = Field(gt=0)


class MinecraftResourceShopExchangeOut(BaseModel):
    status: Literal["reserved", "offline", "insufficient_xp", "unavailable"]
    message: str
    wallet_before: MinecraftXpShopWalletOut
    wallet_after: MinecraftXpShopWalletOut
    pack: MinecraftResourcePackOut | None


class MinecraftResourceExchangeOut(BaseModel):
    id: int
    event_id: str
    guild_id: str
    user_id: str
    minecraft_account_id: str
    item_id: Literal["minecraft:diamond", "minecraft:emerald"]
    item_name: str
    item_count: int
    cost_xp: int
    status: Literal["pending", "delivering"]


class MinecraftItemGachaOut(BaseModel):
    cost_xp: int = Field(gt=0)
    wallet: MinecraftXpShopWalletOut


class MinecraftItemGachaSpendIn(BaseModel):
    request_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
    minecraft_account_id: str = Field(min_length=1, max_length=128)
    draw_day: date
    expected_cost_xp: int = Field(gt=0)


class MinecraftItemGachaSpendOut(BaseModel):
    status: Literal[
        "reserved", "completed", "offline", "insufficient_xp", "unavailable"
    ]
    message: str
    cost_xp: int = Field(gt=0)
    wallet_before: MinecraftXpShopWalletOut
    wallet_after: MinecraftXpShopWalletOut


class MinecraftItemGachaSpendActionIn(BaseModel):
    guild_id: str = Field(pattern=r"^\d+$")
    user_id: str = Field(pattern=r"^\d+$")
