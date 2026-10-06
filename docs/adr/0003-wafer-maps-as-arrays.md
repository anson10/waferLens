# ADR-0003: Wafer maps as 2-D arrays, not one row per die

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

At wafer sort every die is tested and given a bin: pass, or one of several fail bins. That
result is the wafer map, and it feeds two consumers in this project:

- **FabEye** classifies the spatial failure pattern (edge-ring, scratch, center…). It needs
  the whole grid of one wafer at a time, encoded as 0 = off wafer, 1 = good, 2 = fail.
- **Yield reporting** (dbt marts, Grafana, Power BI) needs counts per bin per wafer: yield,
  bin Paretos, loss by fail category.

The demo profile has 25,000 wafers at roughly 500 dies each, so storing one row per die
would mean about 12.5M rows, and about 62M in the stress profile. No query in this project
asks for one die position across many wafers.

## Options considered

1. **One row per die** `(wafer_id, die_x, die_y, bin_code)`. The most "relational" option, and
   any per-die question is plain SQL. But it is the largest table in the database by far,
   the slowest to load, and every consumer that wants a map has to rebuild the grid from
   500 rows.
2. **One 2-D `smallint[][]` array per wafer, plus a bin count table.** One row per wafer holds
   the whole map in exactly the shape FabEye reads, and `wafer_bin_summary` holds the counts
   that reporting needs.
3. **Map stored outside the database** (image or `.npy` file per wafer, path in the DB).
   Compact, but splits one fact across two storage systems, loses transactional consistency
   with the rest of the data, and makes the maps invisible to SQL.

## Decision

We use option 2: `wafer_maps.bin_map` stores the bin grid as a 2-D Postgres array
(0 = off wafer, 1 = pass, ≥ 2 = fail bin), and `wafer_bin_summary` stores die counts per bin.

## Consequences

- **25,000 rows instead of 12.5M** for the demo profile, which keeps load times and backups
  small and leaves the large-table budget to the sensor and metrology hypertables, where
  time-series queries actually need it.
- **FabEye input is a direct read.** Mapping every value ≥ 2 to 2 gives FabEye's encoding with
  no reassembly, which matters when phase 5 batch-scores all 25,000 wafers.
- **The fail bin is kept, not just pass/fail.** Storing bin codes rather than 0/1/2 means
  reporting can still separate functional from leakage fails, at no extra size.
- **The database enforces the shape.** A CHECK on `array_ndims(bin_map) = 2` rejects malformed
  maps even from the `COPY` loader, which bypasses the ORM.
- **Two representations must agree.** The map and `wafer_bin_summary` describe the same
  dies. The loader derives the counts from the map, and a test will check that they match.
- **Per-die SQL is clumsier.** A question like "yield by die position" needs
  `unnest(bin_map) WITH ORDINALITY` to turn the grid back into rows. That's acceptable for
  occasional analysis.
- **What would make us revisit this:** a regular need for cross-wafer per-die analysis, such as
  a die-position yield heatmap across thousands of wafers in Power BI. We would then add a
  derived per-die table or dbt model built from the arrays, rather than change the source
  of truth.
