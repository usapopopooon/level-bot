from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest

from src.cogs import cafe_gacha as cafe_gacha_cog
from src.cogs import cafe_gacha_collection as cafe_gacha_collection_ui
from src.cogs import cafe_gacha_draw as cafe_gacha_draw_ui
from src.cogs.cafe_gacha import (
    BulkExchangeButton,
    CafeGachaCog,
    CafeGachaPanelView,
    CollectionView,
    DynamicCafeDrawButton,
    DynamicCafeTenDrawButton,
    IndividualExchangeButton,
    ProtectionButton,
    RedemptionQuantityView,
    _affordable_batch_count,
    _draw_confirmation_text,
    _exchange_guidance,
    _find_or_create_channel,
    _perform_draw,
    _result_embed,
    _upsert_panel,
    build_panel_embed,
)
from src.database.models import CafeGachaDraw
from src.features.cafe_gacha import service as cafe_gacha_service
from src.features.cafe_gacha.catalog import CARDS, CARDS_BY_KEY
from src.features.color_role_shop.service import Wallet
from src.features.feature_access import service as feature_access_service
from src.features.feature_access.service import CAFE_GACHA


def test_legacy_cafe_module_reexports_collection_choice() -> None:
    assert cafe_gacha_cog.CollectionChoice is cafe_gacha_collection_ui.CollectionChoice


def test_analytics_embed_is_private_admin_summary_without_mentions() -> None:
    analytics = cafe_gacha_service.GuildAnalytics(
        draws_today=3,
        draws_7d=20,
        total_draws=100,
        active_today=2,
        active_7d=8,
        total_users=12,
        new_7d=5,
        duplicate_7d=15,
        rarity_7d=(("C", 10), ("UC", 6), ("R", 4)),
        spent_xp_7d=300,
        draw_reward_xp_7d=700,
        redemption_xp_7d=200,
        completed_users=1,
    )

    embed = cafe_gacha_cog._analytics_embed(analytics)

    rendered = str(embed.to_dict())
    assert "本日 **3回** / 7日 **20回** / 累計 **100回**" in rendered
    assert "NEW **5回** (25.0%)" in rendered
    assert "純増 **+600 XP**" in rendered
    assert "<@" not in rendered


async def test_panel_routes_every_button_to_same_guild() -> None:
    view = CafeGachaPanelView(123456)
    assert view.is_persistent()
    custom_ids: list[str | None] = []
    rows: list[int | None] = []
    for child in view.children:
        item = cast(
            discord.ui.Button[discord.ui.View],
            child.item if isinstance(child, discord.ui.DynamicItem) else child,
        )
        custom_ids.append(item.custom_id)
        rows.append(item.row)

    assert custom_ids == [
        "level:cafe:draw:123456",
        "level:cafe:draw10:123456",
        "level:cafe:collection:123456",
        "level:cafe:balance:123456",
        None,
    ]
    draw_button = view.children[0]
    assert isinstance(draw_button, discord.ui.DynamicItem)
    assert draw_button.item.label == "一枚引く"
    ten_draw_button = view.children[1]
    assert isinstance(ten_draw_button, discord.ui.DynamicItem)
    assert ten_draw_button.item.label == "まとめて引く（最大10枚）"
    collection_button = view.children[2]
    assert isinstance(collection_button, discord.ui.DynamicItem)
    assert collection_button.item.label == "自分の棚・重複交換"
    balance_button = view.children[3]
    assert isinstance(balance_button, discord.ui.DynamicItem)
    assert balance_button.item.label == "自分のXP・残り枠"
    catalog_button = view.children[4]
    assert isinstance(catalog_button, discord.ui.Button)
    assert catalog_button.label == "Web図鑑・排出率"
    assert catalog_button.url == "https://chill-cafe.site/cafe-collection/"
    assert rows == [0, 0, 1, 1, 1]


async def test_draw_button_checks_access_before_drawing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=False)
    perform_draw = AsyncMock()
    response = SimpleNamespace(defer=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(response=response, id=9001, user=SimpleNamespace(id=3001)),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "ensure_feature_access", access)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_perform_draw", perform_draw)

    await DynamicCafeDrawButton(1001).callback(interaction)

    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=CAFE_GACHA,
    )
    response.defer.assert_not_awaited()
    perform_draw.assert_not_awaited()


async def test_draw_button_prepares_free_or_confirmed_paid_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=True)
    prepare_draw = AsyncMock()
    response = SimpleNamespace(defer=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            id=9001,
            response=response,
            user=SimpleNamespace(id=3001),
        ),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "ensure_feature_access", access)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_prepare_draw", prepare_draw)

    await DynamicCafeDrawButton(1001).callback(interaction)

    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=CAFE_GACHA,
    )
    response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    prepare_draw.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        requested_count=1,
    )


async def test_batch_draw_button_prepares_up_to_ten_draws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=True)
    prepare_draw = AsyncMock()
    response = SimpleNamespace(defer=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(id=9010, response=response, user=SimpleNamespace(id=3001)),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "ensure_feature_access", access)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_prepare_draw", prepare_draw)

    await DynamicCafeTenDrawButton(1001).callback(interaction)

    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=CAFE_GACHA,
    )
    response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    prepare_draw.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        requested_count=10,
    )


def test_paid_confirmation_shows_cost_balance_and_hourly_slots() -> None:
    availability = cafe_gacha_service.DrawAvailability(
        wallet=Wallet(total_xp=500, spent_xp=100),
        has_free_draw=False,
        hourly_remaining=7,
    )

    assert _affordable_batch_count(availability) == 7
    assert _draw_confirmation_text(availability, count=7) == (
        "**7枚をまとめて引きます**。\n"
        "現在XP: **400 XP**\n"
        "消費: **140 XP**\n"
        "最低獲得: **175 XP**\n"
        "抽選後: **435 XP以上**\n"
        "この時間の残り枠: 7 → **0回**"
    )


