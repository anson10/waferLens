# Performance

Measured on a laptop: WSL2 on Windows, Docker, TimescaleDB 2.17 / PostgreSQL 16, Python 3.12.
Numbers are for one run of the `demo` profile (seed 42) and will vary by machine.

## End-to-end seed

`make seed` (migrate, simulate, load) takes about **2 minutes** for the demo fab:

| Stage | Seconds | Rows |
|---|---|---|
| Simulate (25,000 wafers) | ~9 | 4.74M |
| Read Parquet | 2.0 | |
| Data contracts (pandera + cross-table) | 11.8 | |
| COPY `tool_sensor_readings` (hypertable) | 51.1 | 2,960,052 |
| COPY `metrology_measurements` (hypertable) | 16.2 | 984,600 |
| COPY `wafer_step_history` | 13.5 | 740,013 |
| COPY `wafer_maps` (2-D arrays) | 4.2 | 24,090 |
| Derive `wafer_bin_summary` (`unnest`) | 10.6 | 88,494 |
| Re-add foreign keys (validates every row) | 7.4 | |
| `ANALYZE` | 6.2 | |
| **Load total** | **~97–124** | **4,825,797** |

The loaded database is 777 MB, with 27 weekly chunks in `tool_sensor_readings`.

## Insert methods

`make bench-load` inserts the same 20,000 real sensor rows four ways, each in a transaction
that is rolled back:

| Method | Rows | Seconds | Rows/s | vs ORM |
|---|---|---|---|---|
| ORM (`session.add_all` + flush) | 20,000 | 10.91 | 1,834 | 1.0x |
| Core (`insert`, executemany) | 20,000 | 8.36 | 2,393 | 1.3x |
| COPY, foreign keys checked per row | 20,000 | 2.66 | 7,527 | 4.1x |
| COPY, foreign keys dropped | 20,000 | 0.97 | 20,703 | 11.3x |

**What this shows:** the insert API matters less than the foreign keys. Core is barely faster
than the ORM, because both pay for four foreign-key lookups per row. COPY removes the
per-statement overhead (4x), and dropping the foreign keys removes the per-row lookups
(another 2.8x).

So the loader runs inside one transaction:

1. truncate, drop the foreign keys;
2. COPY every table;
3. re-add the foreign keys. `ALTER TABLE … ADD CONSTRAINT` validates all rows with one
   set-based join, so integrity is still checked before commit, just not row by row.

On the dev profile this took the load from 38 s (foreign keys on) to 9.7 s, and to 5.8 s
after also formatting timestamps with numpy instead of pandas' per-value formatter. A failed
load rolls everything back, including the dropped constraints (`tests/integration/test_loader.py`).

The benchmark's COPY rates are lower than in the full load (58k rows/s for sensors) because
20,000 rows don't amortise the fixed cost, and the benchmark rows land in a new chunk.

## Not done yet

- **Stress profile** (125,000 wafers, ~24M rows) and `EXPLAIN ANALYZE` of the key queries:
  phase 1 checklist, final item.
- **Further load speed-ups** if needed: dropping and rebuilding secondary indexes around COPY,
  binary COPY, loading the two hypertables in parallel connections, TimescaleDB compression
  for older chunks.
