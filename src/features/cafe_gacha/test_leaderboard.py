from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import CafeGachaDraw, ExcludedUser, GuildMemberMeta
from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.cafe_gacha.leaderboard import (
    cafe_leaderboard_snapshot,
    rank_cafe_leaderboard,
)

GUILD_ID = "1001"


def _draw(
    *,
    event_id: str,
    user_id: str,
    reward_key: str,
    owned_count: int,
) -> CafeGachaDraw:
    card = CARDS_BY_KEY[reward_key]
    return CafeGachaDraw(
        event_id=event_id,
        batch_id=event_id,
        batch_position=1,
        guild_id=GUILD_ID,
        user_id=user_id,
        display_name=f"客{user_id}",
        draw_type="free",
        cost_xp=0,
        reward_xp=card.draw_reward_xp,
        reward_key=card.key,
        reward_name=card.name,
        reward_description=card.description,
        rarity=card.rarity,
        image_filename=card.image_filename,
        exchange_xp=card.exchange_xp,
        was_duplicate=owned_count > 1,
        owned_count=owned_count,
        collected_count=1,
    )


def _add_card_copies(
    session: AsyncSession,
    *,
    user_id: str,
    reward_key: str,
    count: int,
) -> None:
    for index in range(count):
        session.add(
            _draw(
                event_id=f"ranking-{user_id}-{reward_key}-{index}",
                user_id=user_id,
                reward_key=reward_key,
                owned_count=index + 1,
            )
        )


async def test_one_snapshot_supports_all_ten_cafe_rankings(
    db_session: AsyncSession,
) -> None:
    # 2001: 1枚を看板メニューまで育て、熟練度とN棚を先行。
    _add_card_copies(db_session, user_id="2001", reward_key="k-pan", count=25)
    _add_card_copies(db_session, user_id="2001", reward_key="scone", count=3)
    _add_card_copies(db_session, user_id="2001", reward_key="hon-gyokuro", count=1)

    # 2002: 異なる4種を集め、図鑑を先行。
    for key in ("house-blend", "scone", "genmaicha", "cocoa"):
        _add_card_copies(db_session, user_id="2002", reward_key=key, count=1)

    # 2003: ぎりぎりモーニングを完成。
    for key in ("k-pan", "instant-coffee", "jam-toast"):
        _add_card_copies(db_session, user_id="2003", reward_key=key, count=1)

    # 2004: R以上の異なる2種を収集。
    for key in (
        "hon-gyokuro",
        "darjeeling-first-flush",
        "beethoven-sixty-bean-coffee",
    ):
        _add_card_copies(db_session, user_id="2004", reward_key=key, count=1)

    # 表示除外ユーザーは、記録が多くても全ランキングから除外される。
    for key in list(CARDS_BY_KEY)[:10]:
        _add_card_copies(db_session, user_id="2999", reward_key=key, count=25)
    db_session.add(ExcludedUser(guild_id=GUILD_ID, user_id="2999"))
    _add_card_copies(db_session, user_id="2888", reward_key="k-pan", count=25)
    db_session.add(GuildMemberMeta(guild_id=GUILD_ID, user_id="2888", is_active=False))
    await db_session.commit()

    snapshot = await cafe_leaderboard_snapshot(db_session, guild_id=GUILD_ID)

    assert [entry.user_id for entry in rank_cafe_leaderboard(snapshot, "collection")][
        :2
    ] == ["2002", "2004"]
    assert rank_cafe_leaderboard(snapshot, "mastery")[0].user_id == "2001"
    assert rank_cafe_leaderboard(snapshot, "sets")[0].user_id == "2003"
    assert rank_cafe_leaderboard(snapshot, "rare")[0].user_id == "2004"
    assert rank_cafe_leaderboard(snapshot, "treasure")[0].user_id == "2004"
    assert rank_cafe_leaderboard(snapshot, "joke")[0].user_id == "2001"
    assert rank_cafe_leaderboard(snapshot, "coffee")[0].user_id == "2002"
    assert rank_cafe_leaderboard(snapshot, "tea")[0].user_id == "2004"
    assert rank_cafe_leaderboard(snapshot, "sweets")[0].user_id == "2001"
    assert rank_cafe_leaderboard(snapshot, "culture")[0].user_id == "2001"
    assert all(entry.user_id != "2999" for entry in snapshot.entries)
    assert all(entry.user_id != "2888" for entry in snapshot.entries)

    mastery = next(entry for entry in snapshot.entries if entry.user_id == "2001")
    assert mastery.collection_count == 3
    assert mastery.mastery_score == 29
    assert mastery.signature_cards == 1
    assert mastery.familiar_cards == 1
    assert mastery.discovery_cards == 1
    assert mastery.n_collection_count == 1
    assert mastery.n_mastery_score == 25
    assert mastery.coffee_collection_count == 0
    assert mastery.tea_mastery_score == 1
    assert mastery.sweets_mastery_score == 3
    assert mastery.culture_mastery_score == 25
    assert mastery.culture_signature_cards == 1

    treasure = next(entry for entry in snapshot.entries if entry.user_id == "2004")
    assert treasure.treasure_collection_count == 1
    assert treasure.rare_ur_count == 1
    assert treasure.rare_mythic_count == 0

    set_collector = next(entry for entry in snapshot.entries if entry.user_id == "2003")
    assert set_collector.completed_sets == 1


def test_rank_positions_use_documented_tiebreakers() -> None:
    from src.features.cafe_gacha.leaderboard import (
        CafeLeaderboardEntry,
        CafeLeaderboardSnapshot,
    )

    lower_tiebreak = CafeLeaderboardEntry(
        user_id="2001",
        collection_count=10,
        total_draws=10,
        mastery_score=10,
        discovery_cards=10,
        familiar_cards=0,
        regular_cards=0,
        signature_cards=0,
        completed_sets=1,
        rare_collection_count=1,
        rare_r_count=1,
        rare_sr_count=0,
        rare_ssr_count=0,
        rare_ur_count=0,
        rare_mythic_count=0,
        treasure_collection_count=0,
        n_collection_count=5,
        n_mastery_score=5,
        n_signature_cards=0,
    )
    higher_tiebreak = CafeLeaderboardEntry(
        user_id="2002",
        collection_count=10,
        total_draws=20,
        mastery_score=20,
        discovery_cards=5,
        familiar_cards=5,
        regular_cards=0,
        signature_cards=0,
        completed_sets=2,
        rare_collection_count=2,
        rare_r_count=2,
        rare_sr_count=0,
        rare_ssr_count=0,
        rare_ur_count=1,
        rare_mythic_count=0,
        treasure_collection_count=1,
        n_collection_count=5,
        n_mastery_score=10,
        n_signature_cards=0,
    )
    snapshot = CafeLeaderboardSnapshot(entries=(lower_tiebreak, higher_tiebreak))

    collection = rank_cafe_leaderboard(snapshot, "collection")
    assert [(item.rank, item.user_id) for item in collection] == [
        (1, "2002"),
        (2, "2001"),
    ]
    assert rank_cafe_leaderboard(snapshot, "sets")[0].user_id == "2002"
    assert rank_cafe_leaderboard(snapshot, "rare")[0].user_id == "2002"
    assert [
        (item.rank, item.user_id)
        for item in rank_cafe_leaderboard(snapshot, "treasure")
    ] == [(1, "2002")]
    assert rank_cafe_leaderboard(snapshot, "joke")[0].user_id == "2002"
