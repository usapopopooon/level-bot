"""add daily heatmap settings

Revision ID: a4b5c6d7e8f9
Revises: f4a5b6c7d8e9
Create Date: 2026-06-30 19:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guild_settings",
        sa.Column("daily_heatmap_channel_id", sa.String(), nullable=True),
    )
    op.add_column(
        "guild_settings",
        sa.Column(
            "daily_heatmap_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
    )
    op.add_column(
        "guild_settings",
        sa.Column(
            "daily_heatmap_post_time",
            sa.String(),
            nullable=False,
            server_default="00:00",
        ),
    )
    op.add_column(
        "guild_settings",
        sa.Column(
            "daily_heatmap_timezone",
            sa.String(),
            nullable=False,
            server_default="Asia/Tokyo",
        ),
    )
    op.add_column(
        "guild_settings",
        sa.Column("daily_heatmap_last_posted_on", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guild_settings", "daily_heatmap_last_posted_on")
    op.drop_column("guild_settings", "daily_heatmap_timezone")
    op.drop_column("guild_settings", "daily_heatmap_post_time")
    op.drop_column("guild_settings", "daily_heatmap_days")
    op.drop_column("guild_settings", "daily_heatmap_channel_id")
