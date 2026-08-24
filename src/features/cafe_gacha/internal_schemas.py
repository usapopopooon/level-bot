"""Schemas for the trusted Cafe Collection bot API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CafeActorIn(BaseModel):
    guild_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    user_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    role_ids: list[str] = Field(default_factory=list, max_length=100)
    can_manage_guild: bool = False

    @field_validator("role_ids")
    @classmethod
    def validate_role_ids(cls, values: list[str]) -> list[str]:
        if any(not value.isdecimal() or len(value) > 32 for value in values):
            raise ValueError("role_ids must contain Discord snowflakes")
        return list(dict.fromkeys(values))


class CafeAvailabilityIn(BaseModel):
    actor: CafeActorIn
    count: int = Field(ge=1, le=10)


class CafeWalletOut(BaseModel):
    total_xp: int
    spent_xp: int
    available_xp: int


class CafeAvailabilityOut(BaseModel):
    wallet: CafeWalletOut
    has_free_draw: bool
    hourly_remaining: int
    requested_count: int
    cost_xp: int


class CafeDrawIn(BaseModel):
    actor: CafeActorIn
    event_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=1, le=10)
    expected_cost_xp: int = Field(ge=0, le=200)


class CafeDrawOut(BaseModel):
    event_id: str
    batch_position: int
    reward_key: str
    reward_name: str
    reward_description: str
    rarity: str
    image_filename: str
    draw_type: str
    cost_xp: int
    reward_xp: int
    exchange_xp: int
    was_duplicate: bool
    owned_count: int
    collected_count: int


class CafeDrawBatchOut(BaseModel):
    status: Literal[
        "drawn",
        "confirmation_required",
        "insufficient_xp",
        "hourly_limit",
        "conflict",
    ]
    draws: list[CafeDrawOut]
    wallet_before: CafeWalletOut
    wallet_after: CafeWalletOut


class CafeCollectionIn(BaseModel):
    actor: CafeActorIn


class CafeCollectionCardOut(BaseModel):
    key: str
    name: str
    rarity: str
    description: str
    image_filename: str
    count: int
    redeemable_count: int
    lifetime_count: int
    is_protected: bool


class CafeCollectionOut(BaseModel):
    cards: list[CafeCollectionCardOut]


class CafeCapabilitiesOut(BaseModel):
    api_version: int
    catalog_size: int
    asset_count: int
    asset_manifest_sha256: str