def test_free_draw_is_included_when_calculating_affordable_batch() -> None:
    availability = cafe_gacha_service.DrawAvailability(
        wallet=Wallet(total_xp=40, spent_xp=0),
        has_free_draw=True,
        hourly_remaining=10,
    )

    assert _affordable_batch_count(availability) == 10
    assert availability.cost_for(10) == 180


@pytest.mark.parametrize(
    ("available_xp", "has_free_draw", "hourly_remaining", "expected"),
    (
        (0, True, 10, 10),
        (0, False, 10, 0),
        (19, False, 10, 0),
        (20, False, 10, 10),
        (20, True, 7, 7),
    ),
)
def test_batch_count_matches_sequential_guaranteed_xp_oracle(
    available_xp: int,
    has_free_draw: bool,
    hourly_remaining: int,
    expected: int,
) -> None:
    availability = cafe_gacha_service.DrawAvailability(
        wallet=Wallet(total_xp=available_xp, spent_xp=0),
        has_free_draw=has_free_draw,
        hourly_remaining=hourly_remaining,
    )

    assert _affordable_batch_count(availability) == expected


def test_batch_count_matches_exhaustive_sequential_pseudo_oracle() -> None:
    def expected_count(balance: int, has_free_draw: bool, slots: int) -> int:
        count = 0
        for index in range(slots):
            cost_xp = 0 if has_free_draw and index == 0 else 20
            if balance < cost_xp:
                break
            balance = balance - cost_xp + 25
            count += 1
        return count

    for available_xp in range(501):
        for has_free_draw in (False, True):
            for hourly_remaining in range(11):
                availability = cafe_gacha_service.DrawAvailability(
                    wallet=Wallet(total_xp=available_xp, spent_xp=0),
                    has_free_draw=has_free_draw,
                    hourly_remaining=hourly_remaining,
                )
                assert _affordable_batch_count(availability) == expected_count(
                    available_xp,
                    has_free_draw,
                    hourly_remaining,
                )


def test_zero_xp_free_batch_confirmation_never_displays_a_negative_balance() -> None:
    availability = cafe_gacha_service.DrawAvailability(
        wallet=Wallet(total_xp=0, spent_xp=0),
        has_free_draw=True,
        hourly_remaining=10,
    )

    content = _draw_confirmation_text(availability, count=10)

    assert "消費: **180 XP**" in content
    assert "最低獲得: **250 XP**" in content
    assert "抽選後: **70 XP以上**" in content
    assert "獲得XPを次の1枚の費用に充てながら引きます。" in content
    assert "-" not in content


async def test_prepare_draw_uses_guaranteed_rewards_to_offer_ten_from_zero_xp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    availability = cafe_gacha_service.DrawAvailability(
        wallet=Wallet(total_xp=0, spent_xp=0),
        has_free_draw=True,
        hourly_remaining=10,
    )
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            user=SimpleNamespace(id=2001),
            followup=followup,
        ),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "_earned_xp", AsyncMock(return_value=0))
    monkeypatch.setattr(cafe_gacha_draw_ui, "async_session", _SessionContext)
    monkeypatch.setattr(
        cafe_gacha_service,
        "draw_availability",
        AsyncMock(return_value=availability),
    )

    await cafe_gacha_cog._prepare_draw(
        interaction,
        guild_id=1001,
        requested_count=10,
    )

    confirmation = followup.send.await_args.kwargs["view"]
    assert isinstance(confirmation, cafe_gacha_cog.DrawConfirmView)
    assert confirmation.count == 10
    assert confirmation.expected_cost_xp == 180


async def test_prepare_single_draw_rejects_insufficient_xp_before_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    availability = cafe_gacha_service.DrawAvailability(
        wallet=Wallet(total_xp=19, spent_xp=0),
        has_free_draw=False,
        hourly_remaining=10,
    )
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            user=SimpleNamespace(id=2001),
            followup=followup,
        ),
    )
    perform_draw = AsyncMock()
    monkeypatch.setattr(cafe_gacha_draw_ui, "_earned_xp", AsyncMock(return_value=19))
    monkeypatch.setattr(cafe_gacha_draw_ui, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_perform_draw", perform_draw)
    monkeypatch.setattr(
        cafe_gacha_service,
        "draw_availability",
        AsyncMock(return_value=availability),
    )

    await cafe_gacha_cog._prepare_draw(
        interaction,
        guild_id=1001,
        requested_count=1,
    )

    followup.send.assert_awaited_once_with(
        "XPが足りません。現在 **19 XP** です。",
        ephemeral=True,
    )
    perform_draw.assert_not_awaited()


async def test_prepare_draw_carries_the_confirmed_cost_to_the_confirm_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    availability = cafe_gacha_service.DrawAvailability(
        wallet=Wallet(total_xp=400, spent_xp=0),
        has_free_draw=True,
        hourly_remaining=7,
    )
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            user=SimpleNamespace(id=2001),
            followup=followup,
        ),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "_earned_xp", AsyncMock(return_value=400))
    monkeypatch.setattr(cafe_gacha_draw_ui, "async_session", _SessionContext)
    monkeypatch.setattr(
        cafe_gacha_service,
        "draw_availability",
        AsyncMock(return_value=availability),
    )

    await cafe_gacha_cog._prepare_draw(
        interaction,
        guild_id=1001,
        requested_count=10,
    )

    confirmation = followup.send.await_args.kwargs["view"]
    assert isinstance(confirmation, cafe_gacha_cog.DrawConfirmView)
    assert confirmation.count == 7
    assert confirmation.expected_cost_xp == 120
    assert [
        child.label
        for child in confirmation.children
        if isinstance(child, discord.ui.Button)
    ] == ["この内容で引く", "キャンセル"]
    assert followup.send.await_args.kwargs["ephemeral"] is True


