"""add intraday coffee market periods

Revision ID: af4c8e2d7b61
Revises: 9e3f7a1b5c84
Create Date: 2026-09-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "af4c8e2d7b61"
down_revision: str | Sequence[str] | None = "9e3f7a1b5c84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "coffee_market_quotes",
        sa.Column(
            "market_slot",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.alter_column("coffee_market_quotes", "market_slot", server_default=None)
    op.drop_constraint(
        "uq_coffee_market_quote_guild_day",
        "coffee_market_quotes",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_coffee_market_quote_guild_period",
        "coffee_market_quotes",
        ["guild_id", "market_day", "market_slot"],
    )
    op.create_check_constraint(
        "ck_coffee_market_quote_slot",
        "coffee_market_quotes",
        "market_slot BETWEEN 0 AND 3",
    )

    for column in ("purchased_slot", "sellable_slot"):
        op.add_column(
            "coffee_bean_lots",
            sa.Column(
                column,
                sa.SmallInteger(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )
        op.alter_column("coffee_bean_lots", column, server_default=None)
    op.drop_constraint(
        "ck_coffee_bean_lot_sellable_on",
        "coffee_bean_lots",
        type_="check",
    )
    op.create_check_constraint(
        "ck_coffee_bean_lot_purchased_slot",
        "coffee_bean_lots",
        "purchased_slot BETWEEN 0 AND 3",
    )
    op.create_check_constraint(
        "ck_coffee_bean_lot_sellable_slot",
        "coffee_bean_lots",
        "sellable_slot BETWEEN 0 AND 3",
    )
    op.create_check_constraint(
        "ck_coffee_bean_lot_sellable_period",
        "coffee_bean_lots",
        "sellable_on > purchased_on OR "
        "(sellable_on = purchased_on AND sellable_slot > purchased_slot)",
    )

    op.add_column(
        "coffee_market_sales",
        sa.Column(
            "market_slot",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.alter_column("coffee_market_sales", "market_slot", server_default=None)
    op.create_check_constraint(
        "ck_coffee_market_sale_slot",
        "coffee_market_sales",
        "market_slot BETWEEN 0 AND 3",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_coffee_market_sale_slot",
        "coffee_market_sales",
        type_="check",
    )
    op.drop_column("coffee_market_sales", "market_slot")

    op.drop_constraint(
        "ck_coffee_bean_lot_sellable_period",
        "coffee_bean_lots",
        type_="check",
    )
    op.drop_constraint(
        "ck_coffee_bean_lot_sellable_slot",
        "coffee_bean_lots",
        type_="check",
    )
    op.drop_constraint(
        "ck_coffee_bean_lot_purchased_slot",
        "coffee_bean_lots",
        type_="check",
    )
    op.execute(
        "UPDATE coffee_bean_lots "
        "SET sellable_on = purchased_on + INTERVAL '1 day' "
        "WHERE sellable_on = purchased_on"
    )
    op.create_check_constraint(
        "ck_coffee_bean_lot_sellable_on",
        "coffee_bean_lots",
        "sellable_on > purchased_on",
    )
    op.drop_column("coffee_bean_lots", "sellable_slot")
    op.drop_column("coffee_bean_lots", "purchased_slot")

    op.drop_constraint(
        "ck_coffee_market_quote_slot",
        "coffee_market_quotes",
        type_="check",
    )
    op.drop_constraint(
        "uq_coffee_market_quote_guild_period",
        "coffee_market_quotes",
        type_="unique",
    )
    op.execute("DELETE FROM coffee_market_quotes WHERE market_slot != 0")
    op.drop_column("coffee_market_quotes", "market_slot")
    op.create_unique_constraint(
        "uq_coffee_market_quote_guild_day",
        "coffee_market_quotes",
        ["guild_id", "market_day"],
    )
