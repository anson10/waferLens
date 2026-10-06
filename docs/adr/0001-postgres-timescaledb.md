# ADR-0001: PostgreSQL + TimescaleDB as the single datastore

- **Status:** Draft — write the reasoning sections in your own words before marking Accepted
- **Date:** 2026-10-06

## Context
<!-- Facts to build on; rewrite as prose:
- Measurements are append-only time series, 1M+ rows in phase 1, growing with streaming in phase 6.
- Consumers: dbt (phase 2), Grafana (phase 4), Power BI on Windows (phase 7), Dagster.
- v1 used SQLite in dev and Postgres in prod, which hid dialect differences (ROUND/NUMERIC, Decimal results).
-->

## Options considered
1. **SQLite**: what v1 used. <!-- why not: no concurrent writers, no Grafana/Power BI connector story, dev/prod drift -->
2. **DuckDB**: <!-- strong for analytics on Parquet; what's missing for live Grafana + streaming writes? -->
3. **Plain PostgreSQL 16**: <!-- ... -->
4. **PostgreSQL 16 + TimescaleDB**: <!-- hypertables, time_bucket, continuous aggregates, compression -->

## Decision
<!-- one or two sentences -->

## Consequences
<!-- e.g. Docker required for local dev and tests; same engine in dev, CI and demo;
     Grafana has a native TimescaleDB mode; Power BI uses the standard PostgreSQL connector;
     lock-in to a Postgres extension (what would migrating away cost?) -->
