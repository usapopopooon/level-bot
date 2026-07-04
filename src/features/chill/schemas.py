"""Pydantic schemas for chill-place APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChillLevelOut(BaseModel):
    level: int
    progress: float
    progress_percent: int


class ChillPlaceOut(BaseModel):
    required_level: int
    name: str
    emoji: str | None = None
    display_name: str
    choice_label: str
    tags: list[str] = Field(default_factory=list)
    description: str | None = None


class ChillDisplayOut(BaseModel):
    current: ChillPlaceOut | None
    next: ChillPlaceOut | None = None
    selected_locked: bool = False


class ChillPlaceOptionsOut(BaseModel):
    guild_id: str
    user_id: str
    level: ChillLevelOut
    selected_required_level: int | None = None
    places: list[ChillPlaceOut]


class ChillPlaceSelectionIn(BaseModel):
    required_level: int


class ChillPlaceSelectionOut(BaseModel):
    guild_id: str
    user_id: str
    level: ChillLevelOut
    selected: ChillPlaceOut
    chill_place: ChillDisplayOut | None


class ChillPlaceOverrideIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    emoji: str | None = Field(default=None, min_length=1, max_length=40)


class ChillPlaceOverrideOut(BaseModel):
    guild_id: str
    required_level: int
    name: str
    emoji: str | None = None
