"""add Minecraft fishing combo audit events

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-08-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "a6b7c8d9e0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_fishing_combo_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("catch_count", sa.BigInteger(), nullable=False),
        sa.Column("combo_count", sa.Integer(), nullable=False),
        sa.Column("reward_xp", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "catch_count > 0", name="ck_minecraft_fishing_combo_events_catch"
        ),
        sa.CheckConstraint(
            "combo_count >= 1", name="ck_minecraft_fishing_combo_events_combo"
        ),
        sa.CheckConstraint(
            "reward_xp > 0", name="ck_minecraft_fishing_combo_events_reward"
        ),
    )
    op.create_index(
        "ix_minecraft_fishing_combo_events_guild_id",
        "minecraft_fishing_combo_events",
        ["guild_id"],
    )
    op.create_index(
        "ix_minecraft_fishing_combo_events_user_id",
        "minecraft_fishing_combo_events",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("minecraft_fishing_combo_events")