async def test_confirm_button_disappears_before_the_batch_draw_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perform_ten_draw = AsyncMock()
    response = SimpleNamespace(edit_message=AsyncMock())
    interaction = cast(discord.Interaction, SimpleNamespace(response=response))
    view = cafe_gacha_cog.DrawConfirmView(1001, 2001, 7, 120)
    confirm = view.children[0]
    assert isinstance(confirm, discord.ui.Button)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_perform_ten_draw", perform_ten_draw)

    await confirm.callback(interaction)

    response.edit_message.assert_awaited_once_with(
        content="抽選しています…",
        view=None,
    )
    perform_ten_draw.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        event_id=view.event_id,
        count=7,
        allow_paid=True,
        expected_cost_xp=120,
    )


async def test_individual_exchange_confirm_disappears_before_db_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    redeem_cards = AsyncMock(
        return_value=SimpleNamespace(status="unavailable", redemption=None)
    )
    response = SimpleNamespace(edit_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            user=SimpleNamespace(id=2001, display_name="客"),
            response=response,
            followup=followup,
        ),
    )
    view = cafe_gacha_cog.RedemptionConfirmView(1001, 2001, "k-pan", 1)
    confirm = view.children[0]
    assert isinstance(confirm, discord.ui.Button)
    monkeypatch.setattr(
        cafe_gacha_collection_ui,
        "ensure_feature_access",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(cafe_gacha_collection_ui, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "redeem_cards", redeem_cards)

    await confirm.callback(interaction)

    response.edit_message.assert_awaited_once_with(
        content="交換しています…",
        view=None,
    )
    redeem_cards.assert_awaited_once()


async def test_bulk_exchange_confirm_disappears_before_db_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    redeem_cards = AsyncMock(
        return_value=SimpleNamespace(status="unavailable", redemption=None)
    )
    response = SimpleNamespace(edit_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=1001),
            user=SimpleNamespace(id=2001, display_name="客"),
            response=response,
            followup=followup,
        ),
    )
    view = cafe_gacha_cog.BulkRedemptionConfirmView(1001, 2001, {"k-pan": 1})
    confirm = view.children[0]
    assert isinstance(confirm, discord.ui.Button)
    monkeypatch.setattr(
        cafe_gacha_collection_ui,
        "ensure_feature_access",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(cafe_gacha_collection_ui, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "redeem_cards", redeem_cards)

    await confirm.callback(interaction)

    response.edit_message.assert_awaited_once_with(
        content="交換しています…",
        view=None,
    )
    redeem_cards.assert_awaited_once()


def test_n_collection_milestones_are_clear_and_progressive() -> None:
    assert cafe_gacha_cog._n_collection_milestone(0) == (
        "N棚の入口",
        "最初の称号まであと 5種",
    )
    assert cafe_gacha_cog._n_collection_milestone(5)[0] == "☕ N棚見習い"
    assert cafe_gacha_cog._n_collection_milestone(10)[0] == "🧺 N棚コレクター"
    assert cafe_gacha_cog._n_collection_milestone(31) == (
        "🧺 N棚コレクター",
        "次の称号まであと 45種",
    )
    assert cafe_gacha_cog._n_collection_milestone(51) == (
        "🧺 N棚コレクター",
        "次の称号まであと 25種",
    )
    assert cafe_gacha_cog._n_collection_milestone(76) == (
        "🏆 N棚の主",
        "Nカード全76種を収集しました。",
    )


def test_collection_rarity_description_keeps_names_and_exchange_counts_visible() -> (
    None
):
    n_card = CARDS_BY_KEY["k-pan"]
    hn_card = CARDS_BY_KEY["scone"]
    collection = (
        cafe_gacha_service.CollectionCard(
            n_card, count=3, redeemable_count=2, lifetime_count=3
        ),
        cafe_gacha_service.CollectionCard(
            hn_card,
            count=1,
            redeemable_count=0,
            is_protected=True,
        ),
    )

    assert cafe_gacha_cog._collection_rarity_description(collection, "C") == (
        "**Kブロート** ×3（交換可 2） · ☕なじみ（累計3枚）"
    )
    assert cafe_gacha_cog._collection_rarity_description(collection, "UC") == (
        "**スコーン** ×1（🔒保護中）"
    )


async def test_cafe_access_role_command_writes_cafe_feature_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    add_role = AsyncMock(return_value=True)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(guild=SimpleNamespace(id=1001), response=response),
    )
    role = cast(discord.Role, SimpleNamespace(id=2001, mention="<@&2001>"))
    cog = CafeGachaCog(cast(Any, SimpleNamespace()))
    monkeypatch.setattr(cafe_gacha_cog, "async_session", _SessionContext)
    monkeypatch.setattr(
        feature_access_service,
        "add_access_role",
        add_role,
    )

    callback = cast(Any, CafeGachaCog.add_access_role.callback)
    await callback(cog, interaction, role)

    add_role.assert_awaited_once_with(
        ANY,
        guild_id="1001",
        feature=CAFE_GACHA,
        role_id="2001",
    )


def test_exchange_guidance_is_visible_with_and_without_duplicates() -> None:
    card = CARDS_BY_KEY["k-pan"]

    without_duplicates = _exchange_guidance(
        (cafe_gacha_service.CollectionCard(card, count=1, redeemable_count=0),)
    )
    with_duplicates = _exchange_guidance(
        (cafe_gacha_service.CollectionCard(card, count=3, redeemable_count=2),)
    )

    assert "2枚目以降" in without_duplicates
    assert "合計 **2枚**" in with_duplicates
    assert "個別・全重複交換" in with_duplicates
    assert "カフェメダル" in with_duplicates
    assert "最初の1枚は必ず残ります" in with_duplicates

    protected = _exchange_guidance(
        (
            cafe_gacha_service.CollectionCard(
                card,
                count=3,
                redeemable_count=2,
                is_protected=True,
            ),
        )
    )
    assert "交換できる重複カードはまだありません" in protected
    assert "保護中の重複 **2枚** は交換対象外" in protected


