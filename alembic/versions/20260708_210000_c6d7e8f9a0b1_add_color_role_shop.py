"""add color role shop tables

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-07-08 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "color_role_shop_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=160), nullable=True),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("cost_xp >= 1", name="ck_color_role_shop_items_cost_xp"),
        sa.CheckConstraint(
            "char_length(label) BETWEEN 1 AND 80",
            name="ck_color_role_shop_items_label_length",
        ),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 160",
            name="ck_color_role_shop_items_description_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "role_id", name="uq_color_role_shop_item_role"),
    )
    op.create_index(
        op.f("ix_color_role_shop_items_guild_id"),
        "color_role_shop_items",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_color_role_shop_items_role_id"),
        "color_role_shop_items",
        ["role_id"],
        unique=False,
    )

    op.create_table(
        "color_role_exchanges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("cost_xp", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("cost_xp >= 1", name="ck_color_role_exchanges_cost_xp"),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["color_role_shop_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_color_role_exchanges_created_at"),
        "color_role_exchanges",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_color_role_exchanges_guild_id"),
        "color_role_exchanges",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_color_role_exchanges_item_id"),
        "color_role_exchanges",
        ["item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_color_role_exchanges_role_id"),
        "color_role_exchanges",
        ["role_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_color_role_exchanges_user_id"),
        "color_role_exchanges",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_color_role_exchanges_user_id"), table_name="color_role_exchanges"
    )
    op.drop_index(
        op.f("ix_color_role_exchanges_role_id"), table_name="color_role_exchanges"
    )
    op.drop_index(
        op.f("ix_color_role_exchanges_item_id"), table_name="color_role_exchanges"
    )
    op.drop_index(
        op.f("ix_color_role_exchanges_guild_id"), table_name="color_role_exchanges"
    )
    op.drop_index(
        op.f("ix_color_role_exchanges_created_at"),
        table_name="color_role_exchanges",
    )
    op.drop_table("color_role_exchanges")
    op.drop_index(
        op.f("ix_color_role_shop_items_role_id"),
        table_name="color_role_shop_items",
    )
    op.drop_index(
        op.f("ix_color_role_shop_items_guild_id"),
        table_name="color_role_shop_items",
    )
    op.drop_table("color_role_shop_items")
