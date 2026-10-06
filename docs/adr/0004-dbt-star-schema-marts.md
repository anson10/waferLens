# ADR-0004: dbt for transformations, marts as a star schema

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

After phase 1 the database holds normalised operational tables: 23 tables shaped for loading
and integrity (genealogy, hypertables, wafer maps as arrays). Reporting needs something else:
Power BI (phase 7) works best on a star schema, Grafana (phase 4) and SPC (phase 3) need
measurements already joined to their chamber, recipe and spec limits, and the same business
rules (what counts as yield, which pass metrology measures) must not be re-implemented in
every consumer.

Phase 1 already wrote seven workload queries by hand; each one re-joined genealogy, products
and bins its own way.

## Options considered

1. **More hand-written SQL views in Alembic migrations.** No new tool, but no tests beyond
   "it compiles", no lineage, no incremental builds, and every change is a migration.
2. **Transformations in Python (pandas) inside the pipeline.** Flexible, but moves millions of
   rows out of the database and back, and hides the logic from SQL readers.
3. **dbt models in the database.** SQL stays in the database; models are versioned files with
   declared dependencies, data tests, unit tests, generated docs and incremental
   materialisation; dbt is what analytics-engineering job ads in Germany list.

## Decision

All reporting transformations are dbt models in three schemas: `staging` (one view per source
table: renames and types only), `intermediate` (reusable joins: route history, a unified
measurement stream) and `marts` (a star schema of facts at a stated grain and dimensions).
Alembic keeps owning the operational schema; dbt only reads it.

## Consequences

- **One definition per business rule.** Yield, final pass, spec z-scores and queue time are
  computed once in dbt and read by everyone. A singular test checks the mart's yield against
  the loader's `wafer_yield` view, so the two definitions can't silently diverge.
- **Tested transformations:** 82 data tests and 3 unit tests run in CI on a fresh dev fab
  (`dbt build`), including unit tests for the window-function and recursive-CTE logic.
- **Power BI-ready:** facts join dimensions on integer keys; `dim_date` uses a `yyyymmdd`
  key; node is flattened into product and tool into chamber, so the model is a star, not a
  snowflake.
- **Incremental `fct_measurements` (3.07M rows on demo)** is fast for appended data but has to
  cope with the loader's truncate-and-reload. A pre-hook deletes rows from an earlier load;
  after a full reload a `--full-refresh` of that model is faster (48 s vs 131 s), which the
  Dagster job (phase 2b) does.
- **Costs:** a second tool and a second schema owner to keep in step (Alembic for sources,
  dbt for marts); `dbt deps` needs network access in CI; marts duplicate data (~3.8M rows on
  demo), which is the usual price of a reporting layer.
