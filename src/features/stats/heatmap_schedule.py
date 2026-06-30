"""Scheduling helpers for daily VC heatmap posts."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.constants import DEFAULT_DAILY_HEATMAP_TIME, DEFAULT_DAILY_HEATMAP_TIMEZONE

DAILY_HEATMAP_POST_WINDOW = timedelta(hours=1)

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIMEZONE_ALIASES = {
    "jst": DEFAULT_DAILY_HEATMAP_TIMEZONE,
    "japan": DEFAULT_DAILY_HEATMAP_TIMEZONE,
}


def normalize_daily_heatmap_time(value: str) -> str:
    match = _TIME_RE.fullmatch(value.strip())
    if match is None:
        msg = "投稿時刻は HH:MM 形式で指定してください。例: 00:00"
        raise ValueError(msg)

    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        msg = "投稿時刻は 00:00 から 23:59 の範囲で指定してください。"
        raise ValueError(msg)
    return f"{hour:02d}:{minute:02d}"


def normalize_daily_heatmap_timezone(value: str | None) -> str:
    if value is None or not value.strip():
        return DEFAULT_DAILY_HEATMAP_TIMEZONE

    normalized = _TIMEZONE_ALIASES.get(value.strip().lower(), value.strip())
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        msg = "タイムゾーンは Asia/Tokyo や UTC のような名前で指定してください。"
        raise ValueError(msg) from exc
    return normalized


def daily_heatmap_target_date(
    now: datetime,
    *,
    post_time: str = DEFAULT_DAILY_HEATMAP_TIME,
    timezone_name: str = DEFAULT_DAILY_HEATMAP_TIMEZONE,
) -> date | None:
    """Return the previous local date while inside the configured post window."""
    normalized_time = normalize_daily_heatmap_time(post_time)
    normalized_timezone = normalize_daily_heatmap_timezone(timezone_name)
    hour, minute = (int(part) for part in normalized_time.split(":", maxsplit=1))

    aware_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    local_now = aware_now.astimezone(ZoneInfo(normalized_timezone))
    window_start = local_now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    for start in (window_start, window_start - timedelta(days=1)):
        if start <= local_now < start + DAILY_HEATMAP_POST_WINDOW:
            return start.date() - timedelta(days=1)
    return None
