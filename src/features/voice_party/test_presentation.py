from src.features.voice_party.presentation import (
    voice_party_current_embed,
    voice_party_ended_embed,
    voice_party_started_embed,
)


def test_voice_party_embeds_explain_multiplier_and_state() -> None:
    started = voice_party_started_embed(3)
    current = voice_party_current_embed(4)
    ended = voice_party_ended_embed()

    assert started.title == "☕ ティーパーティーボーナス開始！"
    assert "1.5倍" in str(started.description)
    assert "2.5倍" in str(started.description)
    assert started.fields[0].value == "3人"
    assert current.title == "☕ ティーパーティーボーナス開催中！"
    assert current.fields[0].value == "4人"
    assert "2.5倍" in str(current.description)
    assert ended.title == "☕ ティーパーティーボーナス終了"
    assert "通常に戻りました" in str(ended.description)
