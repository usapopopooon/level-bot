"""add Minecraft and Discord voice overlap bonus

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-08-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | Sequence[str] | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column(
            "minecraft_voice_bonus_seconds",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "minecraft_voice_presences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "guild_id", "user_id", name="uq_minecraft_voice_presence_user"
        ),
    )
    op.create_index(
        "ix_minecraft_voice_presences_guild_id",
        "minecraft_voice_presences",
        ["guild_id"],
    )
    op.create_index(
        "ix_minecraft_voice_presences_user_id",
        "minecraft_voice_presences",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("minecraft_voice_presences")
    op.drop_column("daily_stats", "minecraft_voice_bonus_seconds")
