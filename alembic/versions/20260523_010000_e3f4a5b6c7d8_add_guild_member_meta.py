"""add guild_member_meta table

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-23 01:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guild_member_meta",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_guild_member_meta"),
    )
    op.create_index(
        op.f("ix_guild_member_meta_guild_id"),
        "guild_member_meta",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_guild_member_meta_user_id"),
        "guild_member_meta",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_guild_member_meta_user_id"), table_name="guild_member_meta")
    op.drop_index(op.f("ix_guild_member_meta_guild_id"), table_name="guild_member_meta")
    op.drop_table("guild_member_meta")
