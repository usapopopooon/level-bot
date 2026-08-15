"""expand Minecraft item gacha prices and daily draws

Revision ID: e7c4a9b2d6f1
Revises: 9c7e5a1d3f8b
Create Date: 2026-08-27 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7c4a9b2d6f1"
down_revision: str | Sequence[str] | None = "9c7e5a1d3f8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_minecraft_item_gacha_spends_user_day",
        "minecraft_item_gacha_spends",
        type_="unique",
    )
    op.drop_constraint(
        "ck_minecraft_item_gacha_spends_cost",
        "minecraft_item_gacha_spends",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_item_gacha_spends_cost",
        "minecraft_item_gacha_spends",
        "cost_xp IN (100, 1000)",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM minecraft_item_gacha_spends
                WHERE cost_xp <> 100
            ) OR EXISTS (
                SELECT 1
                FROM minecraft_item_gacha_spends
                GROUP BY guild_id, user_id, draw_day
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade item gacha schema without deleting spend history';
            END IF;
        END
        $$
        """
    )
    op.drop_constraint(
        "ck_minecraft_item_gacha_spends_cost",
        "minecraft_item_gacha_spends",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_item_gacha_spends_cost",
        "minecraft_item_gacha_spends",
        "cost_xp = 100",
    )
    op.create_unique_constraint(
        "uq_minecraft_item_gacha_spends_user_day",
        "minecraft_item_gacha_spends",
        ["guild_id", "user_id", "draw_day"],
    )
