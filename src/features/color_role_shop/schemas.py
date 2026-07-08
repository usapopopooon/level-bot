"""Pydantic schemas for color-role shop management API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ColorRoleShopItemOut(BaseModel):
    id: int
    role_id: str
    role_name: str
    label: str
    description: str | None = None
    cost_xp: int


class ColorRoleShopItemUpsertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: str
    cost_xp: int
    description: str | None = None


class ColorRoleShopPanelPostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: str


class ColorRoleShopPanelPostOut(BaseModel):
    channel_id: str
    message_id: str
