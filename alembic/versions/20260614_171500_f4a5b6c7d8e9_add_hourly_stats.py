"""add hourly_stats table

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-14 17:15:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hourly_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("stat_hour", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "reactions_received", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("reactions_given", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("voice_seconds", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "stat_hour >= 0 AND stat_hour <= 23",
            name="ck_hourly_stats_stat_hour",
        ),
        sa.UniqueConstraint(
            "guild_id",
            "user_id",
            "channel_id",
            "stat_date",
            "stat_hour",
            name="uq_hourly_stat",
        ),
    )
    op.create_index(
        op.f("ix_hourly_stats_guild_id"),
        "hourly_stats",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hourly_stats_user_id"),
        "hourly_stats",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hourly_stats_channel_id"),
        "hourly_stats",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hourly_stats_stat_date"),
        "hourly_stats",
        ["stat_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hourly_stats_stat_hour"),
        "hourly_stats",
        ["stat_hour"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_hourly_stats_stat_hour"), table_name="hourly_stats")
    op.drop_index(op.f("ix_hourly_stats_stat_date"), table_name="hourly_stats")
    op.drop_index(op.f("ix_hourly_stats_channel_id"), table_name="hourly_stats")
    op.drop_index(op.f("ix_hourly_stats_user_id"), table_name="hourly_stats")
    op.drop_index(op.f("ix_hourly_stats_guild_id"), table_name="hourly_stats")
    op.drop_table("hourly_stats")