def test_collection_footer_repeats_card_protection_rule() -> None:
    assert cafe_gacha_collection_ui._collection_footer(87, 120) == (
        "収集 87/120種 · 最初の1枚と保護カードは残ります（交換対象は未保護の2枚目以降）"
    )
    embeds = [discord.Embed(title=f"棚 {index}") for index in range(8)]

    cafe_gacha_collection_ui._apply_collection_footer(embeds, owned=87, total=120)

    assert all(
        (embed.footer.text or "").endswith("（交換対象は未保護の2枚目以降）")
        for embed in embeds
    )


async def test_collection_separates_individual_and_all_card_exchange_buttons() -> None:
    card = CARDS_BY_KEY["k-pan"]
    collection = (cafe_gacha_service.CollectionCard(card, count=3, redeemable_count=2),)

    view = CollectionView(1001, 2001, collection)
    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]

    assert [button.label for button in buttons] == [
        "重複を選んでXP交換",
        "全重複をXP交換",
        "全重複をメダル交換",
        "メダル・棚テーマ",
        "保護カードを設定",
        "セットメニュー",
    ]
    assert [button.style for button in buttons] == [
        discord.ButtonStyle.primary,
        discord.ButtonStyle.success,
        discord.ButtonStyle.secondary,
        discord.ButtonStyle.secondary,
        discord.ButtonStyle.secondary,
        discord.ButtonStyle.secondary,
    ]
    assert [button.row for button in buttons] == [1, 1, 2, 2, 3, 3]
    assert not any(
        isinstance(child, discord.ui.Select)
        and child.placeholder == "交換するカードを1種類選ぶ"
        for child in view.children
    )

    quantity_view = RedemptionQuantityView(1001, 2001, card.key, 2)
    assert [
        child.label
        for child in quantity_view.children
        if isinstance(child, discord.ui.Button)
    ] == [
        "このカードを1枚交換",
        "このカードの重複を全交換",
        "このカードの枚数を指定",
    ]


async def test_individual_exchange_button_opens_card_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = CARDS_BY_KEY["k-pan"]
    collection = (cafe_gacha_service.CollectionCard(card, count=3, redeemable_count=2),)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(user=SimpleNamespace(id=2001), response=response),
    )
    monkeypatch.setattr(
        cafe_gacha_collection_ui,
        "ensure_feature_access",
        AsyncMock(return_value=True),
    )

    await IndividualExchangeButton(1001, 2001, collection).callback(interaction)

    response.send_message.assert_awaited_once()
    assert response.send_message.await_args.args == (
        "交換するカードのレアリティを選んでください。",
    )
    assert response.send_message.await_args.kwargs["ephemeral"] is True
    selector_view = response.send_message.await_args.kwargs["view"]
    assert isinstance(selector_view, cafe_gacha_cog.CollectionRaritySelectView)
    assert len(selector_view.children) == 1
    selector = selector_view.children[0]
    assert isinstance(selector, discord.ui.Select)
    assert selector.placeholder == "交換するカードのレアリティを選ぶ"


async def test_protection_button_opens_owned_card_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = CARDS_BY_KEY["k-pan"]
    collection = (cafe_gacha_service.CollectionCard(card, count=3, redeemable_count=2),)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(user=SimpleNamespace(id=2001), response=response),
    )
    monkeypatch.setattr(
        cafe_gacha_collection_ui,
        "ensure_feature_access",
        AsyncMock(return_value=True),
    )

    await ProtectionButton(1001, 2001, collection).callback(interaction)

    response.send_message.assert_awaited_once()
    content = response.send_message.await_args.args[0]
    assert "保護／解除" in content
    selector_view = response.send_message.await_args.kwargs["view"]
    selector = selector_view.children[0]
    assert isinstance(selector, discord.ui.Select)
    assert selector.placeholder == "保護設定するカードのレアリティを選ぶ"


async def test_protected_card_is_absent_from_every_exchange_button() -> None:
    card = CARDS_BY_KEY["k-pan"]
    collection = (
        cafe_gacha_service.CollectionCard(
            card,
            count=3,
            redeemable_count=2,
            is_protected=True,
        ),
    )

    view = CollectionView(1001, 2001, collection)
    labels = [
        child.label for child in view.children if isinstance(child, discord.ui.Button)
    ]

    assert labels == ["メダル・棚テーマ", "保護カードを設定", "セットメニュー"]


async def test_all_card_exchange_button_names_its_full_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = CARDS_BY_KEY["k-pan"]
    collection = (cafe_gacha_service.CollectionCard(card, count=3, redeemable_count=2),)
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(user=SimpleNamespace(id=2001), response=response),
    )
    monkeypatch.setattr(
        cafe_gacha_collection_ui,
        "ensure_feature_access",
        AsyncMock(return_value=True),
    )

    await BulkExchangeButton(1001, 2001, collection).callback(interaction)

    response.send_message.assert_awaited_once()
    content = response.send_message.await_args.args[0]
    assert content.startswith("交換可能な重複カードをすべてXPへ交換します。")
    assert "**各カードの最初の1枚と保護カードは残ります。**" in content
    confirm_view = response.send_message.await_args.kwargs["view"]
    assert [
        child.label
        for child in confirm_view.children
        if isinstance(child, discord.ui.Button)
    ][0] == "全重複をXPへ交換する"


