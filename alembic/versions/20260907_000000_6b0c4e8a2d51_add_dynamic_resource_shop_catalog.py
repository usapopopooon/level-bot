"""add dynamic Minecraft resource shop catalog

Revision ID: 6b0c4e8a2d51
Revises: 5a9b3d7f1c42
Create Date: 2026-09-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6b0c4e8a2d51"
down_revision: str | Sequence[str] | None = "5a9b3d7f1c42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "minecraft_resource_shop_catalogs",
        sa.Column("guild_id", sa.String(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 0", name="ck_minecraft_resource_shop_catalog_revision"
        ),
    )
    op.create_table(
        "minecraft_resource_shop_packs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "guild_id",
            sa.String(),
            sa.ForeignKey(
                "minecraft_resource_shop_catalogs.guild_id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("item_name", sa.String(length=64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "item_id ~ '^minecraft:[a-z0-9_]+$'",
            name="ck_minecraft_resource_shop_pack_item",
        ),
        sa.CheckConstraint(
            "item_count BETWEEN 1 AND 64",
            name="ck_minecraft_resource_shop_pack_count",
        ),
        sa.CheckConstraint(
            "cost_xp BETWEEN 1 AND 10000000",
            name="ck_minecraft_resource_shop_pack_cost",
        ),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_minecraft_resource_shop_pack_sort_order"
        ),
        sa.UniqueConstraint(
            "guild_id",
            "item_id",
            "item_count",
            name="uq_minecraft_resource_shop_pack_identity",
        ),
    )
    op.create_index(
        "ix_minecraft_resource_shop_packs_guild_id",
        "minecraft_resource_shop_packs",
        ["guild_id"],
    )

    op.add_column(
        "minecraft_resource_exchanges",
        sa.Column("item_name", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE minecraft_resource_exchanges
        SET item_name = CASE item_id
            WHEN 'minecraft:diamond' THEN 'ダイヤモンド'
            WHEN 'minecraft:emerald' THEN 'エメラルド'
            WHEN 'minecraft:gunpowder' THEN '火薬'
            ELSE item_id
        END
        """
    )
    op.alter_column(
        "minecraft_resource_exchanges",
        "item_name",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.drop_constraint(
        "ck_minecraft_resource_exchanges_item",
        "minecraft_resource_exchanges",
        type_="check",
    )
    op.drop_constraint(
        "ck_minecraft_resource_exchanges_count",
        "minecraft_resource_exchanges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_resource_exchanges_count",
        "minecraft_resource_exchanges",
        "item_count BETWEEN 1 AND 64",
    )
    op.alter_column(
        "minecraft_resource_exchanges",
        "item_id",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.drop_constraint(
        "ck_minecraft_buyback_item",
        "minecraft_material_buybacks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_buyback_item",
        "minecraft_material_buybacks",
        "item_id IN ('minecraft:emerald', 'minecraft:dirt', 'minecraft:sand', "
        "'minecraft:sandstone', 'minecraft:deepslate', "
        "'minecraft:cobbled_deepslate', 'minecraft:tuff')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_minecraft_buyback_item",
        "minecraft_material_buybacks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_buyback_item",
        "minecraft_material_buybacks",
        "item_id IN ('minecraft:dirt', 'minecraft:sand', 'minecraft:sandstone', "
        "'minecraft:deepslate', 'minecraft:cobbled_deepslate', 'minecraft:tuff')",
    )
    op.alter_column(
        "minecraft_resource_exchanges",
        "item_id",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.drop_constraint(
        "ck_minecraft_resource_exchanges_count",
        "minecraft_resource_exchanges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_minecraft_resource_exchanges_count",
        "minecraft_resource_exchanges",
        "item_count > 0",
    )
    op.create_check_constraint(
        "ck_minecraft_resource_exchanges_item",
        "minecraft_resource_exchanges",
        "item_id IN ('minecraft:diamond', 'minecraft:emerald', 'minecraft:gunpowder')",
    )
    op.drop_column("minecraft_resource_exchanges", "item_name")
    op.drop_table("minecraft_resource_shop_packs")
    op.drop_table("minecraft_resource_shop_catalogs")
