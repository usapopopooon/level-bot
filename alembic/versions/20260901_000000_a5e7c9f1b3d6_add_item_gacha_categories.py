"""add Minecraft item gacha categories

Revision ID: a5e7c9f1b3d6
Revises: 9a4d6e8f2b13
Create Date: 2026-09-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a5e7c9f1b3d6"
down_revision: str | Sequence[str] | None = "9a4d6e8f2b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "minecraft_item_gacha_spends",
        sa.Column(
            "draw_category",
            sa.String(length=16),
            nullable=False,
            server_default="all",
        ),
    )
    op.create_check_constraint(
        "ck_minecraft_item_gacha_spends_category",
        "minecraft_item_gacha_spends",
        "draw_category IN ('all', 'resources', 'adventure', 'equipment')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_minecraft_item_gacha_spends_category",
        "minecraft_item_gacha_spends",
        type_="check",
    )
    op.drop_column("minecraft_item_gacha_spends", "draw_category")
