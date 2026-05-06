.PHONY: install dev test lint typecheck migrate run web docker-build docker-up docker-down

install:
	pip install -e ".[dev]"

dev:
	python -m src.main

web:
	uvicorn src.web.app:app --reload --host 0.0.0.0 --port 8000

migrate:
	alembic upgrade head

migration:
	alembic revision --autogenerate -m "$(m)"

test:
	pytest -q

lint:
	ruff check src
	ruff format --check src

format:
	ruff format src
	ruff check --fix src

typecheck:
	mypy src

docker-build:
	docker build -t level-bot:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down
