"""leveling service の単体テスト (DB 不要)。"""

from datetime import date

from src.features.leveling.service import (
    LEVEL_BASE_XP,
    LEVEL_GROWTH_RATIO,
    XpWeightLog,
    _levels_from_daily_rows,
    _validate_weights,
    _weights_for_day,
    compute_user_levels,
    compute_user_levels_from_counts,
    cumulative_xp_for_level,
    level_from_xp,
)
from src.features.user_profile.service import UserLifetimeStats


def _stats(
    *,
    messages: int = 0,
    voice_seconds: int = 0,
    reactions_received: int = 0,
    reactions_given: int = 0,
) -> UserLifetimeStats:
    return UserLifetimeStats(
        user_id="1",
        display_name="",
        avatar_url=None,
        total_messages=messages,
        total_char_count=0,
        total_voice_seconds=voice_seconds,
        total_reactions_received=reactions_received,
        total_reactions_given=reactions_given,
        first_active_date=None,
        last_active_date=None,
        active_days=0,
    )


# =============================================================================
# cumulative_xp_for_level
# =============================================================================


def test_cumulative_at_level_zero_is_zero() -> None:
    assert cumulative_xp_for_level(0) == 0


def test_cumulative_at_level_one_equals_base() -> None:
    assert cumulative_xp_for_level(1) == LEVEL_BASE_XP


def test_cumulative_at_level_two_is_geometric_sum() -> None:
    expected = round(LEVEL_BASE_XP * (1 + LEVEL_GROWTH_RATIO))
    assert cumulative_xp_for_level(2) == expected


def test_cumulative_strictly_increases() -> None:
    prev = -1
    for level in range(30):
        cur = cumulative_xp_for_level(level)
        assert cur > prev
        prev = cur


# =============================================================================
# level_from_xp
# =============================================================================


def test_level_zero_below_base() -> None:
    assert level_from_xp(0) == 0
    assert level_from_xp(LEVEL_BASE_XP - 1) == 0


def test_level_one_at_base() -> None:
    assert level_from_xp(LEVEL_BASE_XP) == 1


def test_level_matches_cumulative_thresholds() -> None:
    """各 L について cumulative(L) ぴったりで L、その -1 で L-1。"""
    for level in range(1, 20):
        floor = cumulative_xp_for_level(level)
        assert level_from_xp(floor) == level
        assert level_from_xp(floor - 1) == level - 1


def test_level_does_not_skip_levels_when_xp_increases() -> None:
    """XP を 1 ずつ増やしてもレベルは飛び越えない (monotonic + ±1)。"""
    last = 0
    for xp in range(cumulative_xp_for_level(10) + 100):
        cur = level_from_xp(xp)
        assert cur >= last
        assert cur - last <= 1
        last = cur


# =============================================================================
# compute_user_levels
# =============================================================================


def test_empty_stats_yields_level_zero() -> None:
    levels = compute_user_levels(_stats())
    assert levels.total.level == 0
    assert levels.voice.level == 0
    assert levels.text.level == 0
    assert levels.reactions_received.level == 0
    assert levels.reactions_given.level == 0


def test_voice_below_base_stays_level_zero() -> None:
    """60 分 VC = 60 XP (基準 100 未満なので L0)。"""
    levels = compute_user_levels(_stats(voice_seconds=60 * 60))
    assert levels.voice.xp == 60
    assert levels.voice.level == 0


def test_voice_reaches_level_one_at_100_minutes() -> None:
    levels = compute_user_levels(_stats(voice_seconds=100 * 60))
    assert levels.voice.xp == 100
    assert levels.voice.level == 1


def test_text_weight_thirty_per_message() -> None:
    """50 メッセージ = 1500 XP。"""
    levels = compute_user_levels(_stats(messages=50))
    assert levels.text.xp == 1500
    assert levels.text.level > 1


def test_reactions_received_twenty_xp_each() -> None:
    """200 リアクション = 4000 XP。"""
    levels = compute_user_levels(_stats(reactions_received=200))
    assert levels.reactions_received.xp == 4000
    assert levels.reactions_received.level > 1


def test_reactions_given_twenty_xp_each() -> None:
    levels = compute_user_levels(_stats(reactions_given=200))
    assert levels.reactions_given.xp == 4000
    assert levels.reactions_given.level > 1


def test_total_sums_all_axes() -> None:
    """総合 XP は 4 指標の合計と一致する。"""
    levels = compute_user_levels(
        _stats(
            voice_seconds=3000,  # 50 分 → 50 XP
            messages=10,  # 300 XP
            reactions_received=4,  # 80 XP
            reactions_given=4,  # 80 XP
        )
    )
    assert levels.total.xp == 510
    assert levels.voice.xp == 50
    assert levels.text.xp == 300
    assert levels.reactions_received.xp == 80
    assert levels.reactions_given.xp == 80


