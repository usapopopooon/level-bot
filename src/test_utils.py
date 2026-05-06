"""Tests for src.utils."""

from datetime import timezone

from src.utils import clamp, format_seconds, get_timezone


def test_format_seconds_zero() -> None:
    assert format_seconds(0) == "0s"


def test_format_seconds_negative_clamps_to_zero() -> None:
    assert format_seconds(-100) == "0s"


def test_format_seconds_minutes_only() -> None:
    assert format_seconds(125) == "2m 5s"


def test_format_seconds_with_hours() -> None:
    # 1h 5m -> 4ke seconds → 60*60+5*60 = 3900? Use clean: 3725 = 1h 2m
    assert format_seconds(3725) == "1h 2m"


def test_clamp_within_range() -> None:
    assert clamp(5, 0, 10) == 5


def test_clamp_below_min() -> None:
    assert clamp(-1, 0, 10) == 0


def test_clamp_above_max() -> None:
    assert clamp(99, 0, 10) == 10


def test_get_timezone_returns_tzinfo() -> None:
    tz = get_timezone()
    assert isinstance(tz, timezone)
