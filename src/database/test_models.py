"""Validation tests for SQLAlchemy models (no DB required)."""

import pytest

from src.database.models import (
    DailyStat,
    ExcludedChannel,
    Guild,
    UserMeta,
    VoiceSession,
)


def test_guild_validates_digit_string_id() -> None:
    g = Guild(guild_id="123456", name="g")
    assert g.guild_id == "123456"


def test_guild_rejects_non_digit_id() -> None:
    with pytest.raises(ValueError):
        Guild(guild_id="abc", name="g")


def test_voice_session_rejects_bad_user_id() -> None:
    with pytest.raises(ValueError):
        VoiceSession(guild_id="1", user_id="!@#", channel_id="2")


def test_daily_stat_validates_all_fk_ids() -> None:
    s = DailyStat(
        guild_id="1",
        user_id="2",
        channel_id="3",
        stat_date=__import__("datetime").date(2026, 1, 1),
    )
    assert s.guild_id == "1"


def test_excluded_channel_rejects_bad_channel_id() -> None:
    with pytest.raises(ValueError):
        ExcludedChannel(guild_id="1", channel_id="not-a-number")


def test_user_meta_rejects_non_digit_id() -> None:
    with pytest.raises(ValueError):
        UserMeta(user_id="abc")