async def test_264_card_collection_stays_within_discord_component_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = tuple(
        cafe_gacha_service.CollectionCard(card, count=2, redeemable_count=1)
        for card in CARDS
    )
    view = CollectionView(1001, 2001, collection)
    favorite_rarity = next(
        child for child in view.children if isinstance(child, discord.ui.Select)
    )
    favorite_cards = cafe_gacha_cog.FavoriteSelectView(
        1001, 2001, collection, "C"
    ).children[0]
    redemption_cards = cafe_gacha_cog.RedemptionSelectView(
        1001, 2001, collection, "UC"
    ).children[0]

    assert isinstance(favorite_cards, discord.ui.Select)
    assert isinstance(redemption_cards, discord.ui.Select)
    assert len(favorite_rarity.options) == 15
    assert len(favorite_cards.options) == 25
    assert len(redemption_cards.options) == 25
    favorite_page_two = cafe_gacha_cog.FavoriteSelectView(
        1001, 2001, collection, "C", 1
    ).children[0]
    redemption_page_two = cafe_gacha_cog.RedemptionSelectView(
        1001, 2001, collection, "UC", 1
    ).children[0]
    assert isinstance(favorite_page_two, discord.ui.Select)
    assert isinstance(redemption_page_two, discord.ui.Select)
    assert len(favorite_page_two.options) == 25
    assert len(redemption_page_two.options) == 25
    favorite_page_three = cafe_gacha_cog.FavoriteSelectView(
        1001, 2001, collection, "C", 2
    ).children[0]
    assert isinstance(favorite_page_three, discord.ui.Select)
    assert len(favorite_page_three.options) == 25

    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(user=SimpleNamespace(id=2001), response=response),
    )
    monkeypatch.setattr(
        cafe_gacha_collection_ui,
        "ensure_feature_access",
        AsyncMock(return_value=True),
    )
    await BulkExchangeButton(1001, 2001, collection).callback(interaction)

    content = response.send_message.await_args.args[0]
    assert len(content) < 2000
    assert "N: 76種・76枚" in content
    assert "HN: 70種・70枚" in content
    assert "SSR: 6種・6枚" in content


async def test_legacy_catalog_button_directs_to_the_web_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = cast(discord.Interaction, SimpleNamespace(response=response))
    monkeypatch.setattr(
        cafe_gacha_draw_ui,
        "ensure_feature_access",
        AsyncMock(return_value=True),
    )

    await cafe_gacha_cog.DynamicCafeCatalogButton(1001).callback(interaction)

    content = response.send_message.await_args.args[0]
    assert "Web図鑑" in content
    assert "https://chill-cafe.site/cafe-collection/" in content
    assert response.send_message.await_args.kwargs["ephemeral"] is True


def test_panel_concisely_highlights_guaranteed_profit_and_exchange() -> None:
    embed = build_panel_embed()
    content = embed.description or ""

    assert embed.title == cafe_gacha_cog.PANEL_TITLE
    assert content == (
        "カードを集めながら、**引くたびXPが必ず増える**コレクションです。\n\n"
        "**🎟️ 1日1回無料** / 2回目以降 20 XP / "
        "1時間10回まで / **1日の合計上限なし**\n"
        "**必ず黒字：25〜5000 XP獲得**（有料でも +5 XP以上）\n\n"
        "**✨ 抽選の獲得XP**　N 25 / HN 30 / R 60 / SR 150 / SSR 500 / "
        "UR 1500 / 幻 5000 XP\n"
        "**♻️ 重複交換XP**　N 5 / HN 10 / R 20 / SR 50 / SSR 150 / "
        "UR 500 / 幻 1500 XP\n"
        "未収集カードは、同じレアリティ内で **2倍** 出やすくなります。\n"
        "最初の1枚は必ず棚に残り、**2枚目以降だけ**交換できます。\n"
        "抽選結果はカフェ台帳に公開されます。\n\n"
        "詳しい排出率・カード解説・セットメニューは、下のWeb図鑑で確認できます。"
    )
    assert "総合レベルが下がる" not in content
    assert embed.image.url == "attachment://panel-cabinet.jpg"
    assert embed.footer.text == "1日1回の無料分は毎日 0:00に更新"


def test_next_hour_label_shows_the_actual_clock_time() -> None:
    now = datetime(2026, 8, 11, 14, 37, tzinfo=cafe_gacha_service.TOKYO)
    before_midnight = datetime(2026, 8, 11, 23, 59, tzinfo=cafe_gacha_service.TOKYO)

    assert cafe_gacha_cog._next_hour_label(now) == "15:00"
    assert cafe_gacha_cog._next_hour_label(before_midnight) == "00:00"


async def test_hourly_limit_is_explained_without_publishing_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    draw_card = AsyncMock(
        return_value=SimpleNamespace(status="hourly_limit", draw=None)
    )
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=123456),
            user=SimpleNamespace(id=2001, display_name="客"),
            followup=followup,
        ),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "_earned_xp", AsyncMock(return_value=100))
    monkeypatch.setattr(cafe_gacha_draw_ui, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "draw_card", draw_card)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_next_hour_label", lambda: "15:00")

    await _perform_draw(
        interaction,
        guild_id=123456,
        event_id="hourly-limit",
        allow_paid=True,
    )

    draw_card.assert_awaited_once()
    assert draw_card.await_args is not None
    assert draw_card.await_args.kwargs["allow_paid"] is True
    assert followup.send.await_args.args[0] == (
        "1時間の上限 **10回** に達しました。次は **15:00** から引けます。"
    )


