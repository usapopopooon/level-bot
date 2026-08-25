"""add coffee market access roles and append-only ledger logs

Revision ID: 9e3f7a1b5c84
Revises: 8d2e6f0a4b73
Create Date: 2026-09-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9e3f7a1b5c84"
down_revision: str | Sequence[str] | None = "8d2e6f0a4b73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_feature_access_roles_feature",
        "feature_access_roles",
        type_="check",
    )
    op.create_check_constraint(
        "ck_feature_access_roles_feature",
        "feature_access_roles",
        "feature IN ('cafe_gacha', 'color_role_shop', 'coffee_market')",
    )

    op.drop_constraint(
        "ck_coffee_market_ledger_placement_pair",
        "coffee_market_guild_configs",
        type_="check",
    )
    op.drop_column("coffee_market_guild_configs", "ledger_message_id")
    op.add_column(
        "coffee_bean_lots",
        sa.Column("ledger_message_id", sa.String(), nullable=True),
    )
    op.add_column(
        "coffee_market_sales",
        sa.Column("ledger_message_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("coffee_market_sales", "ledger_message_id")
    op.drop_column("coffee_bean_lots", "ledger_message_id")
    op.add_column(
        "coffee_market_guild_configs",
        sa.Column("ledger_message_id", sa.String(), nullable=True),
    )
    op.execute(
        "UPDATE coffee_market_guild_configs "
        "SET ledger_channel_id = NULL WHERE ledger_channel_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_coffee_market_ledger_placement_pair",
        "coffee_market_guild_configs",
        "(ledger_channel_id IS NULL) = (ledger_message_id IS NULL)",
    )

    op.drop_constraint(
        "ck_feature_access_roles_feature",
        "feature_access_roles",
        type_="check",
    )
    op.execute("DELETE FROM feature_access_roles WHERE feature = 'coffee_market'")
    op.create_check_constraint(
        "ck_feature_access_roles_feature",
        "feature_access_roles",
        "feature IN ('cafe_gacha', 'color_role_shop')",
    )
