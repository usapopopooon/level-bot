import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import discord
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.cogs import xp_gift as xp_gift_cog
from src.cogs.xp_gift import (
    XpGiftCog,
    XpGiftConfirmView,
    XpGiftPanelView,
    _notification_embed,
    _recipient_allowed_mentions,
    build_panel_embed,
)
from src.database.models import XpGiftTransfer
from src.features.color_role_shop.service import Wallet
from src.features.xp_gift.service import GiftResult


class _FakeMessage:
    def __init__(
        self,
        *,
        message_id: int,
        content: str,
        embed: discord.Embed,
        nonce: int,
        allowed_mentions: discord.AllowedMentions,
    ) -> None:
        self.id = message_id
        self.content = content
        self.embeds = [embed]
        self.nonce = nonce
        self.allowed_mentions = allowed_mentions
        self.author = SimpleNamespace(bot=True)


class _FakeChannel:
    def __init__(self, *, fail_sends: bool = False) -> None:
        self.messages: list[_FakeMessage] = []
        self.fail_sends = fail_sends
        self.send_attempts = 0

    async def send(self, content: str, **kwargs: Any) -> _FakeMessage:
        self.send_attempts += 1
        if self.fail_sends:
            response = cast(
                Any,
                SimpleNamespace(status=500, reason="test failure", headers={}),
            )
            raise discord.HTTPException(response, "test failure")
        message = _FakeMessage(
            message_id=9000 + len(self.messages),
            content=content,
            embed=kwargs["embed"],
            nonce=kwargs["nonce"],
            allowed_mentions=kwargs["allowed_mentions"],
        )
        self.messages.append(message)
        return message

    async def history(self, **_kwargs: Any) -> Any:
        for message in reversed(self.messages):
            yield message


def _transfer() -> XpGiftTransfer:
    return XpGiftTransfer(
        id=77,
        event_id="gift-77",
        guild_id="1001",
        sender_user_id="2001",
        sender_display_name="送信者",
        recipient_user_id="2002",
        recipient_display_name="受取人",
        gift_xp=1_500,
        tax_xp=50,
        sender_cost_xp=1_550,
        transfer_day=date(2026, 8, 24),
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
    )


async def test_panel_has_clear_persistent_actions_and_rules() -> None:
    view = XpGiftPanelView(1001)
    assert all(isinstance(child, discord.ui.DynamicItem) for child in view.children)
    dynamic_children = cast(list[discord.ui.DynamicItem[Any]], view.children)
    labels = [child.item.label for child in dynamic_children]
    custom_ids = [child.item.custom_id for child in dynamic_children]

    assert view.timeout is None
    assert labels == ["XPを贈る", "自分のXP", "送受信履歴", "仕組みを見る"]
    assert custom_ids == [
        "level:xp-gift:send:1001",
        "level:xp-gift:balance:1001",
        "level:xp-gift:history:1001",
        "level:xp-gift:rules:1001",
    ]

    text = build_panel_embed().description or ""
    assert "同じ相手へ贈れるのは **1日1回**" in text
    assert "日本時間0:00更新" in text
    assert "1,000 XPまでは非課税" in text
    assert "超えた分に **贈与税10%**" in text
    assert "受取人だけに通知" in text


def test_public_notification_mentions_only_recipient() -> None:
    row = _transfer()
    allowed_mentions = _recipient_allowed_mentions(row)
    embed = _notification_embed(row)

    assert cast(Any, allowed_mentions).to_dict() == {
        "users": [2002],
        "parse": [],
    }
    assert "<@" not in (embed.description or "")
    assert "送信者さん" in (embed.description or "")
    assert "受取人さん" in (embed.description or "")
    assert "1,500 XP" in (embed.description or "")


async def test_confirmation_wires_sender_and_recipient_to_transfer_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    sender = SimpleNamespace(id=2001, display_name="送信者", bot=False)
    recipient = SimpleNamespace(id=2002, display_name="受取人", bot=False)
    members = {sender.id: sender, recipient.id: recipient}
    guild = SimpleNamespace(id=1001, get_member=members.get)
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(
            user=sender,
            guild=guild,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        ),
    )
    transfer = _transfer()
    result = GiftResult(
        status="completed",
        transfer=transfer,
        wallet_before=Wallet(total_xp=2_000, spent_xp=0),
        wallet_after=Wallet(total_xp=2_000, spent_xp=550),
        message="完了",
    )
    create_gift = AsyncMock(return_value=result)
    member_error = AsyncMock(return_value=None)
    request_sync = AsyncMock()
    publish = AsyncMock(return_value=True)
    monkeypatch.setattr(xp_gift_cog, "async_session", lambda: _SessionContext())
    monkeypatch.setattr("src.cogs.xp_gift.service.create_xp_gift", create_gift)
    monkeypatch.setattr(xp_gift_cog, "_gift_member_error", member_error)
    monkeypatch.setattr(xp_gift_cog, "_request_level_sync", request_sync)
    monkeypatch.setattr(xp_gift_cog, "_publish_transfer", publish)
    view = XpGiftConfirmView(
        guild_id=1001,
        sender_user_id=2001,
        recipient_user_id=2002,
        gift_xp=500,
    )
    button = next(
        child
        for child in view.children
        if isinstance(child, discord.ui.Button) and child.custom_id == "xp-gift-confirm"
    )

    await button.callback(interaction)

    create_gift.assert_awaited_once_with(
        ANY,
        event_id=view.event_id,
        guild_id="1001",
        sender_user_id="2001",
        sender_display_name="送信者",
        recipient_user_id="2002",
        recipient_display_name="受取人",
        gift_xp=500,
    )
    request_sync.assert_awaited_once_with("1001")
    publish.assert_awaited_once_with(guild, 77)
    cast(AsyncMock, interaction.edit_original_response).assert_awaited_once()


