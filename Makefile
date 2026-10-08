-include .env
export

.DEFAULT_GOAL := help
.PHONY: help install up down reset logs psql migrate simulate load secom seed dbt dbt-docs spc spc-report rootcause rootcause-report story secom-model fabeye-report dashboards screenshots dagster pipeline pipeline-docs bench-load explain lint format typecheck test test-unit check powerbi-check stream-demo

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

spc: ## Phase I limits (frozen) + Phase II alarms into spc_* tables (needs make dbt first)
	uv run python -m waferlens.spc

spc-report: ## Simulated ARL + detection vs ground truth → docs/spc_benchmark.md (after make spc + dbt)
	uv run python -m waferlens.spc.report

rootcause: ## Commonality analysis of every excursion window → rootcause_candidates (after make dbt)
	uv run python -m waferlens.rootcause

rootcause-report: ## Root-cause accuracy + impact + SPC coverage → docs/root_cause.md (after spc, rootcause, dbt)
	uv run python -m waferlens.rootcause.report

story: ## Excursions end to end: alarm, suspects, wafers, cost → docs/excursion_story.md (EXC="40 12 10"; after pipeline + fabeye-report)
	uv run python -m waferlens.rootcause.story $(EXC)

secom-model: ## Train, evaluate + register the SECOM fail model (MLflow) → DB + docs/secom_model.md (after secom)
	uv run python -m waferlens.ml

stream-demo: ## Real-time SPC: replay a day as Kafka events, inject a drift, catch it (after pipeline)
	docker compose --profile stream up -d --wait redpanda
	uv run python -m waferlens.stream.demo

fabeye-report: ## Score every sorted wafer with FabEye → wafer_patterns + docs/fabeye_eval.md (after load)
	uv run python -m waferlens.patterns

powerbi-check: ## Log in as powerbi_reader (what Power BI uses) and list the marts with row counts
	docker compose exec -T -e PGPASSWORD=powerbi_reader db psql -h localhost -U powerbi_reader \
		-d $${POSTGRES_DB:-waferlens} -c "SELECT relname AS table, n_live_tup AS approx_rows \
		FROM pg_stat_user_tables WHERE schemaname = 'marts' ORDER BY relname"

dashboards: ## Regenerate grafana/dashboards/*.json from waferlens.dashboards (Grafana reloads them)
	uv run python -m waferlens.dashboards

screenshots: ## Render the dashboards to docs/img/grafana-*.png (starts the image renderer)
	docker compose --profile screenshots up -d --wait renderer grafana
	uv run python -m waferlens.dashboards.screenshots

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
