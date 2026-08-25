"""Tests for ``run_migrations()``.

実 Postgres コンテナに対して alembic upgrade head を流し、テーブルが
できることと、二度呼び出しても安全 (no-op) であることを確認する。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.database.models import Base
from src.migrations import run_migrations


@pytest_asyncio.fixture
async def empty_pg_url(postgres_url: str) -> AsyncIterator[str]:
    """全スキーマを drop した「真っさら」な PG URL を返す。

    db_session fixture は drop+create で常にスキーマを用意するが、
    こちらは ``alembic_version`` も含めて完全に消す。
    """
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    yield postgres_url


def _set_database_url(url: str) -> str | None:
    """env.py が読む DATABASE_URL を一時的に差し替える。元の値を返す。"""
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    return old


def _restore_database_url(old: str | None) -> None:
    if old is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old


async def _list_tables(url: str) -> set[str]:
    """``public`` スキーマの table 名を取得する。"""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {row[0] for row in result.fetchall()}
    finally:
        await engine.dispose()


async def _list_xp_weight_change_seed_dates(url: str) -> list[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT effective_from::text
                    FROM level_xp_weight_change_logs
                    WHERE operation = 'seed'
                    ORDER BY effective_from
                    """
                )
            )
            return [row[0] for row in result.fetchall()]
    finally:
        await engine.dispose()


async def _list_xp_weight_version_seed_rows(url: str) -> list[tuple[str, int, str]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT effective_from::text, revision, status
                    FROM level_xp_weight_versions
                    ORDER BY effective_from
                    """
                )
            )
            return [(row[0], row[1], row[2]) for row in result.fetchall()]
    finally:
        await engine.dispose()


async def _list_columns(url: str, table_name: str) -> set[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
            return {row[0] for row in result.fetchall()}
    finally:
        await engine.dispose()


async def _column_character_limit(
    url: str, *, table_name: str, column_name: str
) -> int:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                      AND column_name = :column_name
                    """
                ),
                {"table_name": table_name, "column_name": column_name},
            )
            return int(result.scalar_one())
    finally:
        await engine.dispose()


