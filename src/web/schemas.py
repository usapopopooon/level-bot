"""Pydantic response schemas for the public stats API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class GuildOut(BaseModel):
    guild_id: str
    name: str
    icon_url: str | None = None
    member_count: int


class GuildSummaryOut(BaseModel):
    guild_id: str
    name: str
    icon_url: str | None = None
    total_messages: int
    total_voice_seconds: int
    active_users: int
    days: int


class DailyPointOut(BaseModel):
    date: date
    message_count: int
    voice_seconds: int


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


class UserProfileOut(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None
    total_messages: int
    total_voice_seconds: int
    rank_messages: int | None = None
    rank_voice: int | None = None
    daily: list[DailyPointOut]
    top_channels: list[ChannelLeaderboardEntryOut]
