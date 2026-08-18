"""add cafe UR and mythic rarities

Revision ID: 9a4d6e8f2b13
Revises: 8f3c5d9e1b72
Create Date: 2026-08-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9a4d6e8f2b13"
down_revision: str | Sequence[str] | None = "8f3c5d9e1b72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_cafe_gacha_draw_rarity",
        "cafe_gacha_draws",
        type_="check",
    )
    for table_name in (
        "cafe_gacha_draws",
        "cafe_gacha_redemption_items",
        "cafe_gacha_medal_redemption_items",
    ):
        op.alter_column(
            table_name,
            "rarity",
            existing_type=sa.String(length=4),
            type_=sa.String(length=8),
            existing_nullable=False,
        )
    op.create_check_constraint(
        "ck_cafe_gacha_draw_rarity",
        "cafe_gacha_draws",
        "rarity IN ('C', 'UC', 'R', 'SR', 'SSR', 'UR', 'MYTHIC')",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM cafe_gacha_draws
                WHERE rarity IN ('UR', 'MYTHIC')
            ) OR EXISTS (
                SELECT 1 FROM cafe_gacha_redemption_items
                WHERE rarity IN ('UR', 'MYTHIC')
            ) OR EXISTS (
                SELECT 1 FROM cafe_gacha_medal_redemption_items
                WHERE rarity IN ('UR', 'MYTHIC')
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade cafe rarities while UR or MYTHIC rows exist';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(
        "ck_cafe_gacha_draw_rarity",
        "cafe_gacha_draws",
        type_="check",
    )
    for table_name in (
        "cafe_gacha_draws",
        "cafe_gacha_redemption_items",
        "cafe_gacha_medal_redemption_items",
    ):
        op.alter_column(
            table_name,
            "rarity",
            existing_type=sa.String(length=8),
            type_=sa.String(length=4),
            existing_nullable=False,
        )
    op.create_check_constraint(
        "ck_cafe_gacha_draw_rarity",
        "cafe_gacha_draws",
        "rarity IN ('C', 'UC', 'R', 'SR', 'SSR')",
    )
