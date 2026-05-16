"""Pydantic response schemas for the leveling public API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class LevelBreakdownOut(BaseModel):
    level: int
    xp: int
    current_floor: int  # 現レベル到達に必要な累計 XP
    next_floor: int  # 次レベル到達に必要な累計 XP
    progress: float  # 現レベル → 次レベルへの進捗 (0.0-1.0)


class UserLevelsOut(BaseModel):
    total: LevelBreakdownOut
    voice: LevelBreakdownOut
    text: LevelBreakdownOut
    reactions_received: LevelBreakdownOut
    reactions_given: LevelBreakdownOut


class LevelLeaderboardEntryOut(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None
    level: int
    xp: int


class XpWeightLogOut(BaseModel):
    effective_from: date
    message_weight: float
    reaction_received_weight: float
    reaction_given_weight: float


class XpWeightLogCreateIn(BaseModel):
    effective_from: date
    message_weight: float
    reaction_received_weight: float
    reaction_given_weight: float


class XpWeightRollbackIn(BaseModel):
    effective_from: date
