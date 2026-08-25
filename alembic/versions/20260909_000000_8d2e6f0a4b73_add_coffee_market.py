"""add daily coffee bean market

Revision ID: 8d2e6f0a4b73
Revises: 7c1d5e9f3a62
Create Date: 2026-09-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d2e6f0a4b73"
down_revision: str | Sequence[str] | None = "7c1d5e9f3a62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coffee_market_guild_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("panel_channel_id", sa.String(), nullable=True),
        sa.Column("panel_message_id", sa.String(), nullable=True),
        sa.Column("ledger_channel_id", sa.String(), nullable=True),
        sa.Column("ledger_message_id", sa.String(), nullable=True),
        sa.Column("ranking_channel_id", sa.String(), nullable=True),
        sa.Column("ranking_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(panel_channel_id IS NULL) = (panel_message_id IS NULL)",
            name="ck_coffee_market_panel_placement_pair",
        ),
        sa.CheckConstraint(
            "(ledger_channel_id IS NULL) = (ledger_message_id IS NULL)",
            name="ck_coffee_market_ledger_placement_pair",
        ),
        sa.CheckConstraint(
            "(ranking_channel_id IS NULL) = (ranking_message_id IS NULL)",
            name="ck_coffee_market_ranking_placement_pair",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id"),
    )
    op.create_index(
        op.f("ix_coffee_market_guild_configs_guild_id"),
        "coffee_market_guild_configs",
        ["guild_id"],
        unique=True,
    )
    op.create_table(
        "coffee_market_xp_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("amount_xp", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="ck_coffee_market_xp_transaction_direction",
        ),
        sa.CheckConstraint(
            "amount_xp > 0",
            name="ck_coffee_market_xp_transaction_amount",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            name="uq_coffee_market_xp_transaction_event",
        ),
    )
    op.create_index(
        op.f("ix_coffee_market_xp_transactions_guild_id"),
        "coffee_market_xp_transactions",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coffee_market_xp_transactions_user_id"),
        "coffee_market_xp_transactions",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "coffee_market_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("market_day", sa.Date(), nullable=False),
        sa.Column("buy_price_xp", sa.Integer(), nullable=False),
        sa.Column("sell_price_xp", sa.Integer(), nullable=False),
        sa.Column("previous_sell_price_xp", sa.Integer(), nullable=False),
        sa.Column("news", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("buy_price_xp > 0", name="ck_coffee_market_buy_price"),
        sa.CheckConstraint("sell_price_xp > 0", name="ck_coffee_market_sell_price"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "market_day",
            name="uq_coffee_market_quote_guild_day",
        ),
    )
    op.create_index(
        op.f("ix_coffee_market_quotes_guild_id"),
        "coffee_market_quotes",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coffee_market_quotes_market_day"),
        "coffee_market_quotes",
        ["market_day"],
        unique=False,
    )
    op.create_table(
        "coffee_bean_lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("purchased_on", sa.Date(), nullable=False),
        sa.Column("sellable_on", sa.Date(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("remaining_quantity", sa.Integer(), nullable=False),
        sa.Column("buy_price_xp", sa.Integer(), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_coffee_bean_lot_quantity"),
        sa.CheckConstraint(
            "remaining_quantity BETWEEN 0 AND quantity",
            name="ck_coffee_bean_lot_remaining",
        ),
        sa.CheckConstraint("buy_price_xp > 0", name="ck_coffee_bean_lot_buy_price"),
        sa.CheckConstraint(
            "cost_xp = quantity * buy_price_xp",
            name="ck_coffee_bean_lot_cost",
        ),
        sa.CheckConstraint(
            "sellable_on > purchased_on",
            name="ck_coffee_bean_lot_sellable_on",
        ),
        sa.CheckConstraint(
            "expires_on > sellable_on",
            name="ck_coffee_bean_lot_expires_on",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_coffee_bean_lot_event_id"),
        sa.UniqueConstraint(
            "guild_id",
            "user_id",
            "purchased_on",
            name="uq_coffee_bean_lot_user_day",
        ),
    )
    for column in (
        "expires_on",
        "guild_id",
        "purchased_on",
        "sellable_on",
        "user_id",
    ):
        op.create_index(
            op.f(f"ix_coffee_bean_lots_{column}"),
            "coffee_bean_lots",
            [column],
            unique=False,
        )
    op.create_table(
        "coffee_market_sales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("market_day", sa.Date(), nullable=False),
        sa.Column("sale_kind", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("sell_price_xp", sa.Integer(), nullable=False),
        sa.Column("payout_xp", sa.Integer(), nullable=False),
        sa.Column("cost_basis_xp", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sale_kind IN ('manual', 'expired')",
            name="ck_coffee_market_sale_kind",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_coffee_market_sale_quantity"),
        sa.CheckConstraint("sell_price_xp > 0", name="ck_coffee_market_sale_price"),
        sa.CheckConstraint(
            "payout_xp = quantity * sell_price_xp",
            name="ck_coffee_market_sale_payout",
        ),
        sa.CheckConstraint(
            "cost_basis_xp > 0",
            name="ck_coffee_market_sale_cost_basis",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_coffee_market_sale_event_id"),
    )
    for column in ("guild_id", "market_day", "user_id"):
        op.create_index(
            op.f(f"ix_coffee_market_sales_{column}"),
            "coffee_market_sales",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("coffee_market_sales")
    op.drop_table("coffee_bean_lots")
    op.drop_table("coffee_market_quotes")
    op.drop_table("coffee_market_xp_transactions")
    op.drop_table("coffee_market_guild_configs")
