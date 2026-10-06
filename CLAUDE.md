# CLAUDE.md — WaferLens v2

## What this is
A fab yield excursion detection and root-cause platform, built as a portfolio project for
semiconductor data / yield / analytics roles in Germany. It answers one question:
**yield dropped — which tool/chamber caused it, how early could we have known, and what does it
look like on the wafer?**

`ROADMAP.md` is the source of truth for scope and order. Work phase by phase and tick its
checkboxes as items land. v1 lives on the `waferlens-v1-archive` branch; do not copy code from it
without reviewing it first.

## Stack
- Python 3.12, uv, ruff, pyright, pytest + hypothesis, pre-commit
- PostgreSQL 16 + TimescaleDB (Docker), SQLAlchemy 2.0 + psycopg 3, Alembic (from phase 1)
- dbt (star-schema marts), Dagster
- Grafana (provisioned as code), Power BI (PBIP, phase 7, Windows side)
- scikit-learn / gradient boosting + MLflow for SECOM; wafer-map classification via the FabEye API
- Redpanda (phase 6, optional)

## Related project: FabEye
`~/FabEye` (github.com/anson10/FabEye) already does WM-811K wafer-map classification with
lot-disjoint evaluation, conformal prediction, ONNX and a FastAPI service (`/predict/batch`,
`/metrics`). **Never retrain a wafer-map model here.** WaferLens calls FabEye as a service.

## Layout
- `src/waferlens/` — db, simulate, ingest, spc, rootcause, ml, stream, orchestration
- `tests/unit/` (no containers) and `tests/integration/` (marked `integration`, need `make up`)
- `dbt/`, `grafana/`, `powerbi/`, `docs/adr/`

## Conventions
- All DB access goes through `waferlens.db.session` (`get_engine`, `get_session`).
- Postgres is the only database: no SQLite fallback, and integration tests run against the real container.
- Simulator and ingest stay decoupled: the simulator writes files, ingest reads them.
- Simulator output must log every injected excursion as ground truth, because detection is evaluated against it.
- Complex aggregations are SQL (dbt models, or commented raw SQL) with comments on the business logic.
- dbt marts are a star schema (`fct_*`, `dim_*`), since Power BI consumes them in phase 7.
- Every tool added needs an ADR in `docs/adr/` (the user writes the reasoning; drafts only).
- Every claim in the README must be reproducible by a `make` target.
- Don't leave scratch scripts or generated notes in the repo.

## Commands
```bash
make install    # uv sync + pre-commit hooks
make up / down  # containers (reset = also wipe volumes)
make check      # lint + typecheck + all tests (what CI runs)
make test-unit  # no containers needed
```

## Git
- Feature branch per checklist group, merged via PR.
- Commits: `type(scope): subject` plus 3–5 bullets; no Claude attribution lines.
