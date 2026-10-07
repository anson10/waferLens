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

## Transformations (dbt)

`make dbt` builds 40 models and runs 85 tests on demo in about 3 minutes; almost all of it is
`fct_measurements` (3.07M rows):

| Build of `fct_measurements` | Seconds |
|---|---|
| First build (`CREATE TABLE AS`) | 48 |
| Incremental rerun, no new data (3-day look-back, 53k rows reprocessed) | 13 |
| Incremental run right after a full reload (pre-hook deletes old load, delete+insert of 3.07M rows) | 131 |

After a full reload, `dbt build --full-refresh -s fct_measurements` is the faster path; the
Dagster job (phase 2b) uses it when the load asset changed.

## Whole pipeline (Dagster `full_rebuild`)

**Phase 5 update:** once the SECOM model (2 min 54 s) joined the job, the first run on this
7.4 GB machine ran out of memory: the SECOM model search ran beside the fab contracts check,
the kernel killed Postgres, and the run failed. The steps that hold whole tables in Python
(simulate, contracts, load, SPC, SECOM model) are now tagged and the executor runs one of
them at a time. The run then takes **16 min 30 s**; the contracts check waits ~3 min for the
SECOM model, the price of not crashing. FabEye scoring (phase 5a) adds ~90 s after the load.

The rest of this section is the phase 3 run, before that change:

`make pipeline` on demo: **8 min 39 s** end to end, one run, including SPC. Dagster splits
the dbt project into steps around the SPC asset (measurements in, alarms out); steps without
a dependency between them run in parallel, so the step times add up to more than the wall time.

| Step | Time |
|---|---|
| `simulated_fab` (simulate + Parquet) | 24 s |
| `fab_contracts` (blocking check) | 7 s |
| `fab_tables` (atomic COPY load) | 2 min 33 s |
| `secom_tables` (cached download + load) | 9 s |
| `dbt_models` (staging → `fct_measurements`, full refresh) | 1 min 56 s |
| `spc_results` (900 series, 156,779 alarms) | 1 min 31 s |
| `dbt_models` (`fct_spc_alarms` and the other steps) | 25–32 s each |

Before SPC was added the run took 4 min 42 s; the dbt step was ~2x faster than `make dbt`
straight after a reload (179 s), because the job uses `--full-refresh` instead of the
incremental delete+insert path.

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
| 08 = 02 from the `sensor_daily` continuous aggregate | **3.1** | – | | |

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
   over all history is the job of a TimescaleDB continuous aggregate, which turns this into a
   lookup of pre-computed daily rows: see 5.

3. **Chunk exclusion.** Query 03 bounds time with a scalar subquery, and TimescaleDB excludes
   chunks at run time: it reads 6 of 53. Queries 01 and 04 get their time bounds from a join,
   so every chunk's index is probed, but each probe is cheap (8 ms total). Rewriting 01 with
   scalar bounds saved 3 ms and hurt readability, so it stays as is.

4. **The plan for query 07 changes with scale.** On demo the planner uses the
   `(chamber_id, track_in)` genealogy index (69 ms). On stress, 72 excursions with long
   windows match ~142k history rows, the planner switches to a parallel sequential scan of
   all 3.7M rows, and the query takes 635 ms. That's a reasonable choice at that selectivity,
   and the reason to measure at more than one scale.

5. **Continuous aggregate for daily sensor rollups (phase 4).** Migration 0006 adds
   `sensor_daily`: count, mean, sd, min and max per day, chamber and sensor, refreshed by the
   loader after each load (`materialized_only = false`, so rows newer than the last refresh
   still show). Query 08 is query 02 rewritten against it; both return the same 1,629 rows.

   | Demo | Query 02 (raw readings) | Query 08 (`sensor_daily`) |
   |---|---|---|
   | Time | 302.8 ms | **3.1 ms** (~100x) |
   | Blocks | 22,440 | 309 |
   | Rows aggregated | 98,140 readings | 1,629 daily rows (of 28,864) |

   Grafana's "daily mean ± 1 sd" panel reads it, so a whole-period view costs nothing.

## Real-time SPC (phase 6)

`make stream-demo`: one day of the demo fab (17,632 sensor events) published at 800 events/s
to Redpanda (one core, 512 MB) and consumed in batches of up to 500 with a 0.5 s poll window.

| | Value |
|---|---|
| Wall time for the day | ~34 s (publishing at 800/s is the bottleneck) |
| End-to-end latency, event published → alarm committed | p50 ~270 ms, p95 ~515 ms |
| Injected +2σ step caught after | 3 points (CUSUM) |
| Background alarm rate on undisturbed series | ~0.5% (EWMA + CUSUM design ~0.4%) |

Latency is dominated by the batching window: the consumer waits up to 0.5 s to fill a batch,
and commits once per batch. A smaller window lowers latency at the cost of more, smaller
transactions.

**Clock caveat.** On this WSL2 machine the wall clock stepped back by 858 ms and 985 ms within
75 s (WSL's systemd-timesyncd and the Windows host both correcting it), and wall-clock
latencies came out negative for a few alarms. The demo therefore measures latency on the
monotonic clock; the `stream_alarms` timestamps are wall clock and need synced hosts.

## Not done yet

- Load: streaming large tables by row group (memory), parallel COPY of the two hypertables,
  binary COPY, and TimescaleDB compression for older chunks.
