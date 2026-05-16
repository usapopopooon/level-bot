"""add level role awards and role meta tables

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-16 21:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_managed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "role_id", name="uq_role_meta"),
    )
    op.create_index("ix_role_meta_guild_id", "role_meta", ["guild_id"])
    op.create_index("ix_role_meta_role_id", "role_meta", ["role_id"])

    op.create_table(
        "level_role_awards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id", "level", name="uq_level_role_award_guild_level"
        ),
    )
    op.create_index(
        "ix_level_role_awards_guild_id", "level_role_awards", ["guild_id"]
    )
    op.create_index("ix_level_role_awards_role_id", "level_role_awards", ["role_id"])


def downgrade() -> None:
    op.drop_index("ix_level_role_awards_role_id", table_name="level_role_awards")
    op.drop_index("ix_level_role_awards_guild_id", table_name="level_role_awards")
    op.drop_table("level_role_awards")

    op.drop_index("ix_role_meta_role_id", table_name="role_meta")
    op.drop_index("ix_role_meta_guild_id", table_name="role_meta")
    op.drop_table("role_meta")
