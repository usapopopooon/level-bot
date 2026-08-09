from src.features.voice_party.presentation import (
    cafe_talk_current_embed,
    cafe_talk_ended_embed,
    cafe_talk_started_embed,
    tea_carnival_current_embed,
    tea_carnival_ended_embed,
    tea_carnival_started_embed,
    tea_festival_current_embed,
    tea_festival_downgraded_embed,
    tea_festival_ended_embed,
    tea_festival_started_embed,
    voice_party_current_embed,
    voice_party_downgraded_embed,
    voice_party_ended_embed,
    voice_party_started_embed,
)


def test_cafe_talk_embeds_keep_the_waiting_condition_hidden() -> None:
    started = cafe_talk_started_embed()
    current = cafe_talk_current_embed()
    ended = cafe_talk_ended_embed()

    assert started.title == "☕ カフェトークボーナス！"
    assert "ここまでの時間を含め" in str(started.description)
    assert "1.25倍" in str(started.description)
    assert "10分" not in str(started.description)
    assert "3人" not in str(started.description)
    assert current.title == "☕ カフェトークボーナス中"
    assert ended.title == "☕ カフェトークボーナス終了"


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


def test_tea_carnival_embeds_explain_upgrade_and_downgrade() -> None:
    started = tea_carnival_started_embed(10)
    current = tea_carnival_current_embed(11)
    downgraded = tea_festival_downgraded_embed(9)
    ended = tea_carnival_ended_embed()

    assert started.title == "🎪 ティーカーニバルボーナス開始！"
    assert "2.5倍" in str(started.description)
    assert started.fields[0].value == "10人"
    assert current.title == "🎪 ティーカーニバルボーナス開催中！"
    assert "2.5倍" in str(current.description)
    assert current.fields[0].value == "11人"
    assert downgraded.title == "🫖 ティーフェスティバルボーナスに移行しました"
    assert "2倍" in str(downgraded.description)
    assert downgraded.fields[0].value == "9人"
    assert ended.title == "🎪 ティーカーニバルボーナス終了"
    assert "通常に戻りました" in str(ended.description)
