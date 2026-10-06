# Performance

Measured on a laptop: WSL2 on Windows with **7.4 GB RAM** and 12 cores, Docker, TimescaleDB 2.17 /
PostgreSQL 16, Python 3.12. One run per profile (seed 42); expect ±30% between runs and
machines.

## Profiles end to end

| | `demo` | `stress` |
|---|---|---|
| Wafers / lots | 25,000 / 1,018 | 125,000 / 5,151 |
| Rows loaded (fab) | 4,825,797 | 24,332,884 |
| `make seed` wall time | ~2–2.5 min | **10.0 min** |
| Simulate | 5–20 s, peak ~1.0 GB | 33–49 s, peak **3.6 GB** |
| Load | 97–151 s | 484–534 s, peak **4.2 GB** (Python) |
| Database size (incl. SECOM) | 850 MB | 4.2 GB |
| `tool_sensor_readings` chunks (7 days) | 27 | 53 |
| Mean wafer yield | 87.13% | 87.39% |

### Load stages, stress

| Stage | Seconds | Rows | Rows/s |
|---|---|---|---|
| Read Parquet | 5.8 | | |
| Data contracts | 34.3 | | |
| COPY `tool_sensor_readings` | 210.7 | 14,906,360 | 70.7k |
| COPY `metrology_measurements` | 69.3 | 4,984,758 | 71.9k |
| COPY `wafer_step_history` | 46.9 | 3,726,590 | 79.5k |
| COPY `wafer_maps` | 12.4 | 122,378 | |
| Derive `wafer_bin_summary` | 45.4 | 451,557 | |
| Refresh `wafer_yield` | 0.5 | | |
| Re-add foreign keys | 40.2 | | |
| `ANALYZE` | 11.8 | | |
| **Total** | **483.8** | | |

**Memory is the limit on this machine.** During the stress load the whole VM peaked at
5.1 of 7.4 GB (Python 4.2 GB, the rest mostly Postgres). The loader holds every table in
pandas so the contracts can check keys and cross-table rules. Stress therefore needs about
8 GB of RAM. If that becomes a problem, the large tables can be validated column by column
and streamed to COPY by Parquet row group.

## Insert methods

`make bench-load` inserts the same 20,000 real sensor rows four ways, each in a transaction
that is rolled back:

| Method | Rows/s | vs ORM |
|---|---|---|
| ORM (`session.add_all` + flush) | 1,834 | 1.0x |
| Core (`insert`, executemany) | 2,393 | 1.3x |
| COPY, foreign keys checked per row | 7,527 | 4.1x |
| COPY, foreign keys dropped | 20,703 | 11.3x |

The insert API matters less than the foreign keys: Core is barely faster than the ORM
because both pay four foreign-key lookups per row. The loader therefore drops the foreign
keys, COPYs, and re-adds them in the same transaction; `ADD CONSTRAINT` validates all rows
in one set-based join (40 s for 24M rows on stress). On dev this took the load from 38 s to
9.7 s, and formatting timestamps with numpy instead of pandas brought it to 5.8 s.

## Key queries

`make explain` runs the workload queries in `sql/queries/` under
`EXPLAIN (ANALYZE, BUFFERS)`, three times each, and reports the median. These are the
queries later phases depend on: SPC charts, dashboards, drill-downs, commonality and yield
reporting. "Blocks" is 8 kB pages touched; "chunks" is hypertable chunks actually read.

| Query | Demo ms | Stress ms | Stress blocks | Stress chunks |
|---|---|---|---|---|
| 01 control chart (one chamber, ±7 days around a drift) | 7.1 | 7.7 | 1,771 | 53 |
| 02 daily sensor means (one sensor, whole period) | 318.5 | 581.9 | 258,281 | 53 |
| 03 metrology SPC series (one step, last 30 days) | 12.6 | 23.6 | 374 | 6 |
| 04 wafer trace (all steps and sensors of one wafer) | 3.9 | 7.2 | 4,915 | 53 |
| 05 commonality (chambers behind the worst 10%) | 286.3 | 482.1 | 337,363 | 0 |
| 06 weekly yield by product | 98.5 | 355.2 | 23,900 | 0 |
| 07 excursion impact (wafers + yield per excursion) | 69.3 | 634.7 | 36,450 | 0 |

### What the plans showed, and what changed

1. **`wafer_yield` is now a materialized view.** As a plain view, every query that read yield
   rebuilt it from `wafer_bin_summary`: ~570 ms per query on stress, and once per parallel
   worker (`loops=5` in the plan). Yield only changes when data is loaded, so migration 0003
   materializes it with a unique index on `wafer_id`, and the loader refreshes it (0.5 s).

   | Query (stress) | Plain view | Materialized |
   |---|---|---|
   | 05 commonality | 860 ms | 482 ms |
   | 06 weekly yield | 793 ms | 355 ms |
   | 07 excursion impact | 1,151 ms | 635 ms |

2. **Index for query 02 rejected.** The only sensor index leads with `chamber_id`, so "one
   sensor across all chambers" reads 258k blocks (2 GB). An index on `(parameter_id, time)`
   halved it (583 → 301 ms) but costs 450 MB and 15 s on every load. A dashboard aggregate
   over all history is the job of a TimescaleDB continuous aggregate (phase 4), which turns
   this into a lookup of pre-computed daily rows.

3. **Chunk exclusion.** Query 03 bounds time with a scalar subquery, and TimescaleDB excludes
   chunks at run time: it reads 6 of 53. Queries 01 and 04 get their time bounds from a join,
   so every chunk's index is probed, but each probe is cheap (8 ms total). Rewriting 01 with
   scalar bounds saved 3 ms and hurt readability, so it stays as is.

4. **The plan for query 07 changes with scale.** On demo the planner uses the
   `(chamber_id, track_in)` genealogy index (69 ms). On stress, 72 excursions with long
   windows match ~142k history rows, the planner switches to a parallel sequential scan of
   all 3.7M rows, and the query takes 635 ms. That's a reasonable choice at that selectivity,
   and the reason to measure at more than one scale.

## Not done yet

- Continuous aggregates for dashboard rollups (phase 4) — query 02.
- `dbt` marts (phase 2) will give reporting queries pre-joined fact tables.
- Load: streaming large tables by row group (memory), parallel COPY of the two hypertables,
  binary COPY, and TimescaleDB compression for older chunks.
