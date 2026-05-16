"""add slot to level_role_awards and switch uniqueness to per-slot

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-17 03:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "level_role_awards",
        sa.Column("slot", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_constraint(
        "uq_level_role_award_guild_level",
        "level_role_awards",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_level_role_award_guild_slot_level",
        "level_role_awards",
        ["guild_id", "slot", "level"],
    )
    op.alter_column("level_role_awards", "slot", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    dup_rows = bind.execute(
        sa.text(
            """
            SELECT guild_id, level, COUNT(*) AS cnt
            FROM level_role_awards
            GROUP BY guild_id, level
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if dup_rows:
        sample = ", ".join(
            f"(guild_id={row[0]}, level={row[1]}, count={row[2]})"
            for row in dup_rows[:5]
        )
        raise RuntimeError(
            "Cannot downgrade level_role_awards: duplicate (guild_id, level) "
            "exists across slots. Resolve duplicates first. "
            f"Examples: {sample}"
        )

    op.drop_constraint(
        "uq_level_role_award_guild_slot_level",
        "level_role_awards",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_level_role_award_guild_level",
        "level_role_awards",
        ["guild_id", "level"],
    )
    op.drop_column("level_role_awards", "slot")