async def test_ten_draw_hourly_limit_shows_specific_next_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    draw_cards = AsyncMock(
        return_value=SimpleNamespace(status="hourly_limit", draws=())
    )
    followup = SimpleNamespace(send=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=SimpleNamespace(id=123456),
            user=SimpleNamespace(id=2001, display_name="客"),
            followup=followup,
        ),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "_earned_xp", AsyncMock(return_value=500))
    monkeypatch.setattr(cafe_gacha_draw_ui, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "draw_cards", draw_cards)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_next_hour_label", lambda: "15:00")

    await cafe_gacha_cog._perform_ten_draw(
        interaction,
        guild_id=123456,
        event_id="ten-hourly-limit",
    )

    assert followup.send.await_args.args[0] == (
        "10枚のまとめ引きには、この時間の抽選枠が10回分必要です。"
        "次は **15:00** から引けます。"
    )
    assert followup.send.await_args.kwargs == {"ephemeral": True}


async def test_successful_draw_only_publishes_to_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    draw = object()
    wallet_after = SimpleNamespace(available_xp=125)
    draw_card = AsyncMock(
        return_value=SimpleNamespace(
            status="drawn", draw=draw, wallet_after=wallet_after
        )
    )
    publish_draw = AsyncMock(return_value=True)
    request_level_sync = AsyncMock()
    followup = SimpleNamespace(send=AsyncMock())
    guild = SimpleNamespace(id=123456)
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=guild,
            user=SimpleNamespace(id=2001, display_name="客"),
            followup=followup,
        ),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "_earned_xp", AsyncMock(return_value=100))
    monkeypatch.setattr(cafe_gacha_draw_ui, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "draw_card", draw_card)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_publish_draw", publish_draw)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_request_level_sync", request_level_sync)

    await _perform_draw(
        interaction,
        guild_id=123456,
        event_id="successful-draw",
        allow_paid=False,
    )

    publish_draw.assert_awaited_once_with(guild, draw)
    request_level_sync.assert_awaited_once_with("123456")
    assert followup.send.await_args.args[0] == (
        "抽選が完了しました。**カフェ台帳**で結果を確認してください。\n"
        "現在XP: **125 XP**"
    )
    assert followup.send.await_args.kwargs == {"ephemeral": True}


async def test_successful_ten_draw_uses_one_service_call_and_one_ledger_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    draws = tuple(object() for _ in range(10))
    wallet_after = SimpleNamespace(available_xp=645)
    draw_cards = AsyncMock(
        return_value=SimpleNamespace(
            status="drawn", draws=draws, wallet_after=wallet_after
        )
    )
    publish_draws = AsyncMock(return_value=True)
    request_level_sync = AsyncMock()
    followup = SimpleNamespace(send=AsyncMock())
    guild = SimpleNamespace(id=123456)
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            guild=guild,
            user=SimpleNamespace(id=2001, display_name="客"),
            followup=followup,
        ),
    )
    monkeypatch.setattr(cafe_gacha_draw_ui, "_earned_xp", AsyncMock(return_value=500))
    monkeypatch.setattr(cafe_gacha_draw_ui, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "draw_cards", draw_cards)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_publish_draws", publish_draws)
    monkeypatch.setattr(cafe_gacha_draw_ui, "_request_level_sync", request_level_sync)

    await cafe_gacha_cog._perform_ten_draw(
        interaction,
        guild_id=123456,
        event_id="batch-event",
    )

    draw_cards.assert_awaited_once_with(
        ANY,
        event_id="batch-event",
        guild_id="123456",
        user_id="2001",
        display_name="客",
        earned_xp=500,
        count=10,
        allow_paid=True,
        expected_cost_xp=None,
    )
    publish_draws.assert_awaited_once_with(guild, draws)
    request_level_sync.assert_awaited_once_with("123456")
    assert followup.send.await_args.args[0] == (
        "10枚のまとめ引きが完了しました。"
        "**カフェ台帳**で結果を確認してください。\n"
        "現在XP: **645 XP**"
    )
    assert followup.send.await_args.kwargs == {"ephemeral": True}


def test_result_embed_uses_single_public_result_with_collection_state() -> None:
    draw = CafeGachaDraw(
        id=1,
        event_id="event-1",
        guild_id="1001",
        user_id="2001",
        display_name="客",
        draw_type="free",
        cost_xp=0,
        reward_xp=15,
        reward_key="legendary-tea-leaves",
        reward_name="幻の茶葉",
        reward_description="秘蔵品。",
        rarity="SSR",
        image_filename="legendary-tea-leaves.jpg",
        exchange_xp=50,
        was_duplicate=False,
        created_at=datetime.now(UTC),
    )

    embed = _result_embed(draw, owned_count=1, collected_count=4, with_image=True)

    assert embed.title == "SSR｜幻の茶葉"
    assert embed.url == (
        "https://chill-cafe.site/cafe-collection/cards/legendary-tea-leaves/"
    )
    assert embed.description is not None
    assert "<@2001> さんが一枚引きました" in embed.description
    assert "新しいカード" not in embed.description
    assert "NEW COLLECTION" not in str(embed.to_dict())
    assert "客 さんが一枚引きました" not in embed.description
    assert embed.fields[0].name == "🎉 +15 XPの黒字！"
    xp_balance = embed.fields[0].value or ""
    assert "無料 → 15 XP獲得" in xp_balance
    assert "初入手" not in xp_balance
    assert "引くたび必ずプラス！" not in xp_balance
    assert "さらに" not in xp_balance
    assert embed.fields[1].name == "📚 コレクション"
    collection = embed.fields[1].value or ""
    assert "所持 1枚" in collection
    assert "収集 **3 → 4/264種**" in collection
    assert embed.image.url == "attachment://legendary-tea-leaves.jpg"
    assert embed.footer.text == "✨ カフェに珍しい一枚が並びました"
    assert "event-1" not in str(embed.to_dict())


