"""add marimo revival item spends

Revision ID: f0a1b2c3d4e5
Revises: d9e4f6a8b2c5
Create Date: 2026-09-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "d9e4f6a8b2c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marimo_item_spends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("card_key", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("remaining_count", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_marimo_item_spend_event_id"),
        sa.CheckConstraint("card_key = 'moss-cola'", name="ck_marimo_item_spend_card"),
        sa.CheckConstraint("quantity = 1", name="ck_marimo_item_spend_quantity"),
        sa.CheckConstraint(
            "status IN ('consumed', 'insufficient_item')",
            name="ck_marimo_item_spend_status",
        ),
        sa.CheckConstraint(
            "remaining_count >= 0", name="ck_marimo_item_spend_remaining"
        ),
    )
    op.create_index(
        "ix_marimo_item_spends_guild_id", "marimo_item_spends", ["guild_id"]
    )
    op.create_index("ix_marimo_item_spends_user_id", "marimo_item_spends", ["user_id"])
    op.create_index(
        "ix_marimo_item_spends_channel_id", "marimo_item_spends", ["channel_id"]
    )


def downgrade() -> None:
    op.drop_table("marimo_item_spends")
