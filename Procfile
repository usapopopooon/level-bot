release: alembic upgrade head
worker: python -m src.main
api: uvicorn src.web.app:app --host 0.0.0.0 --port $PORT
frontend: cd frontend && npm ci && npm run build && node .next/standalone/server.js
