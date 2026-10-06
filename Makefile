-include .env
export

.DEFAULT_GOAL := help
.PHONY: help install up down reset logs psql migrate simulate load secom seed dbt dbt-docs dagster pipeline pipeline-docs bench-load explain lint format typecheck test test-unit check

help: ## List targets
	@grep -hE '^[a-z-]+:.*## ' $(firstword $(MAKEFILE_LIST)) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-10s %s\n", $$1, $$2}'

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

load: ## Validate and COPY data/$(PROFILE) into Postgres (replaces existing data)
	uv run python -m waferlens.ingest --data data/$(PROFILE)

secom: ## Download (checksum-pinned) and load the real UCI SECOM dataset
	uv run python -m waferlens.ingest.secom

seed: migrate simulate load secom ## Migrate, simulate, load the fab and SECOM (PROFILE=dev|demo|stress)

dbt: ## Build and test the dbt models (staging, intermediate, marts) on loaded data
	cd dbt && uv run dbt deps --profiles-dir . && uv run dbt build --profiles-dir .

dbt-docs: ## Generate dbt docs and docs/dbt.md (lineage + model table)
	cd dbt && uv run dbt docs generate --profiles-dir .
	uv run python -m waferlens.db.dbt_docs

dagster: ## Open the Dagster UI on http://localhost:3001 (assets, jobs, checks, triggers)
	DAGSTER_HOME=$(CURDIR)/.dagster_home uv run dagster dev -m waferlens.orchestration.definitions -p 3001

pipeline: ## Run the full_rebuild job headless: simulate → contracts → load → SECOM → dbt (PROFILE=...)
	mkdir -p .dagster_home
	printf 'resources:\n  fab_data:\n    config:\n      profile: %s\n      seed: %s\n' $(PROFILE) $(SEED) > .dagster_home/run_config.yaml
	DAGSTER_HOME=$(CURDIR)/.dagster_home uv run dagster job execute -m waferlens.orchestration.definitions -j full_rebuild -c .dagster_home/run_config.yaml

pipeline-docs: ## Regenerate docs/pipeline.md from the Dagster asset graph
	uv run python -m waferlens.orchestration.docs

bench-load: ## Compare ORM, Core and COPY inserts on loaded data (rolled back)
	uv run python -m waferlens.ingest.benchmark --data data/$(PROFILE)

explain: ## EXPLAIN ANALYZE the key workload queries in sql/queries (on loaded data)
	uv run python -m waferlens.db.explain

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
