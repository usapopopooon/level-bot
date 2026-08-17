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


class CafeCatalogOut(BaseModel):
    total_cards: int
    food_cards: int
    rarity_counts: dict[str, int]
    rarity_rates_percent: dict[str, float]
    cards: list[CafeCatalogCardOut]
    sets: list[CafeCatalogSetOut]
    mastery_tiers: list[CafeMasteryTierOut]


class CafeLeaderboardEntryOut(BaseModel):
    rank: int
    display_name: str
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
