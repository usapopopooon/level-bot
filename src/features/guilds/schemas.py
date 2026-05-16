"""Pydantic response schemas for the guilds public API."""

from __future__ import annotations

from pydantic import BaseModel


class GuildOut(BaseModel):
    guild_id: str
    name: str
    icon_url: str | None = None
    member_count: int


class GuildRoleOut(BaseModel):
    role_id: str
    role_name: str
    position: int
    is_managed: bool


class LevelRoleAwardOut(BaseModel):
    slot: int
    level: int
    role_id: str
    role_name: str


class LevelRoleAwardsUpdateItem(BaseModel):
    slot: int = 1
    level: int
    role_id: str


class LevelRoleAwardsUpdateIn(BaseModel):
    rules: list[LevelRoleAwardsUpdateItem]
