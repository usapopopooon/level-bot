"""add marimo resurrection xp spends

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | Sequence[str] | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marimo_xp_spends",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_marimo_xp_spend_event_id"),
        sa.CheckConstraint("cost_xp = 3000", name="ck_marimo_xp_spend_revival_cost"),
        sa.CheckConstraint(
            "status IN ('charged', 'declined')",
            name="ck_marimo_xp_spend_status",
        ),
    )
    op.create_index("ix_marimo_xp_spends_guild_id", "marimo_xp_spends", ["guild_id"])
    op.create_index("ix_marimo_xp_spends_user_id", "marimo_xp_spends", ["user_id"])
    op.create_index(
        "ix_marimo_xp_spends_channel_id", "marimo_xp_spends", ["channel_id"]
    )


def downgrade() -> None:
    op.drop_table("marimo_xp_spends")
