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