def test_paid_result_explicitly_shows_positive_balance() -> None:
    draw = CafeGachaDraw(
        id=2,
        event_id="event-paid",
        guild_id="1001",
        user_id="2001",
        display_name="客",
        draw_type="paid",
        cost_xp=20,
        reward_xp=25,
        reward_key="k-pan",
        reward_name="Kブロート",
        reward_description="ジャガイモでかさ増しされた、戦時下の代用パン。",
        rarity="C",
        image_filename="k-pan.jpg",
        exchange_xp=5,
        was_duplicate=True,
        created_at=datetime.now(UTC),
    )

    embed = _result_embed(draw, owned_count=2, collected_count=1, with_image=False)

    assert embed.title == "N｜Kブロート"
    assert "カフェ棚に新しいカード" not in (embed.description or "")
    assert embed.fields[0].name == "🎉 +5 XPの黒字！"
    xp_balance = embed.fields[0].value or ""
    assert "20 XP消費 → 25 XP獲得 · 重複" in xp_balance
    assert "引くたび必ずプラス！" not in xp_balance
    assert "交換すると **さらに +5 XP！**" in xp_balance
    assert "収集 1/264種" in (embed.fields[1].value or "")
    assert embed.footer.text is None
    assert not embed.image.url


class _FakePanelMessage:
    def __init__(
        self, message_id: int, content: str, embed: discord.Embed | None = None
    ) -> None:
        self.id = message_id
        self.author = SimpleNamespace(bot=True)
        self.content = content
        self.embeds = [embed] if embed is not None else []
        self.edit_count = 0
        self.view: discord.ui.View | None = None
        self.attachments: list[Any] = []
        self.suppress: bool | None = None

    async def edit(self, **kwargs: Any) -> None:
        self.content = kwargs.get("content", self.content)
        embed = kwargs.get("embed", self.embeds[0] if self.embeds else None)
        if isinstance(embed, discord.Embed):
            self.embeds = [embed]
        elif embed is None:
            self.embeds = []
        if "view" in kwargs:
            self.view = kwargs["view"]
        if "attachments" in kwargs:
            self.attachments = kwargs["attachments"]
        if "suppress" in kwargs:
            self.suppress = kwargs["suppress"]
        self.edit_count += 1


class _FakePanelChannel:
    def __init__(self) -> None:
        self.messages: list[_FakePanelMessage] = []
        self.send_count = 0

    def history(self, *, limit: int | None) -> Any:
        async def _iterate() -> Any:
            for message in reversed(self.messages):
                yield message

        return _iterate()

    async def send(
        self, content: str | None = None, **kwargs: Any
    ) -> _FakePanelMessage:
        self.send_count += 1
        message = _FakePanelMessage(self.send_count, content or "", kwargs.get("embed"))
        message.view = kwargs.get("view")
        self.messages.append(message)
        return message

    async def fetch_message(self, message_id: int) -> _FakePanelMessage:
        return next(message for message in self.messages if message.id == message_id)


