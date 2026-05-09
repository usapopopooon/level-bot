"""User / channel display metadata feature.

Discord ID から表示名・アイコンを引くためのキャッシュ層。書き込みは
upsert (single + bulk)、読み込みは ID リスト → meta マップ。
"""
