# ADR-0001: PostgreSQL + TimescaleDB as the single datastore

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

WaferLens stores two very different kinds of data that have to be joined constantly:

- **Relational fab data:** products, routes, tools, chambers, lots, wafers and the genealogy
  table (ADR-0002). This is classic OLTP-shaped data with many foreign keys.
- **Time series:** tool sensor readings for every wafer at every step (~3M rows in the demo
  profile) and multi-site metrology (~1.6M rows), growing to ~30M rows in the stress profile
  and arriving continuously once streaming is added in phase 6.

The questions the project answers need both at once. "Which chamber's sensor drifted before
these wafers lost yield?" joins time series to genealogy to yield.

The same database is read by dbt (phase 2), Dagster, Grafana (phase 4), a streaming
consumer writing concurrently (phase 6) and Power BI Desktop on Windows (phase 7).

v1 used SQLite in development and PostgreSQL in production. That caused real bugs: `ROUND`
needed a `NUMERIC` cast on Postgres, and results came back as `Decimal` instead of `float`.
Tests passed against one engine while the deployed app ran on another.

## Options considered

1. **SQLite.** Zero setup, but a single writer, no server for Grafana or Power BI to connect
   to, no time-series features, and the dev/prod mismatch from v1.
2. **DuckDB.** Excellent for columnar analytics over Parquet, and would make the dbt models
   fast. But it is an embedded, single-process database: it cannot serve a loader, a streaming
   consumer, Grafana and Power BI at the same time, and Grafana and Power BI support is through
   plugins and ODBC rather than native connectors.
3. **InfluxDB or another dedicated time-series database.** Built for sensor data, but the
   genealogy and master data would have to live in a second relational database, and every
   root-cause question would become a cross-system join in Python.
4. **Plain PostgreSQL 16.** Handles the relational side and all consumers natively. At ~6M
   rows it would work, but time-bucketed dashboard queries scan whole tables, and partitioning,
   retention and rollups would all be hand-built.
5. **PostgreSQL 16 + TimescaleDB.** Everything in option 4, plus hypertables (automatic time
   partitioning into chunks), `time_bucket`, continuous aggregates (incrementally maintained
   rollups) and native compression, as an extension inside the same database.

## Decision

We use PostgreSQL 16 with the TimescaleDB extension as the only datastore, in every
environment: local Docker, CI (as a service container) and any deployment.

## Consequences

- **One engine everywhere.** Tests run against the same database version and extension as the
  demo, so v1's dev/prod dialect bugs cannot recur. The cost is that Docker is required for
  local development and integration tests.
- **Relational and time-series queries in one SQL statement.** Genealogy, yield and sensor data
  join directly, with foreign keys enforced even on the hypertables.
- **Dashboards stay fast as data grows.** Grafana panels use `time_bucket` and, from phase 4,
  continuous aggregates instead of scanning raw readings. Weekly chunks mean a query over the
  last two weeks only touches a couple of chunks. The stress profile and `docs/perf.md` are
  where this gets measured rather than assumed.
- **Native connectors for every consumer.** dbt-postgres, Grafana's PostgreSQL data source (with
  its TimescaleDB mode) and Power BI's built-in PostgreSQL connector all work without plugins.
- **Not the fastest option for pure analytics.** Wide aggregations over all history would be
  quicker in a columnar engine such as DuckDB. If that becomes a bottleneck, the dbt marts can
  be exported to Parquet and queried in DuckDB without changing the source of truth.
- **Extension lock-in and licensing.** Compression and continuous aggregates are under the
  Timescale License: free to self-host, but not offerable as a hosted database service. That is
  fine for this project. Hypertables are still Postgres tables, so leaving TimescaleDB means
  replacing them with native declarative partitioning and the rollups with materialized views.
  That is real work, but nothing in the application code would change.
