"""group cafe draws into idempotent batches

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cafe_gacha_draws",
        sa.Column("batch_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "cafe_gacha_draws",
        sa.Column("batch_position", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE cafe_gacha_draws
        SET batch_id = event_id,
            batch_position = 1
        """
    )
    op.alter_column("cafe_gacha_draws", "batch_id", nullable=False)
    op.alter_column("cafe_gacha_draws", "batch_position", nullable=False)
    op.create_check_constraint(
        "ck_cafe_gacha_draw_batch_position",
        "cafe_gacha_draws",
        "batch_position BETWEEN 1 AND 10",
    )
    op.create_unique_constraint(
        "uq_cafe_gacha_draw_batch_position",
        "cafe_gacha_draws",
        ["batch_id", "batch_position"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_cafe_gacha_draw_batch_position",
        "cafe_gacha_draws",
        type_="unique",
    )
    op.drop_constraint(
        "ck_cafe_gacha_draw_batch_position",
        "cafe_gacha_draws",
        type_="check",
    )
    op.drop_column("cafe_gacha_draws", "batch_position")
    op.drop_column("cafe_gacha_draws", "batch_id")