async def test_concurrent_publication_sends_one_recipient_only_notification(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _transfer()
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    bind = db_session.bind
    assert isinstance(bind, AsyncEngine)
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
    panel = _FakeChannel()
    ledger = _FakeChannel()
    guild = cast(discord.Guild, SimpleNamespace(id=1001))

    async def configured(_guild: discord.Guild) -> tuple[Any, Any]:
        return panel, ledger

    monkeypatch.setattr(xp_gift_cog, "async_session", factory)
    monkeypatch.setattr(xp_gift_cog, "_configured_channels", configured)

    results = await asyncio.gather(
        xp_gift_cog._publish_transfer(guild, row.id),
        xp_gift_cog._publish_transfer(guild, row.id),
    )

    assert list(results) == [True, True]
    assert len(ledger.messages) == 1
    message = ledger.messages[0]
    assert message.content == "🎁 <@2002>さん、XPが届きました！"
    assert cast(Any, message.allowed_mentions).to_dict() == {
        "users": [2002],
        "parse": [],
    }
    assert "<@2001>" not in message.content
    async with factory() as session:
        persisted = await session.get(XpGiftTransfer, row.id)
        assert persisted is not None
        assert persisted.ledger_message_id == str(message.id)
        assert persisted.notification_attempts == 1


async def test_failed_notification_stops_after_five_attempts(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _transfer()
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    bind = db_session.bind
    assert isinstance(bind, AsyncEngine)
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
    panel = _FakeChannel()
    ledger = _FakeChannel(fail_sends=True)
    guild = cast(discord.Guild, SimpleNamespace(id=1001))

    async def configured(_guild: discord.Guild) -> tuple[Any, Any]:
        return panel, ledger

    monkeypatch.setattr(xp_gift_cog, "async_session", factory)
    monkeypatch.setattr(xp_gift_cog, "_configured_channels", configured)

    results = [
        await xp_gift_cog._publish_transfer(guild, row.id) for _index in range(6)
    ]

    assert results == [False] * 6
    assert ledger.send_attempts == 5
    async with factory() as session:
        persisted = await session.get(XpGiftTransfer, row.id)
        assert persisted is not None
        assert persisted.ledger_message_id is None
        assert persisted.notification_attempts == 5


async def test_missing_ledger_channel_also_stops_after_five_attempts(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _transfer()
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    bind = db_session.bind
    assert isinstance(bind, AsyncEngine)
    factory = async_sessionmaker(bind, class_=AsyncSession, expire_on_commit=False)
    guild = cast(discord.Guild, SimpleNamespace(id=1001))
    configured = AsyncMock(return_value=None)
    monkeypatch.setattr(xp_gift_cog, "async_session", factory)
    monkeypatch.setattr(xp_gift_cog, "_configured_channels", configured)

    results = [
        await xp_gift_cog._publish_transfer(guild, row.id) for _index in range(5)
    ]
    await xp_gift_cog._retry_pending_notifications(guild)

    assert results == [False] * 5
    assert configured.await_count == 5
    async with factory() as session:
        persisted = await session.get(XpGiftTransfer, row.id)
        assert persisted is not None
        assert persisted.notification_attempts == 5


async def test_admin_retry_command_rearms_then_retries_pending_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    rearm = AsyncMock(return_value=(77,))
    list_pending = AsyncMock(
        return_value=(SimpleNamespace(id=77), SimpleNamespace(id=78))
    )
    publish = AsyncMock(side_effect=(True, False))
    response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    guild = SimpleNamespace(id=1001)
    interaction = cast(
        discord.Interaction,
        SimpleNamespace(guild=guild, response=response, followup=followup),
    )
    cog = XpGiftCog(cast(Any, SimpleNamespace()))
    monkeypatch.setattr(xp_gift_cog, "async_session", _SessionContext)
    monkeypatch.setattr("src.cogs.xp_gift.service.rearm_failed_notifications", rearm)
    monkeypatch.setattr(
        "src.cogs.xp_gift.service.list_pending_notifications", list_pending
    )
    monkeypatch.setattr(xp_gift_cog, "_publish_transfer", publish)

    callback = cast(Any, XpGiftCog.retry_notifications.callback)
    await callback(cog, interaction)

    response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    rearm.assert_awaited_once_with(ANY, guild_id="1001")
    list_pending.assert_awaited_once_with(ANY, guild_id="1001")
    assert publish.await_args_list[0].args == (guild, 77)
    assert publish.await_args_list[1].args == (guild, 78)
    sent_message = followup.send.await_args.args[0]
    assert "停止済み **1件**" in sent_message
    assert "未配信 **2件**" in sent_message
    assert "配信成功: **1件**" in sent_message
