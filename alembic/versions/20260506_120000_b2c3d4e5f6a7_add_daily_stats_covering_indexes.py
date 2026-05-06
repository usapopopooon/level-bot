"""add daily_stats covering indexes

長期データ (数百万〜数千万行) でも index-only scan で集計が走るよう、
よく使うクエリ形に合わせた covering index を追加する。

クエリ別の対応 index:

    集計関数                          使う index
    ---------------------------------------------------------------
    get_guild_summary               ix_daily_stats_guild_date_cov
    get_daily_series                ix_daily_stats_guild_date_cov
    get_user_leaderboard            ix_daily_stats_guild_date_cov
    get_channel_leaderboard         ix_daily_stats_guild_date_cov
    get_user_profile (本人 daily)    ix_daily_stats_guild_user_date_cov
    get_user_profile (top channels) ix_daily_stats_guild_user_date_cov

INCLUDE 列に集計対象 (message_count / voice_seconds など) を入れることで、
heap fetch なしでクエリが完結する。

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-06 12:00:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ギルド全体集計 (summary / daily_series / leaderboard) 用
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

    # ユーザープロフィール用 (guild_id, user_id 起点で日付範囲スキャン)
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

    # 旧 narrow index は covering index で完全に代替されるので drop
    op.drop_index("ix_daily_stats_guild_date", table_name="daily_stats")
    op.drop_index("ix_daily_stats_guild_user", table_name="daily_stats")


def downgrade() -> None:
    op.create_index(
        "ix_daily_stats_guild_user",
        "daily_stats",
        ["guild_id", "user_id"],
    )
    op.create_index(
        "ix_daily_stats_guild_date",
        "daily_stats",
        ["guild_id", "stat_date"],
    )
    op.drop_index("ix_daily_stats_guild_user_date_cov", table_name="daily_stats")
    op.drop_index("ix_daily_stats_guild_date_cov", table_name="daily_stats")
