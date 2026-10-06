# ADR-0002: Chamber-level wafer genealogy

- **Status:** Draft — write the reasoning sections in your own words before marking Accepted
- **Date:** 2026-10-06

## Context
<!-- Facts to build on; rewrite as prose:
- v1 linked measurements to a step and a tool_id only; there was no record of which chamber
  processed which wafer, so "which chamber caused this?" could not be asked.
- Multi-chamber tools (etch, CVD, CMP) run wafers of one lot through different chambers.
  Excursions are often in one chamber (e.g. a worn CMP pad, an etch chamber after a PM).
- Lots get split and reworked; the lot a wafer belongs to changes over its route.
- Phase 3 commonality analysis needs: wafer × step → chamber, recipe, lot, time.
-->

## Options considered
1. **Tool on the measurement row** (v1): <!-- why not enough -->
2. **Chamber on each measurement row only**: <!-- what about steps with no measurement on that wafer? (metrology is sampled) -->
3. **Separate genealogy table `wafer_step_history`**: <!-- one row per wafer × step × pass -->

## Decision
<!-- one or two sentences -->

## Consequences
<!-- e.g. ~750k rows for the demo profile; index on (chamber_id, track_in);
     rework modelled as pass_no; lot at time of step stored per row, so splits don't lose history;
     tool_sensor_readings also carries chamber_id (denormalised) — why? -->
