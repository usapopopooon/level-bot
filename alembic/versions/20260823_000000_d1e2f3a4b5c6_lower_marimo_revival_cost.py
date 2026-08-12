"""lower marimo revival cost

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_marimo_xp_spend_revival_cost",
        "marimo_xp_spends",
        type_="check",
    )
    op.create_check_constraint(
        "ck_marimo_xp_spend_positive_cost",
        "marimo_xp_spends",
        "cost_xp > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_marimo_xp_spend_positive_cost",
        "marimo_xp_spends",
        type_="check",
    )
    op.create_check_constraint(
        "ck_marimo_xp_spend_revival_cost",
        "marimo_xp_spends",
        "cost_xp = 3000",
    )