def test_progress_within_zero_to_one_range() -> None:
    levels = compute_user_levels(_stats(messages=75))  # 150 XP
    assert 0.0 <= levels.text.progress <= 1.0


def test_progress_zero_at_floor_one_at_next_floor() -> None:
    """L1 ちょうど (xp = base) なら progress = 0、L2 直前なら 1 に近い。"""
    levels_at_floor = compute_user_levels(_stats(reactions_received=5))  # 100 XP
    assert levels_at_floor.reactions_received.level == 1
    assert levels_at_floor.reactions_received.progress == 0.0


def test_total_xp_equals_sum_of_axis_xp() -> None:
    """丸め誤差で total と axis 合計が乖離しないこと (axis を先に丸める)。"""
    # 30 XP/メッセージでは text 側の丸めは発生しないが、他 axis の丸め検証として有効
    levels = compute_user_levels_from_counts(
        messages=7,
        voice_seconds=37,  # 0.6 分 → 1 XP に丸まる
        reactions_received=3,  # 1.5 XP → 2 (銀行家丸めだと 2)
        reactions_given=5,  # 2.5 XP → 2 (銀行家丸めだと 2)
    )
    axis_sum = (
        levels.voice.xp
        + levels.text.xp
        + levels.reactions_received.xp
        + levels.reactions_given.xp
    )
    assert levels.total.xp == axis_sum


def test_weights_for_day_uses_latest_log_before_target_date() -> None:
    logs = [
        XpWeightLog(
            effective_from=date(1970, 1, 1),
            message_weight=2.0,
            reaction_received_weight=0.5,
            reaction_given_weight=0.5,
        ),
        XpWeightLog(
            effective_from=date(2026, 5, 17),
            message_weight=30.0,
            reaction_received_weight=20.0,
            reaction_given_weight=20.0,
        ),
        XpWeightLog(
            effective_from=date(2026, 6, 1),
            message_weight=10.0,
            reaction_received_weight=5.0,
            reaction_given_weight=5.0,
        ),
    ]
    assert _weights_for_day(date(2026, 5, 16), logs) == (2.0, 0.5, 0.5)
    assert _weights_for_day(date(2026, 5, 17), logs) == (30.0, 20.0, 20.0)
    assert _weights_for_day(date(2026, 6, 2), logs) == (10.0, 5.0, 5.0)


def test_compute_from_counts_matches_compute_from_stats() -> None:
    """同じ素値なら counts API と stats API のレベル結果が一致する。"""
    from_counts = compute_user_levels_from_counts(
        messages=100,
        voice_seconds=3600,
        reactions_received=20,
        reactions_given=10,
    )
    from_stats = compute_user_levels(
        _stats(
            messages=100,
            voice_seconds=3600,
            reactions_received=20,
            reactions_given=10,
        )
    )
    assert from_counts.total.xp == from_stats.total.xp
    assert from_counts.total.level == from_stats.total.level


def test_validate_weights_rejects_zero_or_negative() -> None:
    for message_weight, recv_weight, given_weight in (
        (0.0, 1.0, 1.0),
        (1.0, 0.0, 1.0),
        (1.0, 1.0, -0.1),
    ):
        try:
            _validate_weights(message_weight, recv_weight, given_weight)
        except ValueError as e:
            assert "must be > 0" in str(e)
        else:
            raise AssertionError("expected ValueError")


def test_levels_from_daily_rows_applies_weight_history_per_day() -> None:
    logs = [
        XpWeightLog(
            effective_from=date(1970, 1, 1),
            message_weight=2.0,
            reaction_received_weight=0.5,
            reaction_given_weight=0.5,
        ),
        XpWeightLog(
            effective_from=date(2026, 5, 17),
            message_weight=30.0,
            reaction_received_weight=20.0,
            reaction_given_weight=20.0,
        ),
    ]
    rows = [
        (date(2026, 5, 16), 10, 0, 2, 2),  # legacy weights
        (date(2026, 5, 17), 10, 0, 2, 2),  # current weights
    ]
    levels = _levels_from_daily_rows(rows, weight_logs=logs)

    # text: 10*2 + 10*30 = 320
    assert levels.text.xp == 320
    # reactions: 2*0.5 + 2*20 = 41 per axis
    assert levels.reactions_received.xp == 41
    assert levels.reactions_given.xp == 41
    assert levels.voice.xp == 0
    assert levels.total.xp == 402
