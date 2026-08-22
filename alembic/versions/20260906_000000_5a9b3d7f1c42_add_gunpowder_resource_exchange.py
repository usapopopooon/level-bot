"""add gunpowder resource exchange

Revision ID: 5a9b3d7f1c42
Revises: 4f8a2c6e9b31
Create Date: 2026-09-06 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5a9b3d7f1c42"
down_revision: str | Sequence[str] | None = "4f8a2c6e9b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_minecraft_resource_exchanges_item",
        "minecraft_resource_exchanges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_resource_exchanges_item",
        "minecraft_resource_exchanges",
        "item_id IN ('minecraft:diamond', 'minecraft:emerald', 'minecraft:gunpowder')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_minecraft_resource_exchanges_item",
        "minecraft_resource_exchanges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_resource_exchanges_item",
        "minecraft_resource_exchanges",
        "item_id IN ('minecraft:diamond', 'minecraft:emerald')",
    )
