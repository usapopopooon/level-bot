"""Pydantic response schemas for the stats public API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class GuildSummaryOut(BaseModel):
    guild_id: str
    name: str
    icon_url: str | None = None
    total_messages: int
    total_voice_seconds: int
    total_reactions_received: int
    total_reactions_given: int
    active_users: int
    days: int


class DailyPointOut(BaseModel):
    date: date
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


class HourlyActivityCellOut(BaseModel):
    weekday: int
    hour: int
    voice_seconds: int
    active_users: int
    intensity_percent: int


class SocialGraphNodeOut(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None
    weight: float
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


class SocialGraphEdgeOut(BaseModel):
    source_user_id: str
    target_user_id: str
    weight: float
    voice_seconds: int
    voice_sessions: int
    replies: int
    reactions: int
    co_activity: float


class SocialGraphOut(BaseModel):
    guild_id: str
    days: int
    nodes: list[SocialGraphNodeOut]
    edges: list[SocialGraphEdgeOut]
