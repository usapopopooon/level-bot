"""add guaranteed XP rewards to cafe gacha draws

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cafe_gacha_draws",
        sa.Column("reward_xp", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE cafe_gacha_draws
        SET reward_xp = CASE rarity
            WHEN 'C' THEN 3
            WHEN 'UC' THEN 6
            WHEN 'R' THEN 15
            WHEN 'SR' THEN 40
            WHEN 'SSR' THEN 100
        END
        """
    )
    op.alter_column("cafe_gacha_draws", "reward_xp", nullable=False)
    op.create_check_constraint(
        "ck_cafe_gacha_draw_reward",
        "cafe_gacha_draws",
        "reward_xp >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_cafe_gacha_draw_reward",
        "cafe_gacha_draws",
        type_="check",
    )
    op.drop_column("cafe_gacha_draws", "reward_xp")
