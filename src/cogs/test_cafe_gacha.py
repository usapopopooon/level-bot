from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest

from src.cogs import cafe_gacha as cafe_gacha_cog
from src.cogs.cafe_gacha import (
    CafeGachaCog,
    CafeGachaPanelView,
    DynamicCafeDrawButton,
    _exchange_guidance,
    _find_or_create_channel,
    _perform_draw,
    _result_embed,
    _upsert_panel,
    build_panel_embed,
)
from src.database.models import CafeGachaDraw
from src.features.cafe_gacha import service as cafe_gacha_service
from src.features.cafe_gacha.catalog import CARDS_BY_KEY
from src.features.feature_access import service as feature_access_service
from src.features.feature_access.service import CAFE_GACHA


async def test_panel_routes_every_button_to_same_guild() -> None:
    view = CafeGachaPanelView(123456)
    custom_ids: list[str | None] = []
    for child in view.children:
        assert isinstance(child, discord.ui.DynamicItem)
        custom_ids.append(child.item.custom_id)

    assert custom_ids == [
        "level:cafe:draw:123456",
        "level:cafe:collection:123456",
        "level:cafe:catalog:123456",
        "level:cafe:balance:123456",
    ]
    draw_button = view.children[0]
    assert isinstance(draw_button, discord.ui.DynamicItem)
    assert draw_button.item.label == "一枚引く"
    collection_button = view.children[1]
    assert isinstance(collection_button, discord.ui.DynamicItem)
    assert collection_button.item.label == "コレクション・XP交換"


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
    monkeypatch.setattr(cafe_gacha_cog, "ensure_feature_access", access)
    monkeypatch.setattr(cafe_gacha_cog, "_perform_draw", perform_draw)

    await DynamicCafeDrawButton(1001).callback(interaction)

    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=CAFE_GACHA,
    )
    response.defer.assert_not_awaited()
    perform_draw.assert_not_awaited()


async def test_draw_button_silently_performs_paid_draw_in_the_same_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = AsyncMock(return_value=True)
    perform_draw = AsyncMock()
    response = SimpleNamespace(defer=AsyncMock())
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            id=9001,
            response=response,
            user=SimpleNamespace(id=3001),
        ),
    )
    monkeypatch.setattr(cafe_gacha_cog, "ensure_feature_access", access)
    monkeypatch.setattr(cafe_gacha_cog, "_perform_draw", perform_draw)

    await DynamicCafeDrawButton(1001).callback(interaction)

    access.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        feature=CAFE_GACHA,
    )
    response.defer.assert_awaited_once_with()
    perform_draw.assert_awaited_once_with(
        interaction,
        guild_id=1001,
        event_id="9001",
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
    assert "この下のメニュー" in with_duplicates


def test_panel_concisely_highlights_guaranteed_profit_and_exchange() -> None:
    embed = build_panel_embed()
    content = embed.description or ""

    assert embed.title == cafe_gacha_cog.PANEL_TITLE
    assert content == (
        "カードを集めながら、**引くたびXPが必ず増える**コレクションです。\n"
        "重複カードは、さらに獲得時と同額のXPへ交換できます。\n\n"
        "**🎟️ 1日1回無料** / 2回目以降 20 XP / 1時間10回まで\n"
        "**必ず黒字：25〜300 XP獲得（有料でも +5 XP以上）**\n\n"
        "**✨ レアリティ別XP（獲得・重複交換 共通）**\n"
        "N 25 / HN 30 / R 50 / SR 100 / SSR 300 XP\n\n"
        "最初の1枚はコレクションに残り、2枚目以降を好きな枚数だけ"
        "交換できます。\n"
        "結果はカフェ台帳に公開されます。"
    )
    assert "総合レベルが下がる" not in content
    assert embed.image.url == "attachment://panel-cabinet.jpg"
    assert embed.footer.text == "1日1回の無料分は毎日 0:00（日本時間）に更新"


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
    monkeypatch.setattr(cafe_gacha_cog, "_earned_xp", AsyncMock(return_value=100))
    monkeypatch.setattr(cafe_gacha_cog, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "draw_card", draw_card)

    await _perform_draw(
        interaction,
        guild_id=123456,
        event_id="hourly-limit",
    )

    draw_card.assert_awaited_once()
    assert draw_card.await_args is not None
    assert draw_card.await_args.kwargs["allow_paid"] is True
    message = followup.send.await_args.args[0]
    assert "1時間" in message
    assert "10回" in message
    assert "毎時00分" in message


async def test_successful_draw_only_publishes_to_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    draw = object()
    draw_card = AsyncMock(return_value=SimpleNamespace(status="drawn", draw=draw))
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
    monkeypatch.setattr(cafe_gacha_cog, "_earned_xp", AsyncMock(return_value=100))
    monkeypatch.setattr(cafe_gacha_cog, "async_session", _SessionContext)
    monkeypatch.setattr(cafe_gacha_service, "draw_card", draw_card)
    monkeypatch.setattr(cafe_gacha_cog, "_publish_draw", publish_draw)
    monkeypatch.setattr(cafe_gacha_cog, "_request_level_sync", request_level_sync)

    await _perform_draw(
        interaction,
        guild_id=123456,
        event_id="successful-draw",
    )

    publish_draw.assert_awaited_once_with(guild, draw)
    request_level_sync.assert_awaited_once_with("123456")
    followup.send.assert_not_awaited()


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
    assert embed.description is not None
    assert "<@2001> さんが一枚引きました" in embed.description
    assert "客 さんが一枚引きました" not in embed.description
    assert embed.fields[0].name == "🎉 +15 XPの黒字！"
    xp_balance = embed.fields[0].value or ""
    assert "無料 → 15 XP獲得 · NEW!" in xp_balance
    assert "引くたび必ずプラス！" in xp_balance
    assert "さらに" not in xp_balance
    assert embed.fields[1].name == "📚 コレクション"
    collection = embed.fields[1].value or ""
    assert "所持 1枚" in collection
    assert "収集 4/15種" in collection
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
        exchange_xp=25,
        was_duplicate=True,
        created_at=datetime.now(UTC),
    )

    embed = _result_embed(draw, owned_count=2, collected_count=1, with_image=False)

    assert embed.fields[0].name == "🎉 +5 XPの黒字！"
    xp_balance = embed.fields[0].value or ""
    assert "20 XP消費 → 25 XP獲得 · 重複" in xp_balance
    assert "引くたび必ずプラス！" in xp_balance
    assert "交換すると **さらに +25 XP！**" in xp_balance
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
