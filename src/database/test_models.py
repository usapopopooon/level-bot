"""Validation tests for SQLAlchemy models (no DB required)."""

import pytest

from src.database.models import (
    DailyStat,
    ExcludedChannel,
    Guild,
    LevelRoleAward,
    LevelXpWeightChangeLog,
    RoleMeta,
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


def test_role_meta_rejects_non_digit_role_id() -> None:
    with pytest.raises(ValueError):
        RoleMeta(guild_id="1", role_id="role", name="x", position=1)


def test_level_role_award_rejects_non_digit_guild_id() -> None:
    with pytest.raises(ValueError):
        LevelRoleAward(guild_id="g", level=3, role_id="123")


def test_level_role_award_rejects_invalid_grant_mode() -> None:
    with pytest.raises(ValueError):
        LevelRoleAward(guild_id="1", level=3, role_id="123", grant_mode="invalid")


def test_level_xp_weight_change_log_allows_global_scope() -> None:
    row = LevelXpWeightChangeLog(
        guild_id=None,
        effective_from=__import__("datetime").date(2026, 5, 22),
        operation="seed",
        new_message_weight=3.0,
        new_reaction_received_weight=2.0,
        new_reaction_given_weight=2.0,
    )
    assert row.guild_id is None


def test_level_xp_weight_change_log_rejects_bad_actor_id() -> None:
    with pytest.raises(ValueError):
        LevelXpWeightChangeLog(
            guild_id="1",
            actor_id="not-a-snowflake",
            effective_from=__import__("datetime").date(2026, 5, 22),
            operation="update",
            new_message_weight=3.0,
            new_reaction_received_weight=2.0,
            new_reaction_given_weight=2.0,
        )
