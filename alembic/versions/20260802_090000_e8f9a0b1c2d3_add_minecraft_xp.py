"""add minecraft xp integration ledger

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-02 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_xp_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("minecraft_xp", sa.BigInteger(), nullable=False),
        sa.Column("awarded_xp", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("minecraft_xp >= 0", name="ck_minecraft_xp_daily_raw"),
        sa.CheckConstraint("awarded_xp >= 0", name="ck_minecraft_xp_daily_awarded"),
        sa.UniqueConstraint(
            "guild_id", "user_id", "stat_date", name="uq_minecraft_xp_daily"
        ),
    )
    op.create_index(
        "ix_minecraft_xp_daily_guild_id", "minecraft_xp_daily", ["guild_id"]
    )
    op.create_index("ix_minecraft_xp_daily_user_id", "minecraft_xp_daily", ["user_id"])
    op.create_index(
        "ix_minecraft_xp_daily_stat_date", "minecraft_xp_daily", ["stat_date"]
    )

    op.create_table(
        "minecraft_xp_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("minecraft_xp", sa.BigInteger(), nullable=False),
        sa.Column("awarded_xp", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("minecraft_xp > 0", name="ck_minecraft_xp_events_raw"),
        sa.CheckConstraint("awarded_xp >= 0", name="ck_minecraft_xp_events_awarded"),
    )
    op.create_index(
        "ix_minecraft_xp_events_guild_id", "minecraft_xp_events", ["guild_id"]
    )
    op.create_index(
        "ix_minecraft_xp_events_user_id", "minecraft_xp_events", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("minecraft_xp_events")
    op.drop_table("minecraft_xp_daily")
