"""guarantee positive XP balance for every cafe draw

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-18 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE cafe_gacha_draws
        SET reward_xp = CASE rarity
            WHEN 'C' THEN 25
            WHEN 'UC' THEN 30
            WHEN 'R' THEN 50
            WHEN 'SR' THEN 100
            WHEN 'SSR' THEN 300
        END
        """
    )
    op.create_check_constraint(
        "ck_cafe_gacha_draw_positive_balance",
        "cafe_gacha_draws",
        "reward_xp > cost_xp",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_cafe_gacha_draw_positive_balance",
        "cafe_gacha_draws",
        type_="check",
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
