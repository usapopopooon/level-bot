"""add voice party bonus state and qualifying seconds

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column(
            "voice_party_seconds",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "voice_party_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("participant_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("announcement_message_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guild_id", "channel_id", name="uq_voice_party_state"),
    )
    op.create_index(
        "ix_voice_party_states_guild_id", "voice_party_states", ["guild_id"]
    )
    op.create_index(
        "ix_voice_party_states_channel_id", "voice_party_states", ["channel_id"]
    )


def downgrade() -> None:
    op.drop_table("voice_party_states")
    op.drop_column("daily_stats", "voice_party_seconds")
