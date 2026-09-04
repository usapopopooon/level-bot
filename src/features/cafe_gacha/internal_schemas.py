"""Schemas for the trusted Cafe Collection bot API."""

from __future__ import annotations

from datetime import datetime
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
    exchangeable_count: int
    exchange_xp: int
    exchange_medals: int
    mastery_name: str | None
    mastery_emoji: str | None


class CafeCosmeticOut(BaseModel):
    key: str
    name: str
    cost_medals: int
    color: int
    decoration: str


class CafeSetOut(BaseModel):
    key: str
    name: str
    description: str
    completed: bool
    missing_card_names: list[str]


class CafeMasterySummaryOut(BaseModel):
    name: str
    emoji: str
    card_count: int


class CafeCollectionOut(BaseModel):
    cards: list[CafeCollectionCardOut]
    favorite_reward_key: str | None
    duplicate_draw_streak: int
    endgame_pity_active: bool
    endgame_pity_duplicate_draws: int
    mastery_tiers: list[CafeMasterySummaryOut]
    medal_balance: int
    active_cosmetic: CafeCosmeticOut | None
    cosmetics: list[CafeCosmeticOut]
    sets: list[CafeSetOut]


class CafeCardSettingIn(BaseModel):
    actor: CafeActorIn
    reward_key: str = Field(min_length=1, max_length=64)


class CafeProtectionIn(CafeCardSettingIn):
    protected: bool


class CafeCardSettingOut(BaseModel):
    status: Literal["updated", "unavailable"]
    reward_key: str | None
    reward_name: str | None
    protected: bool | None = None


class CafeRedemptionIn(BaseModel):
    actor: CafeActorIn
    event_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    quantities: dict[str, int] = Field(min_length=1, max_length=527)

    @field_validator("quantities")
    @classmethod
    def validate_quantities(cls, values: dict[str, int]) -> dict[str, int]:
        if any(
            not key or len(key) > 64 or quantity < 1 or quantity > 9999
            for key, quantity in values.items()
        ):
            raise ValueError("invalid Cafe redemption quantities")
        return values


class CafeRedemptionItemOut(BaseModel):
    reward_key: str
    reward_name: str
    rarity: str
    quantity: int
    reward_per_card: int
    reward_total: int


class CafeRedemptionOut(BaseModel):
    status: Literal["redeemed", "unavailable"]
    reward_xp: int
    reward_medals: int
    medal_balance: int | None = None
    items: list[CafeRedemptionItemOut]


class CafeCosmeticIn(BaseModel):
    actor: CafeActorIn
    cosmetic_key: str = Field(min_length=1, max_length=64)


class CafeCosmeticResultOut(BaseModel):
    status: Literal["equipped", "insufficient", "unavailable"]
    cosmetic: CafeCosmeticOut | None
    balance: int


class CafeAnalyticsIn(BaseModel):
    actor: CafeActorIn


class CafeAnalyticsOut(BaseModel):
    draws_today: int
    draws_7d: int
    total_draws: int
    active_today: int
    active_7d: int
    total_users: int
    new_7d: int
    duplicate_7d: int
    rarity_7d: dict[str, int]
    spent_xp_7d: int
    draw_reward_xp_7d: int
    redemption_xp_7d: int
    completed_users: int


class CafeAccessRolesIn(BaseModel):
    actor: CafeActorIn


class CafeAccessRoleMutationIn(CafeAccessRolesIn):
    role_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")


class CafeAccessRolesOut(BaseModel):
    role_ids: list[str]
    changed: bool | None = None


class CafeCapabilitiesOut(BaseModel):
    api_version: int
    catalog_size: int
    asset_count: int
    asset_manifest_sha256: str
    paid_draw_cost_xp: int
    hourly_draw_limit: int
    minimum_draw_reward_xp: int
    maximum_draw_reward_xp: int
    draw_reward_xp_by_rarity: dict[str, int]
    exchange_xp_by_rarity: dict[str, int]
    ranking_category_totals: dict[str, int]
    set_count: int


class CafeLayoutIn(BaseModel):
    actor: CafeActorIn


class CafePlacementIn(BaseModel):
    actor: CafeActorIn
    placement: Literal["panel", "ledger", "ranking"]
    channel_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    message_id: str | None = Field(
        default=None, min_length=1, max_length=32, pattern=r"^\d+$"
    )


class CafeLayoutOut(BaseModel):
    panel_channel_id: str | None
    panel_message_id: str | None
    ledger_channel_id: str | None
    ledger_message_id: str | None
    ranking_channel_id: str | None
    ranking_message_id: str | None


class CafeLedgerPendingIn(BaseModel):
    guild_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")


class CafeLedgerDrawBatchOut(BaseModel):
    event_id: str
    user_id: str
    created_at: datetime
    draws: list[CafeDrawOut]


class CafeLedgerRedemptionOut(BaseModel):
    event_id: str
    user_id: str
    created_at: datetime
    reward_xp: int
    items: list[CafeRedemptionItemOut]


class CafeLedgerPendingOut(BaseModel):
    ledger_channel_id: str | None
    draw_batches: list[CafeLedgerDrawBatchOut]
    redemptions: list[CafeLedgerRedemptionOut]


class CafeLedgerDeliveredIn(BaseModel):
    guild_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    record_type: Literal["draw", "redemption"]
    event_id: str = Field(min_length=1, max_length=64)
    message_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")


class CafeLedgerDeliveredOut(BaseModel):
    delivered: bool


class CafeRankingIn(BaseModel):
    actor: CafeActorIn


class CafeRankingEntryOut(BaseModel):
    rank: int
    user_id: str
    collection_count: int
    mastery_score: int
    familiar_cards: int
    regular_cards: int
    signature_cards: int
    completed_sets: int
    rare_collection_count: int
    rare_r_count: int
    rare_sr_count: int
    rare_ssr_count: int
    rare_ur_count: int
    rare_mythic_count: int
    treasure_collection_count: int
    n_collection_count: int
    n_mastery_score: int
    n_signature_cards: int
    coffee_collection_count: int
    coffee_mastery_score: int
    coffee_signature_cards: int
    tea_collection_count: int
    tea_mastery_score: int
    tea_signature_cards: int
    sweets_collection_count: int
    sweets_mastery_score: int
    sweets_signature_cards: int
    culture_collection_count: int
    culture_mastery_score: int
    culture_signature_cards: int


class CafeRankingCategoryOut(BaseModel):
    key: str
    entries: list[CafeRankingEntryOut]
    viewer_entry: CafeRankingEntryOut | None


class CafeRankingsOut(BaseModel):
    participant_count: int
    total_draws: int
    captured_at: datetime
    category_totals: dict[str, int]
    set_count: int
    categories: list[CafeRankingCategoryOut]
