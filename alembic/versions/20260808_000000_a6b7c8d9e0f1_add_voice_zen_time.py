"""add voice zen time state and XP

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column("voice_zen_xp", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "voice_zen_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column(
            "accumulated_seconds", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column("checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awarded_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guild_id", "channel_id", name="uq_voice_zen_state"),
    )
    op.create_index("ix_voice_zen_states_guild_id", "voice_zen_states", ["guild_id"])
    op.create_index(
        "ix_voice_zen_states_channel_id", "voice_zen_states", ["channel_id"]
    )
    op.create_index("ix_voice_zen_states_user_id", "voice_zen_states", ["user_id"])
    op.create_table(
        "voice_zen_reward_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("awarded_xp", sa.Integer(), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("session_id", "guild_id", "channel_id", "user_id"):
        op.create_index(
            f"ix_voice_zen_reward_events_{column}",
            "voice_zen_reward_events",
            [column],
        )


def downgrade() -> None:
    op.drop_table("voice_zen_reward_events")
    op.drop_table("voice_zen_states")
    op.drop_column("daily_stats", "voice_zen_xp")
