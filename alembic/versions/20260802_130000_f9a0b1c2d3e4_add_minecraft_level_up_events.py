"""add minecraft level-up notification events

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-08-02 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_level_up_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False, unique=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("guild_name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "minecraft_delivered_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("discord_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("level > 0", name="ck_minecraft_level_up_events_level"),
    )
    op.create_index(
        "ix_minecraft_level_up_events_guild_id",
        "minecraft_level_up_events",
        ["guild_id"],
    )
    op.create_index(
        "ix_minecraft_level_up_events_user_id",
        "minecraft_level_up_events",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("minecraft_level_up_events")
