"""add marimo xp events

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marimo_xp_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("awarded_xp", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_marimo_xp_event_id"),
        sa.CheckConstraint("awarded_xp > 0", name="ck_marimo_xp_positive"),
    )
    op.create_index("ix_marimo_xp_events_guild_id", "marimo_xp_events", ["guild_id"])
    op.create_index("ix_marimo_xp_events_user_id", "marimo_xp_events", ["user_id"])
    op.create_index(
        "ix_marimo_xp_events_channel_id", "marimo_xp_events", ["channel_id"]
    )


def downgrade() -> None:
    op.drop_table("marimo_xp_events")
