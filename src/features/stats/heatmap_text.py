"""Text rendering for Discord-friendly VC activity heatmaps."""

from __future__ import annotations

from datetime import date, timedelta

from src.features.stats.service import HourlyActivityCell
from src.utils import today_local

WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")
BUCKET_HOURS = tuple(range(0, 24, 3))
HEAT_CHARS = ("·", "░", "▒", "▓", "█")


def format_hourly_activity_heatmap_title(
    *, days: int, end_date: date | None = None, decorated: bool = True
) -> str:
    end = end_date or today_local()
    start = end - timedelta(days=max(days - 1, 0))
    if start == end:
        title = f"{end.month}月{end.day}日のVCアクティブヒートマップ"
        return f"{title}🔥" if decorated else title
    if start.year == end.year and start.month == end.month:
        title = f"{end.month}月のVCアクティブヒートマップ"
        return f"{title}🔥" if decorated else title
    if start.year == end.year:
        title = f"{start.month}-{end.month}月のVCアクティブヒートマップ"
        return f"{title}🔥" if decorated else title
    title = (
        f"{start.year}年{start.month}月-"
        f"{end.year}年{end.month}月のVCアクティブヒートマップ"
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
        "    0  3  6  9 12 15 18 21",
    ]

    for weekday, label in enumerate(WEEKDAYS_JA):
        values = [
            _heat_char(buckets.get((weekday, hour), 0), max_voice_seconds)
            for hour in BUCKET_HOURS
        ]
        lines.append(f"{label}  {'  '.join(values)}")

    lines.extend(["", "· 少  ░ ▒ ▓ █ 多"])
    return "\n".join(lines)
