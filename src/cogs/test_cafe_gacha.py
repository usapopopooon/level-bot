from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest

from src.cogs import cafe_gacha as cafe_gacha_cog
from src.cogs.cafe_gacha import (
    CafeGachaPanelView,
    _find_or_create_channel,
    _paid_draw_confirmation,
    _result_embed,
    _upsert_panel,
    build_panel_embed,
)
from src.database.models import CafeGachaDraw


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


def test_panel_explains_public_results_cost_and_exchange() -> None:
    description = build_panel_embed().description or ""

    assert "本日最初の1枚は無料" in description
    assert "20 XP" in description
    assert "結果はすべて公開" in description
    assert "SSR 50 XP" in description


def test_paid_confirmation_explains_level_may_drop() -> None:
    content = _paid_draw_confirmation(1234)

    assert "20 XP" in content
    assert "1,234 XP" in content
    assert "総合レベルが下がる場合" in content


def test_result_embed_uses_single_public_result_with_collection_state() -> None:
    draw = CafeGachaDraw(
        id=1,
        event_id="event-1",
        guild_id="1001",
        user_id="2001",
        display_name="客",
        draw_type="free",
        cost_xp=0,
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
    assert embed.author.name == "客 さんが一枚引きました"
    assert embed.fields[0].value == "本日の無料分 · NEW!"
    assert "所持 1枚" in str(embed.fields[1].value)
    assert "収集 4/15種" in str(embed.fields[1].value)
    assert embed.image.url == "attachment://legendary-tea-leaves.jpg"


class _FakePanelMessage:
    def __init__(self, message_id: int, embed: discord.Embed) -> None:
        self.id = message_id
        self.author = SimpleNamespace(bot=True)
        self.embeds = [embed]
        self.edit_count = 0

    async def edit(self, **kwargs: Any) -> None:
        embed = kwargs.get("embed")
        if isinstance(embed, discord.Embed):
            self.embeds = [embed]
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

    async def send(self, **kwargs: Any) -> _FakePanelMessage:
        self.send_count += 1
        message = _FakePanelMessage(self.send_count, kwargs["embed"])
        self.messages.append(message)
        return message


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