async def test_panel_without_saved_id_reuses_existing_post(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    channel = _FakePanelChannel()
    guild = cast(discord.Guild, SimpleNamespace(id=123456))
    monkeypatch.setattr(cafe_gacha_cog, "ASSET_DIR", tmp_path)

    first = await _upsert_panel(
        guild, cast(discord.TextChannel, channel), panel_message_id=None
    )
    second = await _upsert_panel(
        guild, cast(discord.TextChannel, channel), panel_message_id=None
    )

    assert first is second
    assert channel.send_count == 1
    assert channel.messages[0].edit_count == 1
    assert channel.messages[0].content is None
    assert channel.messages[0].embeds[0].title == cafe_gacha_cog.PANEL_TITLE
    assert channel.messages[0].suppress is False


async def test_panel_converts_existing_plain_message_to_embed_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    channel = _FakePanelChannel()
    old_message = _FakePanelMessage(
        42,
        f"# {cafe_gacha_cog.PANEL_TITLE}\n旧パネル",
    )
    channel.messages.append(old_message)
    guild = cast(discord.Guild, SimpleNamespace(id=123456))
    monkeypatch.setattr(cafe_gacha_cog, "ASSET_DIR", tmp_path)

    result = await _upsert_panel(
        guild, cast(discord.TextChannel, channel), panel_message_id=None
    )

    assert result.id == old_message.id
    assert channel.send_count == 0
    assert old_message.content is None
    assert old_message.embeds[0].title == cafe_gacha_cog.PANEL_TITLE
    assert old_message.suppress is False


async def test_redeploy_updates_existing_panel_without_reposting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    channel = _FakePanelChannel()
    guild = cast(discord.Guild, SimpleNamespace(id=123456))
    monkeypatch.setattr(cafe_gacha_cog, "ASSET_DIR", tmp_path)
    previous = cast(
        _FakePanelMessage,
        await _upsert_panel(
            guild, cast(discord.TextChannel, channel), panel_message_id=None
        ),
    )

    current = cast(
        _FakePanelMessage,
        await _upsert_panel(
            guild,
            cast(discord.TextChannel, channel),
            panel_message_id=str(previous.id),
        ),
    )

    assert current is previous
    assert channel.send_count == 1
    assert current.content is None
    assert current.embeds[0].title == cafe_gacha_cog.PANEL_TITLE
    assert isinstance(current.view, CafeGachaPanelView)
    assert previous.edit_count == 1
    assert previous.suppress is False


async def test_startup_repair_updates_existing_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_setup = AsyncMock()
    monkeypatch.setattr(cafe_gacha_cog, "_ensure_setup", ensure_setup)
    guild = cast(discord.Guild, SimpleNamespace(id=123456))

    await cafe_gacha_cog._repair_configured_setup(guild)

    ensure_setup.assert_awaited_once_with(
        guild,
        require_existing=True,
    )


async def test_setup_does_not_publish_leaderboard_and_preserves_saved_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        def __init__(self) -> None:
            self.session = SimpleNamespace(execute=AsyncMock(), rollback=AsyncMock())

        async def __aenter__(self) -> object:
            return self.session

        async def __aexit__(self, *_args: object) -> None:
            return None

    session_context = _SessionContext()
    config = SimpleNamespace(
        counter_channel_id="3001",
        ledger_channel_id="3002",
        panel_message_id="4001",
        leaderboard_panel_message_id="4002",
    )
    counter = cast(discord.TextChannel, SimpleNamespace(id=3001))
    ledger = cast(discord.TextChannel, SimpleNamespace(id=3002))
    main_panel = SimpleNamespace(id=4001)
    get_config = AsyncMock(return_value=config)
    find_channel = AsyncMock(side_effect=(counter, ledger))
    upsert_main = AsyncMock(return_value=main_panel)
    upsert_leaderboard = AsyncMock()
    save_config = AsyncMock()
    monkeypatch.setattr(cafe_gacha_cog, "async_session", lambda: session_context)
    monkeypatch.setattr(cafe_gacha_service, "get_guild_config", get_config)
    monkeypatch.setattr(cafe_gacha_cog, "_find_or_create_channel", find_channel)
    monkeypatch.setattr(cafe_gacha_cog, "_upsert_panel", upsert_main)
    monkeypatch.setattr(
        cafe_gacha_cog,
        "upsert_cafe_leaderboard_panel",
        upsert_leaderboard,
    )
    monkeypatch.setattr(cafe_gacha_service, "save_guild_config", save_config)
    guild = cast(discord.Guild, SimpleNamespace(id=1001))

    result = await cafe_gacha_cog._ensure_setup(guild, require_existing=True)

    assert result == (counter, ledger)
    upsert_main.assert_awaited_once_with(guild, counter, "4001")
    upsert_leaderboard.assert_not_awaited()
    save_config.assert_awaited_once_with(
        session_context.session,
        guild_id="1001",
        counter_channel_id="3001",
        ledger_channel_id="3002",
        panel_message_id="4001",
        leaderboard_panel_message_id="4002",
    )


async def test_leaderboard_panel_is_posted_only_to_manually_selected_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        def __init__(self) -> None:
            self.session = SimpleNamespace()

        async def __aenter__(self) -> object:
            return self.session

        async def __aexit__(self, *_args: object) -> None:
            return None

    session_context = _SessionContext()
    config = SimpleNamespace(
        counter_channel_id="3001",
        ledger_channel_id="3002",
        panel_message_id="4001",
        leaderboard_panel_message_id="4002",
    )
    selected_channel = cast(discord.TextChannel, SimpleNamespace(id=3999))
    panel = cast(discord.Message, SimpleNamespace(id=4999))
    get_config = AsyncMock(side_effect=(config, config))
    upsert_leaderboard = AsyncMock(return_value=panel)
    save_config = AsyncMock()
    monkeypatch.setattr(cafe_gacha_cog, "async_session", lambda: session_context)
    monkeypatch.setattr(cafe_gacha_service, "get_guild_config", get_config)
    monkeypatch.setattr(
        cafe_gacha_cog,
        "upsert_cafe_leaderboard_panel",
        upsert_leaderboard,
    )
    monkeypatch.setattr(cafe_gacha_service, "save_guild_config", save_config)
    guild = cast(discord.Guild, SimpleNamespace(id=1001))

    result = await cafe_gacha_cog._post_leaderboard_panel(guild, selected_channel)

    assert result is panel
    upsert_leaderboard.assert_awaited_once_with(
        selected_channel,
        guild_id=1001,
        panel_message_id="4002",
    )
    save_config.assert_awaited_once_with(
        session_context.session,
        guild_id="1001",
        counter_channel_id="3001",
        ledger_channel_id="3002",
        panel_message_id="4001",
        leaderboard_panel_message_id="4999",
    )


async def test_manual_leaderboard_panel_requires_existing_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return SimpleNamespace()

        async def __aexit__(self, *_args: object) -> None:
            return None

    upsert_leaderboard = AsyncMock()
    monkeypatch.setattr(cafe_gacha_cog, "async_session", _SessionContext)
    monkeypatch.setattr(
        cafe_gacha_service,
        "get_guild_config",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        cafe_gacha_cog,
        "upsert_cafe_leaderboard_panel",
        upsert_leaderboard,
    )

    result = await cafe_gacha_cog._post_leaderboard_panel(
        cast(discord.Guild, SimpleNamespace(id=1001)),
        cast(discord.TextChannel, SimpleNamespace(id=3999)),
    )

    assert result is None
    upsert_leaderboard.assert_not_awaited()


class _FakePermissionChannel:
    def __init__(self, default_role: object) -> None:
        self.default_role = default_role
        self.saved_overwrite: discord.PermissionOverwrite | None = None

    def overwrites_for(self, target: object) -> discord.PermissionOverwrite:
        assert target is self.default_role
        return discord.PermissionOverwrite(view_channel=False, send_messages=True)

    async def set_permissions(
        self, target: object, *, overwrite: discord.PermissionOverwrite
    ) -> None:
        assert target is self.default_role
        self.saved_overwrite = overwrite


async def test_existing_channel_is_made_visible_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_role = object()
    channel = _FakePermissionChannel(default_role)
    guild = SimpleNamespace(
        id=123456,
        default_role=default_role,
        me=None,
        text_channels=[channel],
    )
    monkeypatch.setattr(discord.utils, "get", lambda *_args, **_kwargs: channel)

    result = await _find_or_create_channel(
        cast(discord.Guild, guild), "☕️カフェカウンター"
    )

    assert result is cast(discord.TextChannel, channel)
    assert channel.saved_overwrite is not None
    assert channel.saved_overwrite.view_channel is True
    assert channel.saved_overwrite.read_message_history is True
    assert channel.saved_overwrite.send_messages is False
