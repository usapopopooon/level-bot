"""add message combo xp events

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column(
            "message_combo_xp",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "message_combo_xp_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("config_id", sa.String(length=64), nullable=False),
        sa.Column("streak_days", sa.Integer(), nullable=False),
        sa.Column("awarded_xp", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_message_combo_xp_event_id"),
    )
    op.create_index(
        "ix_message_combo_xp_events_guild_id",
        "message_combo_xp_events",
        ["guild_id"],
    )
    op.create_index(
        "ix_message_combo_xp_events_user_id",
        "message_combo_xp_events",
        ["user_id"],
    )
    op.create_index(
        "ix_message_combo_xp_events_channel_id",
        "message_combo_xp_events",
        ["channel_id"],
    )


def downgrade() -> None:
    op.drop_table("message_combo_xp_events")
    op.drop_column("daily_stats", "message_combo_xp")
