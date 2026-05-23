"""add social edges daily

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-23 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "social_edges_daily",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("source_user_id", sa.String(), nullable=False),
        sa.Column("target_user_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("voice_seconds", sa.BigInteger(), nullable=False),
        sa.Column("voice_sessions", sa.Integer(), nullable=False),
        sa.Column("replies", sa.Integer(), nullable=False),
        sa.Column("reactions", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_user_id <> target_user_id",
            name="ck_social_edges_daily_not_self",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "source_user_id",
            "target_user_id",
            "channel_id",
            "stat_date",
            name="uq_social_edge_daily",
        ),
    )
    op.create_index(
        op.f("ix_social_edges_daily_channel_id"),
        "social_edges_daily",
        ["channel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_social_edges_daily_guild_id"),
        "social_edges_daily",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_social_edges_daily_source_user_id"),
        "social_edges_daily",
        ["source_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_social_edges_daily_stat_date"),
        "social_edges_daily",
        ["stat_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_social_edges_daily_target_user_id"),
        "social_edges_daily",
        ["target_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_social_edges_daily_target_user_id"),
        table_name="social_edges_daily",
    )
    op.drop_index(
        op.f("ix_social_edges_daily_stat_date"),
        table_name="social_edges_daily",
    )
    op.drop_index(
        op.f("ix_social_edges_daily_source_user_id"),
        table_name="social_edges_daily",
    )
    op.drop_index(
        op.f("ix_social_edges_daily_guild_id"),
        table_name="social_edges_daily",
    )
    op.drop_index(
        op.f("ix_social_edges_daily_channel_id"),
        table_name="social_edges_daily",
    )
    op.drop_table("social_edges_daily")
