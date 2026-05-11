"""add reaction counts to daily_stats

daily_stats に reactions_received / reactions_given を追加し、覆う covering
index にも include する。既存行の値は 0 で埋める。

reactions_received: ユーザー (= メッセージ投稿者) のメッセージに付いたリアクション数。
                    人気度・受動的エンゲージメントの指標。
reactions_given:    ユーザー (= リアクションした人) が他人のメッセージに付けた数。
                    能動的なエンゲージメントの指標。

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-11 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column(
            "reactions_received",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "daily_stats",
        sa.Column(
            "reactions_given",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # covering index を作り直して INCLUDE 列にリアクションも含める
    # (新しい reactions_* 列も index-only scan で読めるようにする)
    op.drop_index("ix_daily_stats_guild_date_cov", table_name="daily_stats")
    op.drop_index("ix_daily_stats_guild_user_date_cov", table_name="daily_stats")
    op.create_index(
        "ix_daily_stats_guild_date_cov",
        "daily_stats",
        ["guild_id", "stat_date"],
        postgresql_include=[
            "user_id",
            "channel_id",
            "message_count",
            "char_count",
            "attachment_count",
            "reactions_received",
            "reactions_given",
            "voice_seconds",
        ],
    )
    op.create_index(
        "ix_daily_stats_guild_user_date_cov",
        "daily_stats",
        ["guild_id", "user_id", "stat_date"],
        postgresql_include=[
            "channel_id",
            "message_count",
            "char_count",
            "attachment_count",
            "reactions_received",
            "reactions_given",
            "voice_seconds",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_stats_guild_user_date_cov", table_name="daily_stats")
    op.drop_index("ix_daily_stats_guild_date_cov", table_name="daily_stats")
    op.create_index(
        "ix_daily_stats_guild_date_cov",
        "daily_stats",
        ["guild_id", "stat_date"],
        postgresql_include=[
            "user_id",
            "channel_id",
            "message_count",
            "char_count",
            "attachment_count",
            "voice_seconds",
        ],
    )
    op.create_index(
        "ix_daily_stats_guild_user_date_cov",
        "daily_stats",
        ["guild_id", "user_id", "stat_date"],
        postgresql_include=[
            "channel_id",
            "message_count",
            "char_count",
            "attachment_count",
            "voice_seconds",
        ],
    )

    op.drop_column("daily_stats", "reactions_given")
    op.drop_column("daily_stats", "reactions_received")
