# ADR-0003: Wafer maps as 2-D arrays, not one row per die

- **Status:** Draft — write the reasoning sections in your own words before marking Accepted
- **Date:** 2026-10-06

## Context
<!-- Facts to build on; rewrite as prose:
- Demo profile: 25,000 wafers × ~500 dies ≈ 12.5M die rows if stored one per die.
- Consumers: FabEye needs the whole grid per wafer (0 off / 1 good / 2 fail);
  yield and Pareto reporting need counts per bin; nobody queries "die (12, 7) across all wafers"
  in this project.
- Postgres supports multi-dimensional arrays (smallint[][]) with a CHECK on array_ndims.
-->

## Options considered
1. **One row per die** (wafer_id, die_x, die_y, bin): <!-- pros: plain SQL per die; cons: size, load time, every reader re-assembles the grid -->
2. **2-D array per wafer + bin count table**: <!-- -->
3. **Blob / image file per wafer outside the DB**: <!-- -->

## Decision
<!-- one or two sentences -->

## Consequences
<!-- e.g. 25k rows instead of 12.5M; FabEye payload is a direct read;
     per-die spatial SQL needs unnest() with ordinality; wafer_bin_summary must be kept
     consistent with the map (who guarantees that? loader + a test);
     what would make you switch to option 1? -->
