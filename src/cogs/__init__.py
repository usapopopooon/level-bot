"""Discord cog adapter layer.

各 cog は Discord のリスナー / スラッシュコマンドを受けて ``features/*`` の
サービス関数に委譲する。`/stats *` グループの分離が悩ましいため、関連する
スラッシュコマンドは ``slash_stats.py`` に集約している (1 cog 1 group)。
"""
