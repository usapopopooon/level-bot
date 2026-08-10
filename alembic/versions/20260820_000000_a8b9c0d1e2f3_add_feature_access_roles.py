"""add feature access roles

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-08-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | Sequence[str] | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_access_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "feature IN ('cafe_gacha', 'color_role_shop')",
            name="ck_feature_access_roles_feature",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "feature",
            "role_id",
            name="uq_feature_access_role",
        ),
    )
    op.create_index(
        op.f("ix_feature_access_roles_feature"),
        "feature_access_roles",
        ["feature"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feature_access_roles_guild_id"),
        "feature_access_roles",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feature_access_roles_role_id"),
        "feature_access_roles",
        ["role_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_feature_access_roles_role_id"),
        table_name="feature_access_roles",
    )
    op.drop_index(
        op.f("ix_feature_access_roles_guild_id"),
        table_name="feature_access_roles",
    )
    op.drop_index(
        op.f("ix_feature_access_roles_feature"),
        table_name="feature_access_roles",
    )
    op.drop_table("feature_access_roles")
