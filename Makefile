.PHONY: install dev worker up down logs test lint fmt seed evals check clean

install:
	uv sync --all-groups

dev:
	uvicorn app.main:app --reload --port 8000

worker:
	python -m app.worker

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

test:
	uv run pytest -q

lint:
	uv run ruff check app tests scripts

fmt:
	uv run ruff format app tests scripts
	uv run ruff check --fix app tests scripts

seed:
	uv run python scripts/seed_knowledge_base.py

evals:
	uv run python scripts/run_evals.py

check: lint test

clean:
	docker compose down -v
	rm -rf .pytest_cache .ruff_cache **/__pycache__
