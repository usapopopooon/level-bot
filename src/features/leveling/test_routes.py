"""HTTP-level smoke tests for the leveling route.

`AsyncClient + ASGITransport` で `get_db` を差し替えて Postgres に対して叩く。
"""

from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    DailyStat,
    ExcludedUser,
    LevelXpWeightChangeLog,
    LevelXpWeightLog,
)
from src.features.guilds.service import (
    list_guild_ids_requiring_level_role_sync,
    upsert_guild,
)
from src.features.leveling.service import _invalidate_weight_log_cache
from src.features.meta.service import upsert_user_meta
from src.utils import today_local
from src.web.app import app
from src.web.deps import get_db
from src.web.jwt_auth import create_jwt_token


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """テスト用 db_session を差し込み、有効な session JWT を事前設定した AsyncClient。

    auth middleware が ``/api/v1/*`` を保護しているため、cookie を持たない
    クライアントだとすべて 401 になる。テスト本筋はレベル機能なので、
    起動時に有効な JWT を発行して認証済みクライアントとして扱う。
    """

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("session", create_jwt_token("tester"))
        yield client
    app.dependency_overrides.clear()


async def test_levels_lifetime_aggregates_all_axes(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """各 axis に XP が乗り、total = axis 合計になる (期間減衰なし)。"""
    today = today_local()
    db_session.add(
        DailyStat(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            stat_date=today,
            message_count=50,  # 50 * 3 = 150 XP
            voice_seconds=60 * 100,  # 100 分 = 100 XP → voice L1
            reactions_received=200,  # 200 * 2 = 400 XP
            reactions_given=200,  # 同上
        )
    )
    await db_session.commit()
    await upsert_user_meta(
        db_session, user_id="2001", display_name="u", avatar_url=None, is_bot=False
    )

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels")
    assert resp.status_code == 200
    body = resp.json()
    assert body["voice"]["xp"] == 100
    assert body["text"]["xp"] == 150
    assert body["reactions_received"]["xp"] == 400
    assert body["reactions_given"]["xp"] == 400
    # axis 合計が total と完全一致 (丸めズレ無し)
    assert body["total"]["xp"] == (
        body["voice"]["xp"]
        + body["text"]["xp"]
        + body["reactions_received"]["xp"]
        + body["reactions_given"]["xp"]
    )
    # activity_rate 系のフィールドはレスポンスに存在しない
    assert "activity_rate" not in body
    assert "activity_rate_window_days" not in body


async def test_levels_returns_404_when_no_stats(api_client: AsyncClient) -> None:
    """ライフタイムに記録の無いユーザーは 404。"""
    resp = await api_client.get("/api/v1/guilds/1001/users/9999/levels")
    assert resp.status_code == 404


async def test_levels_with_days_uses_window(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """``?days=7`` で 7 日以前の行は集計対象外。"""
    today = today_local()
    db_session.add_all(
        [
            DailyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=today,
                message_count=50,  # in window → 150 XP
            ),
            DailyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=today - timedelta(days=30),
                message_count=1000,  # out of window → 無視
            ),
        ]
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"]["xp"] == 150
    assert body["text"]["level"] == 1


async def test_levels_with_days_returns_zero_for_inactive_user(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """期間内に活動の無いユーザーは 404 でなく L0 を返す (window はゼロ許容)。"""
    db_session.add(
        DailyStat(
            guild_id="1001",
            user_id="2001",
            channel_id="3001",
            stat_date=date(2020, 1, 1),  # 遥か昔
            message_count=100,
        )
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"]["level"] == 0
    assert body["total"]["xp"] == 0


async def test_levels_lifetime_and_window_use_same_rate_history(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """同じ帳簿と為替表なら lifetime/window でXP評価方針が揃う。"""
    today = today_local()
    change_day = today - timedelta(days=1)
    before_day = today - timedelta(days=2)
    await db_session.execute(
        delete(LevelXpWeightLog).where(LevelXpWeightLog.effective_from == change_day)
    )
    db_session.add(
        LevelXpWeightLog(
            effective_from=change_day,
            message_weight=10.0,
            reaction_received_weight=5.0,
            reaction_given_weight=5.0,
        )
    )
    db_session.add_all(
        [
            DailyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=before_day,
                message_count=10,  # seeded current rate: 10 * 3 = 30 XP
            ),
            DailyStat(
                guild_id="1001",
                user_id="2001",
                channel_id="3001",
                stat_date=change_day,
                message_count=10,  # changed rate: 10 * 10 = 100 XP
            ),
        ]
    )
    await db_session.commit()
    _invalidate_weight_log_cache()

    lifetime_resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels")
    window_resp = await api_client.get("/api/v1/guilds/1001/users/2001/levels?days=3")

    assert lifetime_resp.status_code == 200
    assert window_resp.status_code == 200
    assert lifetime_resp.json()["text"]["xp"] == 130
    assert window_resp.json()["text"]["xp"] == 130


async def test_levels_leaderboard_orders_by_axis(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """指定 axis のレベル降順で並ぶ (減衰無しの素 XP)。"""
    today = today_local()
    db_session.add_all(
        [
            DailyStat(
                guild_id="1001",
                user_id="100",
                channel_id="3001",
                stat_date=today,
                voice_seconds=6000,  # 100 分 = 100 XP
            ),
            DailyStat(
                guild_id="1001",
                user_id="200",
                channel_id="3001",
                stat_date=today,
                voice_seconds=3000,  # 50 分 = 50 XP
            ),
        ]
    )
    await db_session.commit()

    resp = await api_client.get("/api/v1/guilds/1001/levels/leaderboard?axis=voice")
    assert resp.status_code == 200
    body = resp.json()
    assert [e["user_id"] for e in body] == ["100", "200"]
    assert body[0]["xp"] > body[1]["xp"]
    assert "activity_rate" not in body[0]


async def test_levels_leaderboard_uses_rate_history_not_raw_counts(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    today = today_local()
    change_day = today - timedelta(days=1)
    before_day = today - timedelta(days=2)
    await db_session.execute(
        delete(LevelXpWeightLog).where(LevelXpWeightLog.effective_from == change_day)
    )
    db_session.add(
        LevelXpWeightLog(
            effective_from=change_day,
            message_weight=100.0,
            reaction_received_weight=2.0,
            reaction_given_weight=2.0,
        )
    )
    db_session.add_all(
        [
            DailyStat(
                guild_id="1001",
                user_id="100",
                channel_id="3001",
                stat_date=change_day,
                message_count=1,  # 100 XP
            ),
            DailyStat(
                guild_id="1001",
                user_id="200",
                channel_id="3001",
                stat_date=before_day,
                message_count=20,  # 60 XP
            ),
        ]
    )
    await db_session.commit()
    _invalidate_weight_log_cache()

    resp = await api_client.get("/api/v1/guilds/1001/levels/leaderboard?axis=text")

    assert resp.status_code == 200
    body = resp.json()
    assert [e["user_id"] for e in body[:2]] == ["100", "200"]
    assert body[0]["xp"] == 100
    assert body[1]["xp"] == 60


async def test_levels_leaderboard_keeps_excluded_users_excluded_after_rate_change(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    today = today_local()
    await db_session.execute(
        delete(LevelXpWeightLog).where(LevelXpWeightLog.effective_from == today)
    )
    db_session.add(
        LevelXpWeightLog(
            effective_from=today,
            message_weight=100.0,
            reaction_received_weight=2.0,
            reaction_given_weight=2.0,
        )
    )
    db_session.add_all(
        [
            DailyStat(
                guild_id="1001",
                user_id="100",
                channel_id="3001",
                stat_date=today,
                message_count=100,
            ),
            DailyStat(
                guild_id="1001",
                user_id="200",
                channel_id="3001",
                stat_date=today,
                message_count=1,
            ),
            ExcludedUser(guild_id="1001", user_id="100"),
        ]
    )
    await db_session.commit()
    _invalidate_weight_log_cache()

    resp = await api_client.get("/api/v1/guilds/1001/levels/leaderboard?axis=text")

    assert resp.status_code == 200
    assert [e["user_id"] for e in resp.json()] == ["200"]


async def test_levels_leaderboard_rejects_unknown_axis(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.get("/api/v1/guilds/1001/levels/leaderboard?axis=lol")
    assert resp.status_code == 422


async def test_get_xp_weight_logs_returns_seeded_logs(
    api_client: AsyncClient,
) -> None:
    resp = await api_client.get("/api/v1/leveling/xp-weight-logs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 2
    assert body[0]["effective_from"] == "1970-01-01"


async def test_create_xp_weight_log_and_rollback(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    create_resp = await api_client.post(
        "/api/v1/leveling/xp-weight-logs",
        json={
            "effective_from": "2026-06-01",
            "message_weight": 12.0,
            "reaction_received_weight": 6.0,
            "reaction_given_weight": 6.0,
            "actor_id": "9001",
            "reason": "seasonal rebalance",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["effective_from"] == "2026-06-01"
    assert created["message_weight"] == 12.0

    rollback_resp = await api_client.post(
        "/api/v1/leveling/xp-weight-logs/rollback",
        json={
            "effective_from": "2026-06-15",
            "actor_id": "9002",
            "reason": "undo seasonal rebalance",
        },
    )
    assert rollback_resp.status_code == 200
    rolled = rollback_resp.json()
    assert rolled["effective_from"] == "2026-06-15"
    # rollback は「ひとつ前の設定」に戻す (seed の現行値 3/2/2)
    assert rolled["message_weight"] == 3.0
    assert rolled["reaction_received_weight"] == 2.0
    assert rolled["reaction_given_weight"] == 2.0

    audit_rows = (
        (
            await db_session.execute(
                select(LevelXpWeightChangeLog).order_by(
                    LevelXpWeightChangeLog.effective_from.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(row.effective_from.isoformat(), row.operation) for row in audit_rows] == [
        ("2026-06-01", "create"),
        ("2026-06-15", "rollback"),
    ]
    created_audit, rollback_audit = audit_rows
    assert created_audit.previous_message_weight is None
    assert created_audit.new_message_weight == 12.0
    assert created_audit.actor_id == "9001"
    assert created_audit.reason == "seasonal rebalance"
    assert rollback_audit.previous_message_weight == 12.0
    assert rollback_audit.new_message_weight == 3.0
    assert rollback_audit.actor_id == "9002"
    assert rollback_audit.reason == "undo seasonal rebalance"


async def test_create_xp_weight_log_does_not_request_level_role_sync(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await upsert_guild(
        db_session,
        guild_id="1001",
        name="guild",
        icon_url=None,
        member_count=1,
    )

    resp = await api_client.post(
        "/api/v1/leveling/xp-weight-logs",
        json={
            "effective_from": "2026-06-01",
            "message_weight": 12.0,
            "reaction_received_weight": 6.0,
            "reaction_given_weight": 6.0,
        },
    )

    assert resp.status_code == 200
    assert await list_guild_ids_requiring_level_role_sync(db_session) == []


async def test_create_xp_weight_log_rejects_non_increasing_effective_from(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await api_client.post(
        "/api/v1/leveling/xp-weight-logs",
        json={
            "effective_from": "2026-05-01",
            "message_weight": 10.0,
            "reaction_received_weight": 5.0,
            "reaction_given_weight": 5.0,
        },
    )
    assert resp.status_code == 422
    audit_rows = (
        (await db_session.execute(select(LevelXpWeightChangeLog))).scalars().all()
    )
    assert audit_rows == []


async def test_create_xp_weight_log_rejects_duplicate_effective_from(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await api_client.post(
        "/api/v1/leveling/xp-weight-logs",
        json={
            "effective_from": "2026-07-01",
            "message_weight": 11.0,
            "reaction_received_weight": 6.0,
            "reaction_given_weight": 6.0,
        },
    )
    assert first.status_code == 200

    second = await api_client.post(
        "/api/v1/leveling/xp-weight-logs",
        json={
            "effective_from": "2026-07-01",
            "message_weight": 12.0,
            "reaction_received_weight": 7.0,
            "reaction_given_weight": 7.0,
        },
    )
    assert second.status_code == 422
    assert "effective_from must be greater" in second.text
    audit_rows = (
        (await db_session.execute(select(LevelXpWeightChangeLog))).scalars().all()
    )
    assert len(audit_rows) == 1


async def test_create_xp_weight_log_rejects_invalid_actor_id(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await api_client.post(
        "/api/v1/leveling/xp-weight-logs",
        json={
            "effective_from": "2026-06-01",
            "message_weight": 12.0,
            "reaction_received_weight": 6.0,
            "reaction_given_weight": 6.0,
            "actor_id": "admin",
        },
    )
    assert resp.status_code == 422
    audit_rows = (
        (await db_session.execute(select(LevelXpWeightChangeLog))).scalars().all()
    )
    assert audit_rows == []


async def test_rollback_requires_at_least_two_weight_logs(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        delete(LevelXpWeightLog).where(
            LevelXpWeightLog.effective_from != date(1970, 1, 1)
        )
    )
    await db_session.commit()

    resp = await api_client.post(
        "/api/v1/leveling/xp-weight-logs/rollback",
        json={"effective_from": "2026-08-01"},
    )
    assert resp.status_code == 422
    assert "at least 2" in resp.text
