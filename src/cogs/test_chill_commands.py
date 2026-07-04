from src.cogs.chill_commands import (
    build_chill_place_choices,
    format_chill_display,
    format_chill_list,
    resolve_chill_place_selection,
)
from src.features.chill.presets import build_chill_places, resolve_chill_display


def test_resolve_chill_place_selection_accepts_level_and_names() -> None:
    places = build_chill_places()

    by_level = resolve_chill_place_selection(places, "8")
    by_name = resolve_chill_place_selection(places, "ふかふかチェア")
    by_display_name = resolve_chill_place_selection(places, "💤 ふかふかチェア")
    by_choice = resolve_chill_place_selection(places, "💤 ふかふかチェア (Lv.8)")

    assert by_level is not None
    assert by_name is not None
    assert by_display_name is not None
    assert by_choice is not None
    assert by_level.name == "ふかふかチェア"
    assert by_name.required_level == 8
    assert by_display_name.required_level == 8
    assert by_choice.required_level == 8
    assert resolve_chill_place_selection(places, "ない場所") is None


def test_build_chill_place_choices_filters_by_name() -> None:
    places = build_chill_places()

    choices = build_chill_place_choices(places, "ソファ")

    assert [choice.name for choice in choices] == [
        "🛋️ ロビーソファ (Lv.2)",
        "🕯️ 半個室ソファ (Lv.18)",
    ]
    assert [choice.value for choice in choices] == ["2", "18"]


def test_format_chill_list_marks_unlock_status() -> None:
    text = format_chill_list(build_chill_places(), level=2)

    assert "✓ Lv.1 🪑 入口のベンチ" in text
    assert "✓ Lv.2 🛋️ ロビーソファ" in text
    assert "□ Lv.3 🪟 窓際スツール" in text


def test_format_chill_display_includes_vibe_and_next_place() -> None:
    display = resolve_chill_display(build_chill_places(), level=8)

    assert display is not None
    text = format_chill_display(display)

    assert "💤 ふかふかチェア (Lv.8)" in text
    assert "まったり / 休憩" in text
    assert "ちょっと疲れた日に沈み込む席。" in text
    assert "次の解放: 🔌 充電席 Lv.9" in text
