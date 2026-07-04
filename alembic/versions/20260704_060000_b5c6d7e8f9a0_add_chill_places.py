"""add chill place tables

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-07-04 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guild_chill_places",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("required_level", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("emoji", sa.String(length=40), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "required_level >= 1", name="ck_guild_chill_places_required_level"
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 80",
            name="ck_guild_chill_places_name_length",
        ),
        sa.CheckConstraint(
            "emoji IS NULL OR char_length(emoji) BETWEEN 1 AND 40",
            name="ck_guild_chill_places_emoji_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "required_level", name="uq_guild_chill_place"),
    )
    op.create_index(
        op.f("ix_guild_chill_places_guild_id"),
        "guild_chill_places",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_guild_chill_places_required_level"),
        "guild_chill_places",
        ["required_level"],
        unique=False,
    )

    op.create_table(
        "user_chill_places",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("required_level", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "required_level >= 1", name="ck_user_chill_places_required_level"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "user_id", name="uq_user_chill_place"),
    )
    op.create_index(
        op.f("ix_user_chill_places_guild_id"),
        "user_chill_places",
        ["guild_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_chill_places_user_id"),
        "user_chill_places",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_chill_places_user_id"), table_name="user_chill_places")
    op.drop_index(op.f("ix_user_chill_places_guild_id"), table_name="user_chill_places")
    op.drop_table("user_chill_places")
    op.drop_index(
        op.f("ix_guild_chill_places_required_level"),
        table_name="guild_chill_places",
    )
    op.drop_index(
        op.f("ix_guild_chill_places_guild_id"),
        table_name="guild_chill_places",
    )
    op.drop_table("guild_chill_places")
