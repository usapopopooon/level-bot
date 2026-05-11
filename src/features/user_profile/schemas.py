"""Pydantic response schemas for the user profile public API."""

from __future__ import annotations

from pydantic import BaseModel

from src.features.stats.schemas import DailyPointOut


class TopChannelEntryOut(BaseModel):
    """プロフィールの「主な発言チャンネル」レスポンス。

    ranking の ``ChannelLeaderboardEntryOut`` と同型だが、ranking feature
    に依存しないよう独自定義としている。
    """

    channel_id: str
    name: str
    message_count: int
    voice_seconds: int
    reactions_received: int
    reactions_given: int


class UserProfileOut(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None
    total_messages: int
    total_voice_seconds: int
    total_reactions_received: int
    total_reactions_given: int
    rank_messages: int | None = None
    rank_voice: int | None = None
    rank_reactions_received: int | None = None
    rank_reactions_given: int | None = None
    daily: list[DailyPointOut]
    top_channels: list[TopChannelEntryOut]
