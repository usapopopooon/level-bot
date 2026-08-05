"""add Minecraft XP exchange ledger

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-05 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_xp_exchanges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("minecraft_account_id", sa.String(length=128), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("reward_xp", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cost_xp > 0", name="ck_minecraft_xp_exchanges_cost"),
        sa.CheckConstraint("reward_xp > 0", name="ck_minecraft_xp_exchanges_reward"),
        sa.CheckConstraint(
            "status IN ('pending', 'delivering', 'completed', 'cancelled')",
            name="ck_minecraft_xp_exchanges_status",
        ),
        sa.UniqueConstraint("event_id", name="uq_minecraft_xp_exchanges_event_id"),
    )
    op.create_index(
        "ix_minecraft_xp_exchanges_guild_id",
        "minecraft_xp_exchanges",
        ["guild_id"],
    )
    op.create_index(
        "ix_minecraft_xp_exchanges_user_id",
        "minecraft_xp_exchanges",
        ["user_id"],
    )
    op.create_index(
        "ix_minecraft_xp_exchanges_status",
        "minecraft_xp_exchanges",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("minecraft_xp_exchanges")
