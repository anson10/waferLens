-include .env
export

.DEFAULT_GOAL := help
.PHONY: help install up down reset logs psql migrate simulate lint format typecheck test test-unit check

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-10s %s\n", $$1, $$2}'

install: ## Create .venv, install deps, install git hooks
	uv sync
	uv run pre-commit install

up: ## Start TimescaleDB + Grafana and wait until healthy
	docker compose up -d --wait

down: ## Stop containers (data kept)
	docker compose down

reset: ## Stop containers and delete all data volumes
	docker compose down -v

logs: ## Follow container logs
	docker compose logs -f

psql: ## Open a psql shell in the db container
	docker compose exec db psql -U $${POSTGRES_USER:-waferlens} -d $${POSTGRES_DB:-waferlens}

migrate: ## Apply Alembic migrations to the dev database
	uv run alembic upgrade head

PROFILE ?= demo
SEED ?= 42
simulate: ## Generate fab data as Parquet in data/$(PROFILE) (PROFILE=dev|demo|stress)
	uv run python -m waferlens.simulate --profile $(PROFILE) --seed $(SEED)

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-fix lint and formatting
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## Pyright
	uv run pyright

test: ## All tests incl. integration (needs `make up`)
	uv run pytest --cov --cov-report=term-missing

test-unit: ## Unit tests only, no containers needed
	uv run pytest -m "not integration"

check: lint typecheck test ## Everything CI runs
