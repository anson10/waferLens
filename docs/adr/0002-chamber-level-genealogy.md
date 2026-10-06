# ADR-0002: Chamber-level wafer genealogy

- **Status:** Accepted
- **Date:** 2026-10-06

## Context

WaferLens has to answer "which tool or chamber caused this yield drop?". That is only
possible if we know, for every wafer, exactly where it was processed at every step.

v1 stored a `tool_id` on each process step and nothing per wafer. Real equipment doesn't work
that way. An etch, CVD or CMP tool usually has two to four chambers, and the 25 wafers of one
lot are spread across them. Excursions are very often confined to a single chamber: a worn
CMP pad, an etch chamber that came back from preventive maintenance slightly off, or a
leaking chuck. If lot 47 went through ETCH-02 and only chamber B is drifting, a tool-level
record makes all 25 wafers suspects; a chamber-level record narrows it to the 12 that ran
in B, and the comparison against the 13 that ran in A is the signal itself.

Two more facts shaped the design:

- **Metrology is sampled.** Only about 5 of 25 wafers per lot are measured at a given step,
  but yield is known for every wafer at sort, weeks later. The processing path must be
  recorded for every wafer, measured or not.
- **Lots change.** Lots get split, merged and reworked, so the lot a wafer belongs to at
  sort is not necessarily the lot it was in at step 12.

## Options considered

1. **Tool on the step (v1).** Simple, but cannot separate chambers, and says nothing about
   individual wafers. Ruled out by the core question of the project.
2. **`chamber_id` on each measurement row.** Gives chamber context where a measurement
   exists, but metrology is sampled, so roughly 80% of wafers would have no record of their
   chamber at most steps. Commonality analysis on low-yield wafers would have large holes.
3. **A dedicated genealogy table, `wafer_step_history`.** One row per wafer × route step ×
   pass, holding chamber, recipe, lot and track-in/track-out times, written for every wafer
   regardless of sampling.

## Decision

We use option 3: `wafer_step_history` is the single source of truth for where each wafer was
processed, keyed on `(wafer_id, route_step_id, pass_no)`.

## Consequences

- **Commonality analysis becomes a join, not an inference.** "Which chambers do the low-yield
  wafers share, compared with the good ones?" is a GROUP BY over this table joined to
  `wafer_yield`. An index on `(chamber_id, track_in)` serves the reverse question, "which
  wafers went through chamber B between Monday and Wednesday?".
- **Size.** About 750k rows for the demo profile (25,000 wafers × ~30 steps) and ~3.75M for
  stress. That is small for Postgres, so it stays an ordinary table rather than a hypertable.
- **Rework keeps its history.** A repeated step is `pass_no = 2`, not an overwrite, so a wafer
  that was reworked in a different chamber still shows both paths.
- **Splits don't lose traceability.** Each row stores the lot the wafer was in *at that step*;
  `wafers.lot_id` only holds the current lot.
- **Deliberate denormalisation.** `tool_sensor_readings` also carries `chamber_id`, although it
  could be looked up here. Grafana plots sensor data per chamber over millions of rows, and
  avoiding a join on every panel refresh is worth one extra smallint column. The loader writes
  both from the same simulator output, so they cannot disagree.
- **What would make us revisit this:** batch tools that process many wafers in one run
  (furnaces) would need a run/batch table between wafer and chamber. None of the simulated
  steps are batch steps today.
