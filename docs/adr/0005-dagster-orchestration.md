# ADR-0005: Dagster for orchestration, modelled as assets

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

By phase 2 the pipeline has five stages run by hand in the right order: simulate, check
contracts, load, load SECOM, build dbt. Phases 3–6 add SPC, root cause, model scoring and a
stream. The order matters (dbt must not run on a half-loaded fab), failures must stop what
depends on them, and someone looking at a mart should be able to see what it was built from.

`make seed` chains the stages, but it can't say *which* table a mart depends on, can't run
only what a new data drop affects, and has no schedule, sensor or run history.

## Options considered

1. **Make + cron.** Already there; no lineage, retries, run history or partial reruns.
2. **Airflow.** The best-known scheduler; models *tasks*, not the tables they produce, so the
   dbt project needs a separate integration to show lineage, and local setup is heavy.
3. **Prefect.** Pleasant Python API; also task-centric.
4. **Dagster.** Models *assets* (tables, files) with dependencies; `dagster-dbt` turns every
   dbt model into an asset and every dbt test into an asset check; one `dagster dev` runs it
   locally.

## Decision

Dagster, with the pipeline written as assets: the Parquet drop, one asset per warehouse
table (keys matching the dbt source names), and the dbt project through `dagster-dbt`.
Contracts are a blocking asset check on the drop.

## Consequences

- **One lineage graph from config to mart:** 65 assets, and a test fails if a dbt source is
  not produced by a loader asset, so the graph can't silently break.
- **Failures stop downstream work:** the contracts check is blocking, so bad data never reaches
  the database (tested by forcing it to fail), and dbt tests block the models they test.
- **Two entry points:** `full_rebuild` (nightly schedule) and `ingest` (sensor on a new
  Parquet drop that the pipeline did not write itself, so a rebuild does not trigger a
  second load).
- **dbt runs with `--full-refresh` by default,** because the loader reloads everything and a
  full build is faster after a reload (docs/perf.md). Incremental builds are for appended
  data in phase 6.
- **Costs:** a heavy dependency tree (~100 packages); the dbt manifest must exist at import
  time, so the definitions run `dbt deps` + `dbt parse` when it is missing (needs network
  for the dbt package hub); run history lives in a local `DAGSTER_HOME` (SQLite), not a
  shared deployment.
