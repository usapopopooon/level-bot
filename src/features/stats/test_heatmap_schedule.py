from datetime import UTC, datetime

import pytest

from src.constants import DEFAULT_DAILY_HEATMAP_TIMEZONE
from src.features.stats.heatmap_schedule import (
    daily_heatmap_target_date,
    normalize_daily_heatmap_time,
    normalize_daily_heatmap_timezone,
)


def test_daily_heatmap_target_date_defaults_to_jst() -> None:
    assert daily_heatmap_target_date(datetime(2026, 6, 30, 15, 30, tzinfo=UTC)) == (
        datetime(2026, 6, 30, tzinfo=UTC).date()
    )


def test_daily_heatmap_target_date_uses_configured_timezone() -> None:
    assert (
        daily_heatmap_target_date(
            datetime(2026, 7, 1, 0, 30, tzinfo=UTC),
            timezone_name="UTC",
        )
        == datetime(2026, 6, 30, tzinfo=UTC).date()
    )


def test_daily_heatmap_target_date_skips_outside_post_window() -> None:
    assert daily_heatmap_target_date(datetime(2026, 7, 1, 1, 0, tzinfo=UTC)) is None


def test_daily_heatmap_target_date_uses_configured_post_time() -> None:
    assert (
        daily_heatmap_target_date(
            datetime(2026, 6, 30, 18, 15, tzinfo=UTC),
            post_time="03:00",
            timezone_name="Asia/Tokyo",
        )
        == datetime(2026, 6, 30, tzinfo=UTC).date()
    )


def test_normalize_daily_heatmap_time_accepts_short_hour() -> None:
    assert normalize_daily_heatmap_time("9:05") == "09:05"


def test_normalize_daily_heatmap_time_rejects_invalid_time() -> None:
    with pytest.raises(ValueError):
        normalize_daily_heatmap_time("24:00")


def test_normalize_daily_heatmap_timezone_defaults_and_accepts_jst_alias() -> None:
    assert normalize_daily_heatmap_timezone("") == DEFAULT_DAILY_HEATMAP_TIMEZONE
    assert normalize_daily_heatmap_timezone("JST") == DEFAULT_DAILY_HEATMAP_TIMEZONE


def test_normalize_daily_heatmap_timezone_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError):
        normalize_daily_heatmap_timezone("Moon/Base")
