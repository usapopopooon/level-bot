"""Pydantic response schemas for the ranking public API."""

from __future__ import annotations

from pydantic import BaseModel


class LeaderboardEntryOut(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None
    message_count: int
    voice_seconds: int


class ChannelLeaderboardEntryOut(BaseModel):
    channel_id: str
    name: str
    message_count: int
    voice_seconds: int
