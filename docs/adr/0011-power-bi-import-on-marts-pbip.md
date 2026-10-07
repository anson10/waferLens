# ADR-0011: Power BI in Import mode on the dbt marts, saved as PBIP

- **Status:** Accepted
- **Date:** 2026-10-08

## Context

Power BI is the BI tool most German fab and analytics job ads ask for (ADR-0004 shaped the
dbt marts as a star schema for it). Grafana already covers live monitoring (ADR-0007); the
Power BI report is for the questions a yield engineer or manager asks of history: yield
trend by product, where dies are lost, what an excursion cost, which chamber caused it.

Three choices have to be made before building: how Power BI gets the data, what it can see,
and how the report lives in git. A `.pbix` file is a binary zip with the data inside: it
can't be reviewed, diffs are meaningless, and committing it commits the data.

## Options considered

**Data access**
1. **DirectQuery** on Postgres: always current, but every visual is a SQL query over WSL,
   DAX time intelligence and some modelling features are restricted, and the report is only
   as fast as the database.
2. **Import** of the marts: the data is copied into the VertiPaq engine on refresh; full
   DAX, fast visuals; ~1M rows of marts fit easily. The demo data changes only when the
   pipeline reruns, so staleness doesn't matter.

**Scope**
1. Import raw tables and model in Power BI (Power Query transformations).
2. Import only the dbt marts: transformations stay in tested SQL; Power BI does semantics
   (relationships, measures, security) and presentation.

**Format**
1. `.pbix` in git (or out of git).
2. **PBIP** with the semantic model in **TMDL**: a folder of text files; measures,
   relationships and roles diff line by line.

## Decision

Import mode, marts only, PBIP/TMDL in `powerbi/`. Power BI connects as `powerbi_reader`
(migration 0011), which can read `marts` and nothing else, so the report can't depend on raw
tables even by accident. `dim_excursion` was added to the marts so the four excursion-grain
facts share one dimension. The model is a single-direction star with a marked date table
and one inactive relationship (FabEye's true vs predicted pattern), and every measure is
checked against the same number computed in SQL on the marts rather than eyeballed.

## Consequences

- **Reviewable BI:** measures, relationships and RLS roles are text in git; `.pbix` and the
  local data cache are ignored.
- **One source of truth for logic:** yield, impact and root-cause numbers come from dbt; DAX
  only aggregates them, and the reference values catch a measure that disagrees.
- **Refresh is manual** (Power BI Desktop, after `make pipeline`); there is no gateway or
  Power BI Service deployment, which a production setup would need.
- **Windows dependency:** Power BI Desktop runs on Windows and reaches the database through
  WSL2's localhost forwarding; the demo database has no TLS, so the connection is
  unencrypted, acceptable on localhost only.
- **Not reproducible by `make`:** unlike the rest of the repo, the report is built by hand;
  screenshots and the TMDL files are the evidence.
