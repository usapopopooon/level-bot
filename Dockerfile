FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/ scripts/

RUN chmod +x scripts/*.sh && mkdir -p data

# Default: bot + API を 1 コンテナで起動する。
# Railway などで分割する場合はサービス側の Custom Start Command で
#   sh scripts/start-bot.sh
#   sh scripts/start-api.sh
# のいずれかを上書きする (release は scripts/release.sh)。
CMD ["sh", "scripts/start-all.sh"]
