"""add cafe card protections

Revision ID: a1c2e3f4b5d6
Revises: f0a1b2c3d4e5
Create Date: 2026-09-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c2e3f4b5d6"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cafe_gacha_card_protections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("reward_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "guild_id",
            "user_id",
            "reward_key",
            name="uq_cafe_gacha_card_protection",
        ),
    )
    op.create_index(
        "ix_cafe_gacha_card_protections_guild_id",
        "cafe_gacha_card_protections",
        ["guild_id"],
    )
    op.create_index(
        "ix_cafe_gacha_card_protections_user_id",
        "cafe_gacha_card_protections",
        ["user_id"],
    )
    op.create_index(
        "ix_cafe_gacha_card_protections_reward_key",
        "cafe_gacha_card_protections",
        ["reward_key"],
    )


def downgrade() -> None:
    op.drop_table("cafe_gacha_card_protections")
