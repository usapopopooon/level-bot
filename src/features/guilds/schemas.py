"""Pydantic response schemas for the guilds public API."""

from __future__ import annotations

from pydantic import BaseModel


class GuildOut(BaseModel):
    guild_id: str
    name: str
    icon_url: str | None = None
    member_count: int
