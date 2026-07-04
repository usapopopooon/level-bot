"""Default chill-place presets and pure formatting helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ChillPlace:
    required_level: int
    name: str
    emoji: str | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class ChillPlaceOverride:
    name: str
    emoji: str | None = None


@dataclass(frozen=True)
class ChillDisplay:
    current: ChillPlace | None
    next_place: ChillPlace | None
    selected_locked: bool = False


DEFAULT_CHILL_PLACES: tuple[ChillPlace, ...] = (
    ChillPlace(
        1,
        "入口のベンチ",
        "🪑",
        ("はじめまして", "気軽"),
        "まずはここで、ゆっくり空気を眺める席。",
    ),
    ChillPlace(
        2,
        "ロビーソファ",
        "🛋️",
        ("雑談", "のんびり"),
        "通りすがりの会話に混ざりやすい、やわらかい場所。",
    ),
    ChillPlace(
        3,
        "窓際スツール",
        "🪟",
        ("ひと休み", "明るい"),
        "外の気配を感じながら、少しだけ腰を下ろす席。",
    ),
    ChillPlace(
        4,
        "小さな丸テーブル",
        "☕",
        ("少人数", "気軽"),
        "近くの人と軽く話すのにちょうどいいテーブル。",
    ),
    ChillPlace(
        5,
        "カフェカウンター",
        "🥤",
        ("雑談", "作業前"),
        "飲み物を片手に、その日の調子を整える場所。",
    ),
    ChillPlace(
        6,
        "本棚のそば",
        "📚",
        ("静か", "読書"),
        "会話も作業も、少し落ち着いた声になる一角。",
    ),
    ChillPlace(
        7,
        "観葉植物の横",
        "🪴",
        ("すみっこ", "安心"),
        "ほどよく人の気配がある、静かなすみっこ。",
    ),
    ChillPlace(
        8,
        "ふかふかチェア",
        "💤",
        ("まったり", "休憩"),
        "ちょっと疲れた日に沈み込む席。",
    ),
    ChillPlace(
        9,
        "充電席",
        "🔌",
        ("回復", "作業"),
        "端末も気持ちも、じわっと充電していく場所。",
    ),
    ChillPlace(
        10,
        "いつものカフェ席",
        "☕",
        ("定位置", "雑談"),
        "顔なじみの会話が自然に始まる席。",
    ),
    ChillPlace(
        12,
        "静かな作業机",
        "📝",
        ("集中", "静か"),
        "少し集中したい日に向いた、整った机。",
    ),
    ChillPlace(
        14,
        "本棚奥の席",
        "📖",
        ("読書", "隠れ家"),
        "本棚の奥で、話しかけられすぎずに過ごせる場所。",
    ),
    ChillPlace(
        16,
        "夜更かしテーブル",
        "🌙",
        ("夜", "作業"),
        "遅い時間のゆるい作業と雑談が似合うテーブル。",
    ),
    ChillPlace(
        18,
        "半個室ソファ",
        "🕯️",
        ("少人数", "落ち着く"),
        "少しこもって、近い人たちと過ごせるソファ。",
    ),
    ChillPlace(
        20,
        "チルラウンジ",
        "🍵",
        ("節目", "まったり"),
        "ここまで来た人のための、広めでゆるいラウンジ。",
    ),
    ChillPlace(
        25,
        "窓辺の作業部屋",
        "🌤️",
        ("集中", "景色"),
        "景色を横目に、ゆっくり手を動かす部屋。",
    ),
    ChillPlace(
        30,
        "深夜の作業部屋",
        "🌃",
        ("深夜", "集中"),
        "静かな夜に、ぽつぽつ人が集まる作業部屋。",
    ),
    ChillPlace(
        40,
        "中庭ベンチ",
        "🌿",
        ("外気", "休憩"),
        "少し外に出た気分で、肩の力を抜けるベンチ。",
    ),
    ChillPlace(
        50,
        "暖炉前",
        "🔥",
        ("常連", "ぬくもり"),
        "長くいる人たちの会話がゆっくり続く場所。",
    ),
    ChillPlace(
        75,
        "屋上テラス",
        "🌌",
        ("夜風", "特別"),
        "夜風にあたりながら、静かに話せる特別席。",
    ),
    ChillPlace(
        100,
        "常連席",
        "🏆",
        ("記念", "定位置"),
        "ここまで過ごしてきた人だけの、ちょっと誇らしい席。",
    ),
)


def format_chill_place_name(place: ChillPlace) -> str:
    return f"{place.emoji} {place.name}" if place.emoji else place.name


def format_chill_choice_name(place: ChillPlace) -> str:
    return f"{format_chill_place_name(place)} (Lv.{place.required_level})"


def build_chill_places(
    overrides: Mapping[int, ChillPlaceOverride] | None = None,
) -> tuple[ChillPlace, ...]:
    by_level = {place.required_level: place for place in DEFAULT_CHILL_PLACES}
    if overrides:
        for level, override in overrides.items():
            default = by_level.get(level)
            tags = default.tags if default is not None else ()
            description = default.description if default is not None else None
            emoji = (
                override.emoji
                if override.emoji is not None
                else default.emoji
                if default is not None
                else None
            )
            by_level[level] = ChillPlace(
                level,
                override.name,
                emoji=emoji,
                tags=tags,
                description=description,
            )
    return tuple(by_level[level] for level in sorted(by_level))


def resolve_chill_display(
    places: tuple[ChillPlace, ...],
    *,
    level: int | None,
    selected_level: int | None = None,
) -> ChillDisplay | None:
    if level is None or not places:
        return None
    unlocked = [place for place in places if place.required_level <= level]
    if not unlocked:
        next_place = next(
            (place for place in places if place.required_level > level), None
        )
        return ChillDisplay(current=None, next_place=next_place)

    selected = next(
        (place for place in places if place.required_level == selected_level),
        None,
    )
    if selected is not None and selected.required_level <= level:
        current = selected
        selected_locked = False
    else:
        current = unlocked[-1]
        selected_locked = selected is not None
    next_place = next((place for place in places if place.required_level > level), None)
    return ChillDisplay(
        current=current, next_place=next_place, selected_locked=selected_locked
    )
