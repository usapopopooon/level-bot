"""add separate Cafe bot Discord placements

Revision ID: 7c1d5e9f3a62
Revises: 6b0c4e8a2d51
Create Date: 2026-09-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c1d5e9f3a62"
down_revision: str | Sequence[str] | None = "6b0c4e8a2d51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cafe_collection_bot_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False, unique=True),
        sa.Column("panel_channel_id", sa.String(), nullable=True),
        sa.Column("panel_message_id", sa.String(), nullable=True),
        sa.Column("ledger_channel_id", sa.String(), nullable=True),
        sa.Column("ledger_message_id", sa.String(), nullable=True),
        sa.Column("ledger_configured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ranking_channel_id", sa.String(), nullable=True),
        sa.Column("ranking_message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_cafe_collection_bot_layouts_guild_id",
        "cafe_collection_bot_layouts",
        ["guild_id"],
        unique=True,
    )
    op.add_column(
        "cafe_gacha_draws",
        sa.Column("collection_bot_ledger_message_id", sa.String(), nullable=True),
    )
    op.add_column(
        "cafe_gacha_redemptions",
        sa.Column("collection_bot_ledger_message_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cafe_gacha_redemptions", "collection_bot_ledger_message_id")
    op.drop_column("cafe_gacha_draws", "collection_bot_ledger_message_id")
    op.drop_index(
        "ix_cafe_collection_bot_layouts_guild_id",
        table_name="cafe_collection_bot_layouts",
    )
    op.drop_table("cafe_collection_bot_layouts")
