"""Tests for src.main backoff/reconnect logic."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import Mock, patch

import aiohttp
import discord
import pytest

from src import main
from src.main import (
    DISCORD_RECONNECT_BASE_DELAY,
    DISCORD_RECONNECT_JITTER_RATIO,
    _backoff_sleep_seconds,
    _is_fatal_discord_error,
    _run_bot_with_backoff,
)

# DISCORD_STABLE_RUN_SECONDS は実時間で測るためテストでは短く差し替える。
_TEST_STABLE_RUN_SECONDS = 0.02


def _http_exception(status: int) -> discord.HTTPException:
    """`status` を持つ最低限の HTTPException を構築する。"""
    response = Mock()
    response.status = status
    response.reason = "test"
    return discord.HTTPException(response, {"message": "test", "code": 0})


# =============================================================================
# _is_fatal_discord_error
# =============================================================================


def test_login_failure_is_fatal() -> None:
    assert _is_fatal_discord_error(discord.LoginFailure("bad token"))


def test_privileged_intents_required_is_fatal() -> None:
    assert _is_fatal_discord_error(discord.PrivilegedIntentsRequired(shard_id=0))


@pytest.mark.parametrize("status", [401, 403])
def test_http_auth_errors_are_fatal(status: int) -> None:
    assert _is_fatal_discord_error(_http_exception(status))


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_http_5xx_and_429_are_transient(status: int) -> None:
    assert not _is_fatal_discord_error(_http_exception(status))


def test_aiohttp_client_error_is_transient() -> None:
    assert not _is_fatal_discord_error(aiohttp.ClientConnectionError())


def test_oserror_is_transient() -> None:
    assert not _is_fatal_discord_error(OSError("connection refused"))


# =============================================================================
# _backoff_sleep_seconds
# =============================================================================


def test_backoff_floor_at_base_delay() -> None:
    """負側ジッタで BASE_DELAY を下回らないこと。"""
    samples = [_backoff_sleep_seconds(DISCORD_RECONNECT_BASE_DELAY) for _ in range(500)]
    assert min(samples) >= DISCORD_RECONNECT_BASE_DELAY


def test_backoff_upper_bounded_by_jitter_ratio() -> None:
    """正側ジッタが JITTER_RATIO を超えないこと。"""
    delay = 100.0
    upper = delay * (1 + DISCORD_RECONNECT_JITTER_RATIO)
    samples = [_backoff_sleep_seconds(delay) for _ in range(500)]
    assert max(samples) <= upper + 1e-9


# =============================================================================
# _run_bot_with_backoff
# =============================================================================


class _FakeBot:
    """LevelBot のスタブ。``action`` で start() の挙動を切り替える。

    action は次のいずれか:
        - BaseException: start() で raise
        - callable(bot) -> Awaitable: start() 内で await
        - None: bot.close() が呼ばれるまで待機 (= 正常接続中)
    """

    def __init__(
        self,
        action: BaseException | Callable[["_FakeBot"], Awaitable[None]] | None,
    ) -> None:
        self._action = action
        self._closed = False
        self._close_event = asyncio.Event()
        self.start_called = False

    async def __aenter__(self) -> "_FakeBot":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def start(self, _token: str) -> None:
        self.start_called = True
        action = self._action
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            await action(self)
            return
        await self._close_event.wait()

    async def close(self) -> None:
        self._closed = True
        self._close_event.set()

    def is_closed(self) -> bool:
        return self._closed


class _FakeBotFactory:
    """``LevelBot()`` 呼び出し毎に script の next アクションで bot を生成する。"""

    def __init__(
        self,
        actions: list[BaseException | Callable[[_FakeBot], Awaitable[None]] | None],
    ) -> None:
        self._actions = list(actions)
        self.bots: list[_FakeBot] = []

    def __call__(self, *_args: Any, **_kwargs: Any) -> _FakeBot:
        action = self._actions.pop(0) if self._actions else None
        bot = _FakeBot(action)
        self.bots.append(bot)
        return bot


@pytest.fixture(autouse=True)
def no_sleep() -> Any:
    """全テスト共通でバックオフ睡眠を実質ゼロにして高速化する。"""
    with patch.object(main, "_backoff_sleep_seconds", return_value=0.0) as p:
        yield p


@pytest.fixture(autouse=True)
def _reset_global_bot() -> Any:
    """テスト間で _bot グローバルが漏れないようにする。"""
    main._bot = None
    yield
    main._bot = None


async def test_retries_after_transient_error() -> None:
    """transient な例外なら再接続を試みること。"""
    shutdown_event = asyncio.Event()

    async def _set_shutdown_then_block(bot: _FakeBot) -> None:
        shutdown_event.set()
        await bot._close_event.wait()

    factory = _FakeBotFactory(
        [
            discord.ConnectionClosed(Mock(), shard_id=None),
            _set_shutdown_then_block,
        ]
    )

    with patch.object(main, "LevelBot", factory):
        await asyncio.wait_for(_run_bot_with_backoff(shutdown_event), timeout=5)

    assert len(factory.bots) == 2
    assert factory.bots[0].start_called
    assert factory.bots[1].start_called


async def test_fatal_error_does_not_retry() -> None:
    """LoginFailure 等は即座に再送出され、再接続を試みないこと。"""
    shutdown_event = asyncio.Event()
    factory = _FakeBotFactory([discord.LoginFailure("bad token")])

    with (
        patch.object(main, "LevelBot", factory),
        pytest.raises(discord.LoginFailure),
    ):
        await asyncio.wait_for(_run_bot_with_backoff(shutdown_event), timeout=5)

    assert len(factory.bots) == 1


async def test_http_401_does_not_retry() -> None:
    """HTTP 401 (認証失敗) も再試行せず即終了すること。"""
    shutdown_event = asyncio.Event()
    factory = _FakeBotFactory([_http_exception(401)])

    with (
        patch.object(main, "LevelBot", factory),
        pytest.raises(discord.HTTPException),
    ):
        await asyncio.wait_for(_run_bot_with_backoff(shutdown_event), timeout=5)

    assert len(factory.bots) == 1


async def test_http_503_retries() -> None:
    """Discord 障害 (5xx) は再試行対象であること。"""
    shutdown_event = asyncio.Event()

    async def _set_shutdown_then_block(bot: _FakeBot) -> None:
        shutdown_event.set()
        await bot._close_event.wait()

    factory = _FakeBotFactory([_http_exception(503), _set_shutdown_then_block])

    with patch.object(main, "LevelBot", factory):
        await asyncio.wait_for(_run_bot_with_backoff(shutdown_event), timeout=5)

    assert len(factory.bots) == 2


async def test_shutdown_during_connection_closes_bot() -> None:
    """接続中にシャットダウン要求が来ると bot.close() が呼ばれてループを抜ける。"""
    shutdown_event = asyncio.Event()
    factory = _FakeBotFactory([None])  # 1 個目はずっと接続中

    with patch.object(main, "LevelBot", factory):

        async def _runner() -> None:
            await _run_bot_with_backoff(shutdown_event)

        task = asyncio.create_task(_runner())
        # bot が start() に入るまで少し待つ
        for _ in range(50):
            if factory.bots and factory.bots[0].start_called:
                break
            await asyncio.sleep(0.01)
        assert factory.bots[0].start_called
        assert not factory.bots[0].is_closed()

        shutdown_event.set()
        await asyncio.wait_for(task, timeout=5)

    assert factory.bots[0].is_closed()
    assert len(factory.bots) == 1  # 再接続していない


async def test_shutdown_event_set_after_transient_skips_retry() -> None:
    """transient エラー直後にシャットダウン要求済みなら再接続しない。"""
    shutdown_event = asyncio.Event()

    async def _raise_after_setting_shutdown(_bot: _FakeBot) -> None:
        shutdown_event.set()
        raise aiohttp.ClientConnectionError()

    factory = _FakeBotFactory([_raise_after_setting_shutdown])

    with patch.object(main, "LevelBot", factory):
        await asyncio.wait_for(_run_bot_with_backoff(shutdown_event), timeout=5)

    assert len(factory.bots) == 1


async def test_unexpected_error_propagates() -> None:
    """transient/fatal 分類外の例外は上に投げてプロセスを落とす。"""
    shutdown_event = asyncio.Event()
    factory = _FakeBotFactory([RuntimeError("unexpected")])

    with (
        patch.object(main, "LevelBot", factory),
        pytest.raises(RuntimeError, match="unexpected"),
    ):
        await asyncio.wait_for(_run_bot_with_backoff(shutdown_event), timeout=5)

    assert len(factory.bots) == 1


async def test_backoff_resets_after_stable_run(no_sleep: Any) -> None:
    """STABLE_RUN_SECONDS 以上接続できた後の障害ではバックオフが BASE に戻る。"""
    shutdown_event = asyncio.Event()
    captured_delays: list[float] = []

    def _record(d: float) -> float:
        captured_delays.append(d)
        return 0.0

    no_sleep.side_effect = _record

    async def _stable_then_fail(_bot: _FakeBot) -> None:
        # 安定動作後の障害をシミュレート: STABLE_RUN_SECONDS を超えてから raise
        await asyncio.sleep(_TEST_STABLE_RUN_SECONDS + 0.02)
        raise aiohttp.ClientConnectionError()

    async def _shutdown_then_block(bot: _FakeBot) -> None:
        shutdown_event.set()
        await bot._close_event.wait()

    factory = _FakeBotFactory(
        [
            aiohttp.ClientConnectionError(),  # iter 1: 即 fail (短命)
            _stable_then_fail,  # iter 2: 安定接続 → fail
            _shutdown_then_block,  # iter 3: シャットダウンで終了
        ]
    )

    with (
        patch.object(main, "LevelBot", factory),
        patch.object(main, "DISCORD_STABLE_RUN_SECONDS", _TEST_STABLE_RUN_SECONDS),
    ):
        await asyncio.wait_for(_run_bot_with_backoff(shutdown_event), timeout=5)

    # iter 1 の sleep は BASE。iter 2 は安定動作後なので BASE にリセットされる。
    # リセットが効いていなければ iter 2 は BASE*2 になっていたはず。
    assert captured_delays == [
        DISCORD_RECONNECT_BASE_DELAY,
        DISCORD_RECONNECT_BASE_DELAY,
    ]
    assert len(factory.bots) == 3
