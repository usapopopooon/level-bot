"""Pydantic response schemas for the leveling public API."""

from __future__ import annotations

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
    activity_rate: float  # 直近 30 日のアクティブ率 (0.0-1.0)。XP の掛け率
    activity_rate_window_days: int  # rate を求めた窓 (デフォ 30)
