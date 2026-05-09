"""Regression tests for ``date_window``.

書き込み (Bot 側 ``today_local()``) と読み出し (集計側 ``date_window``) で
タイムゾーンが食い違うと境界日にデータが消える。両者が同じ日付関数を
通っていることを保証する。
"""

from datetime import timedelta

from src.utils import date_window, today_local


def test_date_window_end_matches_today_local() -> None:
    _, end = date_window(30)
    assert end == today_local()


def test_date_window_uses_local_not_utc() -> None:
    """書き込み (today_local) と読み出し (date_window) の整合を確認する。"""
    _, end = date_window(1)
    assert end == today_local()


def test_date_window_30_days_inclusive() -> None:
    start, end = date_window(30)
    assert (end - start) == timedelta(days=29)  # 30 日 = 閉区間で 29 日差


def test_date_window_single_day() -> None:
    start, end = date_window(1)
    assert start == end == today_local()


def test_date_window_zero_clamps_to_single_day() -> None:
    start, end = date_window(0)
    # days-1 が負にならないようクランプされ、start == end になる
    assert start == end == today_local()


def test_date_window_year() -> None:
    start, end = date_window(365)
    assert (end - start) == timedelta(days=364)
