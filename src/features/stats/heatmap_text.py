"""Text rendering for Discord-friendly VC activity heatmaps."""

from __future__ import annotations

import unicodedata
from datetime import date, timedelta

from src.features.stats.service import HourlyActivityCell
from src.utils import today_local


def _display_width(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1 for char in value
    )


FULLWIDTH_DIGIT_TRANS = str.maketrans("0123456789", "０１２３４５６７８９")
WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")
BUCKET_HOURS = tuple(range(0, 24, 3))
BUCKET_LABELS = tuple(f"{hour}-{hour + 2}" for hour in BUCKET_HOURS)
BUCKET_LABEL_WIDTH = max(len(label) for label in BUCKET_LABELS)
ROW_HEADER_LABEL = "曜日/時"
ROW_LABEL_WIDTH = _display_width(ROW_HEADER_LABEL)
HEAT_CHARS = ("·", "░", "▒", "▓", "█")


def _fullwidth_number(value: int) -> str:
    return str(value).translate(FULLWIDTH_DIGIT_TRANS)


def format_hourly_activity_heatmap_title(
    *, days: int, end_date: date | None = None, decorated: bool = True
) -> str:
    end = end_date or today_local()
    start = end - timedelta(days=max(days - 1, 0))
    if start == end:
        title = (
            f"{_fullwidth_number(end.month)}月"
            f"{_fullwidth_number(end.day)}日のVCアクティブヒートマップ"
        )
        return f"{title}🔥" if decorated else title
    if days < 28:
        title = f"直近{_fullwidth_number(days)}日間のVCアクティブヒートマップ"
        return f"{title}🔥" if decorated else title
    if start.year == end.year and start.month == end.month:
        title = f"{_fullwidth_number(end.month)}月のVCアクティブヒートマップ"
        return f"{title}🔥" if decorated else title
    if start.year == end.year:
        title = (
            f"{_fullwidth_number(start.month)}-"
            f"{_fullwidth_number(end.month)}月のVCアクティブヒートマップ"
        )
        return f"{title}🔥" if decorated else title
    title = (
        f"{_fullwidth_number(start.year)}年{_fullwidth_number(start.month)}月-"
        f"{_fullwidth_number(end.year)}年"
        f"{_fullwidth_number(end.month)}月のVCアクティブヒートマップ"
    )
    return f"{title}🔥" if decorated else title


def hourly_activity_heatmap_level(voice_seconds: int, max_voice_seconds: int) -> int:
    if voice_seconds <= 0 or max_voice_seconds <= 0:
        return 0
    ratio = voice_seconds / max_voice_seconds
    if ratio <= 0.25:
        return 1
    if ratio <= 0.5:
        return 2
    if ratio <= 0.75:
        return 3
    return 4


def _heat_char(voice_seconds: int, max_voice_seconds: int) -> str:
    return HEAT_CHARS[hourly_activity_heatmap_level(voice_seconds, max_voice_seconds)]


def _text_bucket(value: str) -> str:
    return value.center(BUCKET_LABEL_WIDTH)


def _pad_display(value: str, width: int) -> str:
    return value + " " * max(width - _display_width(value), 0)


def bucket_hourly_activity_heatmap_voice_seconds(
    cells: list[HourlyActivityCell],
) -> dict[tuple[int, int], int]:
    buckets: dict[tuple[int, int], int] = {}
    for cell in cells:
        bucket_hour = cell.hour - (cell.hour % 3)
        key = (cell.weekday, bucket_hour)
        buckets[key] = buckets.get(key, 0) + cell.voice_seconds
    return buckets


def render_hourly_activity_heatmap_text(
    *,
    days: int,
    cells: list[HourlyActivityCell],
    end_date: date | None = None,
) -> str:
    """Render a compact Japanese weekday x 3-hour VC heatmap."""
    buckets = bucket_hourly_activity_heatmap_voice_seconds(cells)
    max_voice_seconds = max(buckets.values(), default=0)
    lines = [
        format_hourly_activity_heatmap_title(days=days, end_date=end_date),
        "",
        (
            f"{_pad_display(ROW_HEADER_LABEL, ROW_LABEL_WIDTH)} "
            f"{' '.join(_text_bucket(label) for label in BUCKET_LABELS).rstrip()}"
        ),
    ]

    for weekday, label in enumerate(WEEKDAYS_JA):
        values = [
            _text_bucket(_heat_char(buckets.get((weekday, hour), 0), max_voice_seconds))
            for hour in BUCKET_HOURS
        ]
        lines.append(
            f"{_pad_display(label, ROW_LABEL_WIDTH)} {' '.join(values).rstrip()}"
        )

    lines.extend(["", "· 少  ░ ▒ ▓ █ 多"])
    return "\n".join(lines)
