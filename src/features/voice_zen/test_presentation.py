from src.features.voice_zen.presentation import (
    voice_zen_ended_embed,
    voice_zen_reward_embed,
)


def test_ten_minute_embed_makes_feature_discoverable() -> None:
    embed = voice_zen_reward_embed(user_id="11", minutes=10, xp=10)

    assert embed.title == "🧘 禅タイム開始！"
    assert "10分間" in (embed.description or "")
    assert "10 XP" in (embed.description or "")


def test_later_milestone_and_end_embeds_are_clear() -> None:
    reward = voice_zen_reward_embed(user_id="11", minutes=180, xp=200)
    joined = voice_zen_ended_embed(user_id="11", participant_count=2)
    left = voice_zen_ended_embed(user_id="11", participant_count=0)
    muted = voice_zen_ended_embed(
        user_id="11", participant_count=1, user_still_present=True
    )

    assert reward.title == "🧘 禅タイム3時間達成！"
    assert "200 XP" in (reward.description or "")
    assert "仲間が加わりました" in (joined.description or "")
    assert "VCから退出" in (left.description or "")
    assert "ミュート状態" in (muted.description or "")
