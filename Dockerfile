FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

RUN mkdir -p data

# Default: run migrations, then start bot + API server in parallel
CMD ["sh", "-c", "alembic upgrade head && (python -m src.main & uvicorn src.web.app:app --host 0.0.0.0 --port ${PORT:-8000} & wait)"]
