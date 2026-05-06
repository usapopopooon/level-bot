release: alembic upgrade head
worker: python -m src.main
api: uvicorn src.web.app:app --host 0.0.0.0 --port $PORT
# frontend は frontend/Dockerfile + frontend/railway.toml で別サービスとしてデプロイする。
# Procfile からは管理しない。
