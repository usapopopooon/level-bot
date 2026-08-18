"""add minecraft market purchase ledger

Revision ID: b7c2e4f6a819
Revises: 9a4d6e8f2b13
Create Date: 2026-09-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c2e4f6a819"
down_revision: str | Sequence[str] | None = "9a4d6e8f2b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_market_purchases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("listing_id", sa.BigInteger(), nullable=False),
        sa.Column("buyer_user_id", sa.String(), nullable=False),
        sa.Column("seller_user_id", sa.String(), nullable=False),
        sa.Column("buyer_minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("seller_minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("listing_id > 0", name="ck_minecraft_market_listing_id"),
        sa.CheckConstraint("cost_xp > 0", name="ck_minecraft_market_cost"),
        sa.CheckConstraint(
            "buyer_user_id <> seller_user_id",
            name="ck_minecraft_market_distinct_users",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'cancelled')",
            name="ck_minecraft_market_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_minecraft_market_event_id"),
    )
    op.create_index(
        "uq_minecraft_market_guild_listing",
        "minecraft_market_purchases",
        ["guild_id", "listing_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'completed')"),
    )
    for column_name in (
        "guild_id",
        "buyer_user_id",
        "seller_user_id",
        "status",
    ):
        op.create_index(
            f"ix_minecraft_market_purchases_{column_name}",
            "minecraft_market_purchases",
            [column_name],
        )


def downgrade() -> None:
    op.drop_table("minecraft_market_purchases")
