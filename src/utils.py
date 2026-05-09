"""Utility helpers shared across the bot and web app."""

from datetime import UTC, date, datetime, timedelta, timezone

from src.config import settings


def get_timezone() -> timezone:
    """設定された TIMEZONE_OFFSET (時) からタイムゾーンを返す。"""
    return timezone(timedelta(hours=settings.timezone_offset))


def now_utc() -> datetime:
    """UTC のタイムゾーン付き現在時刻を返す。"""
    return datetime.now(UTC)


def now_local() -> datetime:
    """設定タイムゾーン基準の現在時刻を返す。"""
    return datetime.now(get_timezone())


def today_local() -> date:
    """設定タイムゾーン基準の「今日」を返す。日次集計のキーに使う。"""
    return now_local().date()


def date_window(days: int) -> tuple[date, date]:
    """``[today - (days-1), today]`` の閉区間を返す (Bot 設定 TZ 基準)。

    書き込み側 (``today_local()``) と一致させるため、UTC ではなく
    ``settings.timezone_offset`` を反映した日付を使う。読み出し系
    feature (``stats`` / ``ranking`` / ``user_profile``) が同じ窓を
    使うために共通化している。
    """
    today = today_local()
    start = today - timedelta(days=max(days - 1, 0))
    return start, today


def format_seconds(total_seconds: int) -> str:
    """秒数を ``Xh Ym`` / ``Ym Zs`` 形式に整形する。"""
    if total_seconds < 0:
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def clamp(value: int, min_value: int, max_value: int) -> int:
    """値を ``[min_value, max_value]`` の範囲にクランプする。"""
    return max(min_value, min(max_value, value))
