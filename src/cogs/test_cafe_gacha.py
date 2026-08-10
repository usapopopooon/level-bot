from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import discord
import pytest

from src.cogs import cafe_gacha as cafe_gacha_cog
from src.cogs.cafe_gacha import (
    CafeGachaPanelView,
    _exchange_guidance,
    _find_or_create_channel,
    _paid_draw_confirmation,
    _perform_draw,
    _result_content,
    _upsert_panel,
    build_panel_content,
)
from src.database.models import CafeGachaDraw
from src.features.cafe_gacha import service as cafe_gacha_service
from src.features.cafe_gacha.catalog import CARDS_BY_KEY


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


def test_panel_explains_public_results_cost_and_exchange() -> None:
    content = build_panel_content()

    assert "1日1回無料" in content
    assert "1時間10回まで" in content
    assert "2回目以降" in content
    assert "20 XP" in content
    assert "獲得XP: N 25 / UC 30 / R 50 / SR 100 / SSR 300 XP" in content
    assert "最低 +5 XP" in content
    assert "20 XP消費 → 25 XP以上獲得" in content
    assert "結果はすべて公開" in content
    assert "結果はカフェ台帳" in content
    assert "重複交換: N 3 / UC 10 / R 30 / SR 100 / SSR 300 XP" in content


def test_paid_confirmation_explains_level_may_drop() -> None:
    content = _paid_draw_confirmation(1234)

    assert "20 XP" in content
    assert "最低でも差引 +5 XP" in content
    assert "1,234 XP" in content
    assert "総合レベルが下がる場合" in content
    assert "1時間10回まで" in content


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
        allow_paid=False,
    )

    message = followup.send.await_args.args[0]
    assert "1時間" in message
    assert "10回" in message
    assert "毎時00分" in message


def test_result_content_uses_single_public_result_with_collection_state() -> None:
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

    content = _result_content(draw, owned_count=1, collected_count=4)

    assert "SSR｜幻の茶葉" in content
    assert "<@2001> さんが一枚引きました" in content
    assert "客 さんが一枚引きました" not in content
    assert "無料 → 15 XP獲得 · NEW!" in content
    assert "## 今回の収支 +15 XP" in content
    assert "所持 1枚" in content
    assert "収集 4/15種" in content
    assert "event-1" not in content


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
        exchange_xp=3,
        was_duplicate=True,
        created_at=datetime.now(UTC),
    )

    content = _result_content(draw, owned_count=2, collected_count=1)

    assert "20 XP消費 → 25 XP獲得 · 重複" in content
    assert "## 今回の収支 +5 XP" in content


class _FakePanelMessage:
    def __init__(
        self, message_id: int, content: str, embed: discord.Embed | None = None
    ) -> None:
        self.id = message_id
        self.author = SimpleNamespace(bot=True)
        self.content = content
        self.embeds = [embed] if embed is not None else []
        self.edit_count = 0
        self.deleted = False
        self.view: discord.ui.View | None = None
        self.attachments: list[Any] = []

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
        self.edit_count += 1

    async def delete(self) -> None:
        self.deleted = True


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
    assert channel.messages[0].embeds == []


async def test_panel_converts_existing_embed_to_regular_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    channel = _FakePanelChannel()
    old_embed = discord.Embed(title=cafe_gacha_cog.PANEL_TITLE)
    old_message = _FakePanelMessage(42, "", old_embed)
    channel.messages.append(old_message)
    guild = cast(discord.Guild, SimpleNamespace(id=123456))
    monkeypatch.setattr(cafe_gacha_cog, "ASSET_DIR", tmp_path)

    result = await _upsert_panel(
        guild, cast(discord.TextChannel, channel), panel_message_id=None
    )

    assert result.id == old_message.id
    assert channel.send_count == 0
    assert old_message.content == build_panel_content()
    assert old_message.embeds == []


async def test_redeploy_posts_new_panel_and_deletes_previous_panel(
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
            repost=True,
        ),
    )

    assert current is not previous
    assert channel.send_count == 2
    assert current.content == build_panel_content()
    assert isinstance(current.view, CafeGachaPanelView)
    assert previous.deleted is True
    assert previous.edit_count == 0


async def test_startup_repair_requests_panel_repost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_setup = AsyncMock()
    monkeypatch.setattr(cafe_gacha_cog, "_ensure_setup", ensure_setup)
    guild = cast(discord.Guild, SimpleNamespace(id=123456))

    await cafe_gacha_cog._repair_configured_setup(guild)

    ensure_setup.assert_awaited_once_with(
        guild,
        require_existing=True,
        repost_panel=True,
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
