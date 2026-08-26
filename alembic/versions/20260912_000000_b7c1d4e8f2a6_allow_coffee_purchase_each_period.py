"""allow one coffee purchase in each market period

Revision ID: b7c1d4e8f2a6
Revises: af4c8e2d7b61
Create Date: 2026-09-12 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7c1d4e8f2a6"
down_revision: str | Sequence[str] | None = "af4c8e2d7b61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE coffee_bean_lots SET purchased_slot = CASE "
        "WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Tokyo') < 6 THEN 0 "
        "WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Tokyo') < 12 THEN 1 "
        "WHEN EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Tokyo') < 18 THEN 2 "
        "ELSE 3 END "
        "WHERE purchased_slot = 0 AND sellable_on > purchased_on"
    )
    op.drop_constraint(
        "uq_coffee_bean_lot_user_day",
        "coffee_bean_lots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_coffee_bean_lot_user_period",
        "coffee_bean_lots",
        ["guild_id", "user_id", "purchased_on", "purchased_slot"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_coffee_bean_lot_user_period",
        "coffee_bean_lots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_coffee_bean_lot_user_day",
        "coffee_bean_lots",
        ["guild_id", "user_id", "purchased_on"],
    )
