from src.features.cafe_gacha.mastery import mastery_tier, next_mastery_tier


def test_mastery_tiers_cover_every_boundary() -> None:
    assert mastery_tier(0) is None
    tiers = [mastery_tier(count) for count in (1, 3, 10, 25)]
    assert all(tier is not None for tier in tiers)
    assert [tier.name for tier in tiers if tier is not None] == [
        "発見",
        "なじみ",
        "常連",
        "看板メニュー",
    ]
    next_tier = next_mastery_tier(24)
    assert next_tier is not None
    assert next_tier.minimum_count == 25
    assert next_mastery_tier(25) is None
