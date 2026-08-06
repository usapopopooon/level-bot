from src.features.voice_party.presentation import (
    tea_festival_current_embed,
    tea_festival_ended_embed,
    tea_festival_started_embed,
    voice_party_current_embed,
    voice_party_downgraded_embed,
    voice_party_ended_embed,
    voice_party_started_embed,
)


def test_voice_party_embeds_explain_multiplier_and_state() -> None:
    started = voice_party_started_embed(3)
    current = voice_party_current_embed(4)
    ended = voice_party_ended_embed()

    assert started.title == "☕ ティーパーティーボーナス開始！"
    assert "1.5倍" in str(started.description)
    assert started.fields[0].value == "3人"
    assert current.title == "☕ ティーパーティーボーナス開催中！"
    assert current.fields[0].value == "4人"
    assert ended.title == "☕ ティーパーティーボーナス終了"
    assert "通常に戻りました" in str(ended.description)


def test_tea_festival_embeds_explain_upgrade_and_downgrade() -> None:
    started = tea_festival_started_embed(5)
    current = tea_festival_current_embed(6)
    downgraded = voice_party_downgraded_embed(4)
    ended = tea_festival_ended_embed()

    assert started.title == "🫖 ティーフェスティバルボーナス開始！"
    assert "2倍" in str(started.description)
    assert started.fields[0].value == "5人"
    assert current.title == "🫖 ティーフェスティバルボーナス開催中！"
    assert "2倍" in str(current.description)
    assert current.fields[0].value == "6人"
    assert downgraded.title == "☕ ティーパーティーボーナスに移行しました"
    assert "1.5倍" in str(downgraded.description)
    assert downgraded.fields[0].value == "4人"
    assert ended.title == "🫖 ティーフェスティバルボーナス終了"
    assert "通常に戻りました" in str(ended.description)
