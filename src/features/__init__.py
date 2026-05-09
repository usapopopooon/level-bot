"""Feature packages.

各 feature ディレクトリは以下を含み、互いに独立して捨てやすい構造にしてある:

    - service.py      ビジネスロジック (DB CRUD + 計算)
    - schemas.py      Web 用 Pydantic レスポンス schema (必要な feature のみ)
    - routes.py       FastAPI ルータ (必要な feature のみ)
    - test_*.py       コロケートされた pytest テスト

Feature 間で参照関係がある場合は ``service.py`` 経由のみ。SQLAlchemy モデルは
``database/models.py`` に集約しており、これは横断インフラとして扱う。
"""
