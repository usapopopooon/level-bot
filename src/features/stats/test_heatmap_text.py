"""Tests for compact text VC heatmaps."""

from datetime import date

from src.features.stats.heatmap_text import render_hourly_activity_heatmap_text
from src.features.stats.service import HourlyActivityCell


def _cells(entries: dict[tuple[int, int], int]) -> list[HourlyActivityCell]:
    return [
        HourlyActivityCell(
            weekday=weekday,
            hour=hour,
            voice_seconds=entries.get((weekday, hour), 0),
            active_users=1 if entries.get((weekday, hour), 0) > 0 else 0,
            intensity_percent=0,
        )
        for weekday in range(7)
        for hour in range(24)
    ]


def test_render_hourly_activity_heatmap_text_is_compact_japanese_layout() -> None:
    text = render_hourly_activity_heatmap_text(
        days=7,
        end_date=date(2026, 6, 30),
        cells=_cells(
            {
                (0, 0): 60,
                (0, 1): 40,
                (1, 3): 50,
                (6, 21): 25,
            }
        ),
    )

    assert text == (
        "直近７日間のVCアクティブヒートマップ🔥\n"
        "\n"
        "曜日/時  0-2   3-5   6-8   9-11 12-14 15-17 18-20 21-23\n"
        "月        █     ·     ·     ·     ·     ·     ·     ·\n"
        "火        ·     ▒     ·     ·     ·     ·     ·     ·\n"
        "水        ·     ·     ·     ·     ·     ·     ·     ·\n"
        "木        ·     ·     ·     ·     ·     ·     ·     ·\n"
        "金        ·     ·     ·     ·     ·     ·     ·     ·\n"
        "土        ·     ·     ·     ·     ·     ·     ·     ·\n"
        "日        ·     ·     ·     ·     ·     ·     ·     ░\n"
        "\n"
        "· 少  ░ ▒ ▓ █ 多"
    )


def test_render_hourly_activity_heatmap_text_formats_single_day() -> None:
    text = render_hourly_activity_heatmap_text(
        days=1,
        end_date=date(2026, 6, 30),
        cells=_cells({}),
    )

    assert text.startswith("６月３０日のVCアクティブヒートマップ🔥\n")


def test_render_hourly_activity_heatmap_text_formats_recent_days() -> None:
    text = render_hourly_activity_heatmap_text(
        days=7,
        end_date=date(2026, 7, 5),
        cells=_cells({}),
    )

    assert text.startswith("直近７日間のVCアクティブヒートマップ🔥\n")


def test_render_hourly_activity_heatmap_text_formats_multi_month_range() -> None:
    text = render_hourly_activity_heatmap_text(
        days=30,
        end_date=date(2026, 6, 30),
        cells=_cells({}),
    )

    assert text.startswith("６月のVCアクティブヒートマップ🔥\n")


def test_render_hourly_activity_heatmap_text_formats_spanning_months() -> None:
    text = render_hourly_activity_heatmap_text(
        days=31,
        end_date=date(2026, 6, 30),
        cells=_cells({}),
    )

    assert text.startswith("５-６月のVCアクティブヒートマップ🔥\n")
