"""カフェ・コレクション公開ページ向けレスポンススキーマ。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CafeCatalogCardOut(BaseModel):
    key: str
    name: str
    rarity: str
    description: str
    image_url: str
    base_draw_rate_percent: float
    draw_reward_xp: int
    exchange_xp: int
    is_food: bool


class CafeCatalogSetOut(BaseModel):
    key: str
    name: str
    description: str
    required_card_keys: list[str]


class CafeMasteryTierOut(BaseModel):
    minimum_count: int
    name: str
    emoji: str


class CafeCatalogRulesOut(BaseModel):
    free_draws_per_day: int
    free_draw_reset_timezone: str
    paid_draw_cost_xp: int
    hourly_draw_limit: int
    daily_draw_limit: int | None
    unowned_weight_multiplier: int
    endgame_pity_min_collected: int
    endgame_pity_duplicate_draws: int
    first_copy_protected: bool
    draw_results_public: bool


class CafeCatalogOut(BaseModel):
    total_cards: int
    food_cards: int
    rarity_counts: dict[str, int]
    rarity_rates_percent: dict[str, float]
    cards: list[CafeCatalogCardOut]
    sets: list[CafeCatalogSetOut]
    mastery_tiers: list[CafeMasteryTierOut]
    rules: CafeCatalogRulesOut


class CafeLeaderboardEntryOut(BaseModel):
    rank: int
    profile_id: str
    display_name: str
    avatar_url: str | None
    collection_count: int
    total_draws: int
    mastery_score: int
    discovery_cards: int
    familiar_cards: int
    regular_cards: int
    signature_cards: int
    completed_sets: int
    rare_collection_count: int
    rare_r_count: int
    rare_sr_count: int
    rare_ssr_count: int
    n_collection_count: int
    n_mastery_score: int
    n_signature_cards: int


class CafeLeaderboardCategoryOut(BaseModel):
    key: str
    entries: list[CafeLeaderboardEntryOut]


class CafeLeaderboardsOut(BaseModel):
    guild_id: str
    total_cards: int
    total_sets: int
    participant_count: int
    total_draws: int
    captured_at: datetime
    categories: list[CafeLeaderboardCategoryOut]


class CafeCollectionProfileCardOut(BaseModel):
    card_key: str
    count: int
    lifetime_count: int


class CafeCollectionProfileOut(BaseModel):
    profile_id: str
    display_name: str
    avatar_url: str | None
    total_cards: int
    total_sets: int
    collection_count: int
    total_draws: int
    mastery_score: int
    completed_set_keys: list[str]
    ranks: dict[str, int]
    cards: list[CafeCollectionProfileCardOut]
    captured_at: datetime
