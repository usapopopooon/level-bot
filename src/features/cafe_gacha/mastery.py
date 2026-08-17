"""カードの累計獲得数から熟練度を算出する。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MasteryTier:
    minimum_count: int
    name: str
    emoji: str


MASTERY_TIERS: tuple[MasteryTier, ...] = (
    MasteryTier(1, "発見", "🔎"),
    MasteryTier(3, "なじみ", "☕"),
    MasteryTier(10, "常連", "⭐"),
    MasteryTier(25, "看板メニュー", "🏆"),
)


def mastery_tier(lifetime_count: int) -> MasteryTier | None:
    """累計獲得数に対応する最高の熟練度を返す。"""
    achieved = tuple(
        tier for tier in MASTERY_TIERS if lifetime_count >= tier.minimum_count
    )
    return achieved[-1] if achieved else None


def next_mastery_tier(lifetime_count: int) -> MasteryTier | None:
    return next(
        (tier for tier in MASTERY_TIERS if lifetime_count < tier.minimum_count), None
    )
