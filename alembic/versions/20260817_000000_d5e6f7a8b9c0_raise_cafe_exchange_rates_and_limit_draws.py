"""raise cafe exchange rates and limit hourly draws

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cafe_gacha_user_states",
        sa.Column("draw_count_hour_started_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "cafe_gacha_user_states",
        sa.Column(
            "hourly_draw_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_cafe_gacha_user_hourly_draw_count",
        "cafe_gacha_user_states",
        "hourly_draw_count BETWEEN 0 AND 10",
    )
    op.execute(
        """
        UPDATE cafe_gacha_user_states AS state
        SET draw_count_hour_started_at = date_trunc('hour', CURRENT_TIMESTAMP),
            hourly_draw_count = LEAST((
                SELECT count(*)
                FROM cafe_gacha_draws AS draw
                WHERE draw.guild_id = state.guild_id
                  AND draw.user_id = state.user_id
                  AND draw.created_at >= date_trunc('hour', CURRENT_TIMESTAMP)
                  AND draw.created_at < date_trunc('hour', CURRENT_TIMESTAMP)
                      + interval '1 hour'
            ), 10)
        """
    )
    op.execute(
        """
        UPDATE cafe_gacha_draws
        SET exchange_xp = CASE rarity
            WHEN 'C' THEN 3
            WHEN 'UC' THEN 10
            WHEN 'R' THEN 30
            WHEN 'SR' THEN 100
            WHEN 'SSR' THEN 300
        END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE cafe_gacha_draws
        SET exchange_xp = CASE rarity
            WHEN 'C' THEN 2
            WHEN 'UC' THEN 4
            WHEN 'R' THEN 8
            WHEN 'SR' THEN 20
            WHEN 'SSR' THEN 50
        END
        """
    )
    op.drop_constraint(
        "ck_cafe_gacha_user_hourly_draw_count",
        "cafe_gacha_user_states",
        type_="check",
    )
    op.drop_column("cafe_gacha_user_states", "hourly_draw_count")
    op.drop_column("cafe_gacha_user_states", "draw_count_hour_started_at")