async def _constraint_definition(
    url: str, *, table_name: str, constraint_name: str
) -> str:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT pg_get_constraintdef(constraint_row.oid)
                    FROM pg_constraint AS constraint_row
                    JOIN pg_class AS relation
                      ON relation.oid = constraint_row.conrelid
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = :table_name
                      AND constraint_row.conname = :constraint_name
                    """
                ),
                {
                    "table_name": table_name,
                    "constraint_name": constraint_name,
                },
            )
            return str(result.scalar_one())
    finally:
        await engine.dispose()


async def _insert_mixed_item_gacha_spends(url: str) -> int:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO minecraft_item_gacha_spends (
                        event_id, guild_id, user_id, minecraft_account_id,
                        draw_day, cost_xp, status, requested_at
                    ) VALUES
                        ('00000000-0000-4000-8000-000000000301', '1001', '3001',
                         'mc-bot:7', DATE '2026-08-15', 100, 'pending', NOW()),
                        ('00000000-0000-4000-8000-000000000302', '1001', '3001',
                         'mc-bot:7', DATE '2026-08-15', 1000, 'pending', NOW())
                    """
                )
            )
            result = await conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM minecraft_item_gacha_spends
                    WHERE guild_id = '1001' AND user_id = '3001'
                      AND draw_day = DATE '2026-08-15'
                      AND draw_category = 'all'
                    """
                )
            )
            return int(result.scalar_one())
    finally:
        await engine.dispose()


async def test_run_migrations_creates_all_tables(empty_pg_url: str) -> None:
    """空 DB に対して呼ぶと、定義済み全テーブル + alembic_version が作られる。"""
    old = _set_database_url(empty_pg_url)
    try:
        run_migrations()
    finally:
        _restore_database_url(old)

    tables = await _list_tables(empty_pg_url)
    assert "alembic_version" in tables
    # 主要テーブルがすべて存在することを確認 (全列挙すると壊れやすいので主要のみ)
    assert "guilds" in tables
    assert "guild_settings" in tables
    assert "daily_stats" in tables
    assert "voice_sessions" in tables
    assert "user_meta" in tables
    assert "channel_meta" in tables
    assert "excluded_channels" in tables
    assert "guild_chill_places" in tables
    assert "user_chill_places" in tables
    assert "role_meta" in tables
    assert "level_role_awards" in tables
    assert "level_xp_weight_logs" in tables
    assert "level_xp_weight_change_logs" in tables
    assert "level_xp_weight_versions" in tables
    assert "social_edges_daily" in tables
    assert "minecraft_voice_presences" in tables
    assert "minecraft_fishing_combo_events" in tables
    assert "minecraft_woodcutting_combo_events" in tables
    assert "voice_party_states" in tables
    assert "voice_zen_states" in tables
    assert "voice_zen_reward_events" in tables
    assert "message_combo_xp_events" in tables
    assert "marimo_xp_events" in tables
    assert "marimo_xp_spends" in tables
    assert "marimo_item_spends" in tables
    assert "minecraft_item_gacha_spends" in tables
    assert "minecraft_market_purchases" in tables
    assert "minecraft_resource_exchanges" in tables
    assert "minecraft_resource_shop_catalogs" in tables
    assert "minecraft_resource_shop_packs" in tables
    assert "coffee_market_guild_configs" in tables
    assert "coffee_market_xp_transactions" in tables
    assert "coffee_market_quotes" in tables
    assert "coffee_bean_lots" in tables
    assert "coffee_market_sales" in tables
    feature_access_constraint = await _constraint_definition(
        empty_pg_url,
        table_name="feature_access_roles",
        constraint_name="ck_feature_access_roles_feature",
    )
    assert "cafe_gacha" in feature_access_constraint
    assert "color_role_shop" in feature_access_constraint
    assert "coffee_market" in feature_access_constraint
    coffee_market_config_columns = await _list_columns(
        empty_pg_url, "coffee_market_guild_configs"
    )
    assert {
        "panel_channel_id",
        "panel_message_id",
        "ledger_channel_id",
        "ranking_channel_id",
        "ranking_message_id",
    } <= coffee_market_config_columns
    assert "ledger_message_id" not in coffee_market_config_columns
    assert "ledger_message_id" in await _list_columns(empty_pg_url, "coffee_bean_lots")
    assert "ledger_message_id" in await _list_columns(
        empty_pg_url, "coffee_market_sales"
    )
    assert "cafe_gacha_guild_configs" in tables
    assert "cafe_gacha_card_protections" in tables
    assert "cafe_gacha_user_states" in tables
    assert "cafe_gacha_draws" in tables
    assert "cafe_gacha_redemptions" in tables
    assert "cafe_gacha_redemption_items" in tables
    assert "cafe_gacha_medal_redemptions" in tables
    assert "cafe_gacha_medal_redemption_items" in tables
    assert "cafe_gacha_cosmetic_unlocks" in tables
    assert "xp_gift_guild_configs" in tables
    assert "xp_gift_transfers" in tables
    cafe_draw_columns = await _list_columns(empty_pg_url, "cafe_gacha_draws")
    assert {"reward_xp", "batch_id", "batch_position"} <= cafe_draw_columns
    for table_name in (
        "cafe_gacha_draws",
        "cafe_gacha_redemption_items",
        "cafe_gacha_medal_redemption_items",
    ):
        assert (
            await _column_character_limit(
                empty_pg_url,
                table_name=table_name,
                column_name="rarity",
            )
            == 8
        )
    cafe_rarity_constraint = await _constraint_definition(
        empty_pg_url,
        table_name="cafe_gacha_draws",
        constraint_name="ck_cafe_gacha_draw_rarity",
    )
    assert "UR" in cafe_rarity_constraint
    assert "MYTHIC" in cafe_rarity_constraint
    cafe_config_columns = await _list_columns(empty_pg_url, "cafe_gacha_guild_configs")
    assert "leaderboard_panel_message_id" in cafe_config_columns
    cafe_state_columns = await _list_columns(empty_pg_url, "cafe_gacha_user_states")
    assert {"draw_count_hour_started_at", "hourly_draw_count"} <= cafe_state_columns
    xp_gift_columns = await _list_columns(empty_pg_url, "xp_gift_transfers")
    assert {
        "sender_user_id",
        "recipient_user_id",
        "gift_message",
        "gift_xp",
        "tax_xp",
        "sender_cost_xp",
        "transfer_day",
        "ledger_message_id",
        "notification_attempts",
    } <= xp_gift_columns
    xp_gift_amount_constraint = await _constraint_definition(
        empty_pg_url,
        table_name="xp_gift_transfers",
        constraint_name="ck_xp_gift_amount",
    )
    assert "5000" in xp_gift_amount_constraint
    assert "3000" not in xp_gift_amount_constraint
    resource_exchange_columns = await _list_columns(
        empty_pg_url, "minecraft_resource_exchanges"
    )
    assert "item_name" in resource_exchange_columns
    catalog_pack_columns = await _list_columns(
        empty_pg_url, "minecraft_resource_shop_packs"
    )
    assert {
        "guild_id",
        "item_id",
        "item_name",
        "item_count",
        "cost_xp",
        "sort_order",
    } <= catalog_pack_columns
    buyback_item_constraint = await _constraint_definition(
        empty_pg_url,
        table_name="minecraft_material_buybacks",
        constraint_name="ck_minecraft_buyback_item",
    )
    assert "minecraft:emerald" in buyback_item_constraint
    assert await _list_xp_weight_change_seed_dates(empty_pg_url) == [
        "1970-01-01",
        "2026-05-17",
        "2026-05-20",
    ]
    assert await _list_xp_weight_version_seed_rows(empty_pg_url) == [
        ("1970-01-01", 1, "active"),
        ("2026-05-17", 1, "active"),
        ("2026-05-20", 1, "active"),
    ]
    columns = await _list_columns(empty_pg_url, "level_xp_weight_change_logs")
    assert "target_effective_from" in columns
    version_columns = await _list_columns(empty_pg_url, "level_xp_weight_versions")
    assert {"revision", "status", "change_log_id", "supersedes_id"} <= version_columns
    guild_settings_columns = await _list_columns(empty_pg_url, "guild_settings")
    assert {
        "daily_heatmap_channel_id",
        "daily_heatmap_days",
        "daily_heatmap_post_time",
        "daily_heatmap_timezone",
        "daily_heatmap_last_posted_on",
    } <= guild_settings_columns
    social_edge_columns = await _list_columns(empty_pg_url, "social_edges_daily")
    assert {
        "source_user_id",
        "target_user_id",
        "voice_seconds",
        "voice_sessions",
        "replies",
        "reactions",
    } <= social_edge_columns
    daily_stat_columns = await _list_columns(empty_pg_url, "daily_stats")
    assert "minecraft_voice_bonus_seconds" in daily_stat_columns
    assert "voice_party_seconds" in daily_stat_columns
    assert "voice_cafe_talk_seconds" in daily_stat_columns
    assert "tea_festival_seconds" in daily_stat_columns
    assert "tea_carnival_seconds" in daily_stat_columns
    assert "message_combo_xp" in daily_stat_columns
    assert "voice_zen_xp" in daily_stat_columns
    voice_presence_columns = await _list_columns(
        empty_pg_url, "minecraft_voice_presences"
    )
    assert "bonus_cursor_at" in voice_presence_columns
    voice_party_state_columns = await _list_columns(empty_pg_url, "voice_party_states")
    assert "tier" in voice_party_state_columns
    assert "announced_tier" in voice_party_state_columns
    assert "bonus_started_at" in voice_party_state_columns
    assert "cafe_talk_pending_seconds_by_date" in voice_party_state_columns
    guild_chill_columns = await _list_columns(empty_pg_url, "guild_chill_places")
    assert {"guild_id", "required_level", "name", "emoji"} <= guild_chill_columns
    user_chill_columns = await _list_columns(empty_pg_url, "user_chill_places")
    assert {"guild_id", "user_id", "required_level"} <= user_chill_columns
    role_meta_columns = await _list_columns(empty_pg_url, "role_meta")
    assert "color" in role_meta_columns
    item_gacha_columns = await _list_columns(
        empty_pg_url, "minecraft_item_gacha_spends"
    )
    assert "draw_category" in item_gacha_columns
    item_gacha_category_constraint = await _constraint_definition(
        empty_pg_url,
        table_name="minecraft_item_gacha_spends",
        constraint_name="ck_minecraft_item_gacha_spends_category",
    )
    assert "resources" in item_gacha_category_constraint
    assert "adventure" in item_gacha_category_constraint
    assert "equipment" in item_gacha_category_constraint
    assert await _insert_mixed_item_gacha_spends(empty_pg_url) == 2


async def test_run_migrations_is_idempotent(empty_pg_url: str) -> None:
    """二度呼んでも例外を出さない (二度目は no-op)。"""
    old = _set_database_url(empty_pg_url)
    try:
        run_migrations()
        run_migrations()
    finally:
        _restore_database_url(old)

    tables = await _list_tables(empty_pg_url)
    assert "alembic_version" in tables
