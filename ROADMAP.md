# WaferLens 2.0 — Roadmap

**One question the whole system answers:**
> Yield dropped — which tool/chamber caused it, how early could we have known, and what does it look like on the wafer?

Every phase ends with something shippable and a measurable result for the README/CV.

## Target stack

| Layer | Choice |
|---|---|
| Storage | Postgres 16 + TimescaleDB |
| Transforms | dbt (staging → intermediate → marts, star schema) |
| Orchestration | Dagster |
| Live monitoring | Grafana (provisioned as code, alerting) |
| BI reporting | Power BI (PBIP/TMDL in git) — *last phase, Windows side* |
| ML | PyTorch, scikit-learn, MLflow |
| Streaming (stretch) | Redpanda (Kafka API) |
| Tooling | uv, ruff, pyright, pytest + hypothesis, pre-commit, Docker Compose, GitHub Actions, Makefile |

## Milestones

| Milestone | After phase | Meaning |
|---|---|---|
| **M1 — CV-ready** | 4 | Data platform + SPC/root-cause + Grafana. Safe to put on CV. |
| **M2 — Standout** | 5 | Integrates FabEye + SECOM process ML. |
| **M3 — Complete** | 8 | Streaming, Power BI, write-up, video. |

---

## Phase 0 — Reset & foundation (~3 days)

Goal: clean repo where every later phase plugs into CI, Docker, and `make`.

- [x] Archive v1 on a `waferlens-v1-archive` branch (same pattern as `schemaforge-archive`)
- [x] Clear `main`; keep LICENSE, move v1 notes/crib files out of the repo (`~/waferlens-v1-notes/`)
- [x] `pyproject.toml` with uv; `dev` dependency group (dbt / ml groups added in phases 2 / 5)
- [x] ruff + pyright + pre-commit configured
- [x] Package layout: `src/waferlens/{db,simulate,ingest,spc,rootcause,ml,stream,orchestration}`, `dbt/`, `grafana/`, `powerbi/`, `docs/adr/`
- [x] `docker-compose.yml`: TimescaleDB + Grafana (datasource provisioned, no dashboards yet) with healthchecks
- [x] `Makefile`: `install`, `up`, `down`, `reset`, `psql`, `lint`, `typecheck`, `test`, `check` (`seed` / `dbt` / `demo` land in phases 1 / 2 / 8)
- [x] GitHub Actions: lint + typecheck + tests (against a TimescaleDB service container) — green on PR #1 and `main`
- [x] ADR template
- [x] ADR-001 "Postgres/TimescaleDB over SQLite/DuckDB"
- [x] Rewrite `CLAUDE.md` for v2
- [x] README stub with the one-question pitch + architecture diagram

**Done when:** `make up && make test` passes locally and in CI on an empty project.

---

## Phase 1 — Data model, simulator, SECOM (~1.5 weeks)

Goal: a realistic fab data model with genealogy, a simulator with **ground truth**, and SECOM loaded (WM-811K stays in FabEye).

### Data scale

| Profile | Lots | Wafers | Simulated time | Rows (approx.) | Used for |
|---|---|---|---|---|---|
| `dev` | 40 | 1,000 | 30 days | ~170k | Unit tests, CI (< 1 s) |
| **`demo`** (default) | **1,000** | **25,000** | **6 months** | **4.74M** | All README results, Grafana, Power BI, FabEye scoring |
| `stress` | 5,000 | 125,000 | 12 months | 24.3M | Performance write-up only (`docs/perf.md`) |

`demo` (seed 42, measured): tool sensor readings 2.96M · inline metrology 985k (5 of 25 wafers per lot, 12 steps, 22 parameters, 9 sites) · genealogy 740k · 24,090 wafer maps (one array per wafer) · 40 injected excursions · mean yield 87.1%. Generates in ~5–20 s, ~1 GB peak memory. Details in `docs/simulator.md`.

### Schema (Alembic) — see `docs/schema.md`
- [x] `products`, `technology_nodes`, `routes`, `route_steps` (step sequence per product)
- [x] `tools`, `chambers` (tool → chambers), `recipes` (versioned), plus `tool_types`, `parameters`, `sort_bins`
- [x] `lots`, `wafers`, `lot_events` (split / merge / hold / release)
- [x] `wafer_step_history` (wafer × step × pass → lot, chamber, recipe, track-in/out time) — the genealogy table
- [x] `tool_sensor_readings` (every wafer × step: chamber sensor summaries) as a **TimescaleDB hypertable**
- [x] `metrology_measurements` (sampled wafers, multi-site: site_x, site_y) as a **TimescaleDB hypertable**
- [x] `metrology_plans` (which steps/parameters get measured, wafers per lot, sites, LSL/target/USL)
- [x] `wafer_maps` (one row per wafer: die bin grid as a Postgres array, FabEye-compatible 0/1/2 encoding) — not one row per die
- [x] `wafer_bin_summary` (wafer × bin → die count) + `wafer_yield` view
- [x] `excursions_ground_truth` (simulator log: type, chamber/recipe, parameter, pattern, start, end, magnitude) + `simulation_runs` provenance
- [x] Constraints: FKs, uniques, check constraints (statuses, slots, spec order, site on wafer, 2-D maps, excursion root cause), indexes for genealogy and time-series queries — each one tested
- [x] ADR-002 "Genealogy model and why chamber-level history matters"
- [x] ADR-003 "Wafer maps as arrays, not die rows"

### Simulator — see `docs/simulator.md`
- [x] Config-driven (`config/fab.yaml`, validated with pydantic): products, routes, tools/chambers, sensors, metrology specs
- [x] Wafers routed through chambers (slot-based dispatch per tool) with timestamps, queue times, holds, splits, litho rework, scrap
- [x] Correlated parameters (e.g. overlay x ↔ y, CD ↔ sheet resistance) via Cholesky factor of a correlation matrix
- [x] Excursion injectors: step shift, linear drift, chamber offset, recipe change, spatial defect patterns (center, donut, edge ring, edge loc, loc, scratch, random)
- [x] Die-level sort bins from a Poisson defect model + spatial patterns (no hard yield clipping)
- [x] Every injected excursion logged to `excursions_ground_truth`
- [x] Deterministic by seed (independent random stream per stage); `--profile dev|demo|stress`
- [x] Fully vectorised numpy (loop over 30 steps only); `demo` generates in ~5–20 s
- [x] Metrology sampling plan + 9-site measurements with radial within-wafer profile
- [x] 40 excursions spread over 6 months for `demo`, mixed types and chambers
- [x] Writes Parquet + manifest; loader is a separate module (keep simulate/ingest decoupled)
- [x] Tests: output matches every table, PK/FK and CHECK rules hold (also property-tested over random seeds and sizes), injected shifts are measurable, recipe windows and spatial yield loss verified

### Ingest & data quality
- [x] pandera contracts per table, generated from the ORM metadata, plus cross-table rules (metrology after its step, sensor chamber = genealogy chamber, wafer map grid and bins)
- [x] Bulk load via `COPY` with foreign keys dropped and re-added in the same transaction; benchmark vs ORM / Core in `docs/perf.md` (ORM 1.8k rows/s → COPY 20.7k rows/s, 11x)
- [x] Idempotent, atomic re-runs (truncate-and-load in one transaction; a failed load leaves the old data)
- [x] `wafer_bin_summary` derived from `wafer_maps` in SQL (`unnest`), with a test that they always agree (ADR-003)
- [x] `make seed` = migrate + simulate + load (demo: ~2 min, 4.83M rows)

### Real datasets
- [x] UCI SECOM downloader (SHA-256 pinned) + loader → `secom_runs` / `secom_readings` (590 signals in long format + pass/fail; `make secom`)
- [x] Data card `docs/data/secom.md` (source, license, quirks, missingness, fail-rate drift 22% → 3%)

### Tests
- [x] Schema/constraint tests, simulator property tests (hypothesis), loader round-trip tests

### Stress & query performance — see `docs/perf.md`
- [x] `make seed PROFILE=stress` works end to end (10 min, 24.3M rows, 4.2 GB; peak 4.2 GB RAM documented as the limit)
- [x] Key workload queries in `sql/queries/` + `make explain` (EXPLAIN ANALYZE, median of 3, blocks, chunks read)
- [x] Plan-driven fix: `wafer_yield` materialized (migration 0003), reporting queries 2–2.6x faster on stress
- [x] Measured and rejected: `(parameter_id, time)` sensor index (2x faster, +450 MB, +15 s per load) → continuous aggregate in phase 4

**Done when:** `make seed` (demo profile) loads ~6M rows with genealogy, wafer maps and ground truth; SECOM loads; `make seed PROFILE=stress` works and `EXPLAIN ANALYZE` of key queries plus load times are noted in `docs/perf.md`.

**CV line:** *Simulated 6 months of fab operation (25,000 wafers, 1,000 lots, 4.8M rows, 40 injected excursions) on a chamber-level genealogy schema in TimescaleDB, bulk-loaded via COPY with contract checks, stress-tested to 24M rows and tuned from EXPLAIN ANALYZE.*

**Status: phase 1 complete (2026-10-06).**

---

## Phase 2 — dbt + Dagster (~1 week)

Goal: tested transformation layer and orchestrated, observable pipeline. **Design marts as a star schema now — Power BI consumes them in Phase 7.**

### dbt — see `docs/dbt.md` (generated) and ADR-004
- [x] Sources + freshness check (on `simulation_runs.created_at`: has the pipeline loaded recently?)
- [x] Staging models (23 views: renames, typing, derived durations)
- [x] Intermediate: `int_wafer_route_history`, `int_measurement_with_context`
- [x] Marts — facts: `fct_measurements` (3.07M rows), `fct_wafer_yield`, `fct_die_bins`, `fct_wafer_steps` (added: genealogy fact for commonality + cycle time); `fct_spc_alarms` moved to phase 3, when alarms exist
- [x] Marts — dims: `dim_date`, `dim_tool`, `dim_chamber`, `dim_product`, `dim_node`, `dim_recipe`, `dim_lot` + `dim_wafer`, `dim_route_step`, `dim_parameter`, `dim_sort_bin`
- [x] Incremental model for `fct_measurements` (delete+insert, 3-day look-back, pre-hook clears rows from an earlier load) — verified on rerun and on reload
- [x] Tests: 82 data tests (unique/not_null/relationships/accepted_values/ranges + 4 singular business-rule tests) and 3 dbt unit tests; `dbt build` in CI on a fresh dev fab
- [x] `dbt docs` generated; lineage as a generated Mermaid graph in `docs/dbt.md` (`make dbt-docs`) instead of a screenshot
- [x] Window functions (`lag` queue time, `row_number` final pass, `lead` recipe validity, bin share) and a recursive CTE (lot split lineage)
- [x] ADR-004 "dbt for transformations, marts as a star schema"

### Dagster
- [ ] Assets: simulate → load → dbt models → SPC → root cause
- [ ] dbt assets via `dagster-dbt`
- [ ] Schedule (daily) + sensor (new Parquet files)
- [ ] Asset checks wired to data contracts
- [ ] Lineage graph screenshot in README

**Done when:** one `dagster` materialization rebuilds everything end-to-end; `dbt test` green in CI.

**CV line:** *Built a star-schema analytics layer in dbt orchestrated as Dagster assets with data-quality checks.*

---

## Phase 3 — SPC & root-cause engine (~1.5 weeks)

Goal: detection that's **measured against ground truth**, not just "flags exist".

### SPC
- [ ] Phase I: estimate limits from an in-control baseline window; persist in `control_limits` (versioned)
- [ ] Phase II: monitor new data against frozen limits
- [ ] Shewhart + Western Electric rules 1–4 (vectorised)
- [ ] EWMA chart
- [ ] CUSUM chart
- [ ] Hotelling T² for correlated parameter groups
- [ ] Limits per tool **and** per chamber
- [ ] Unique constraint on alarms (idempotent reruns)
- [ ] hypothesis property tests (e.g. in-control data ⇒ false-alarm rate ≈ theoretical)

### Benchmarking
- [ ] ARL harness: ARL₀ (false alarms) and ARL₁ (detection delay) for shift sizes 0.25σ–3σ
- [ ] Results table + plot: Shewhart vs WE rules vs EWMA vs CUSUM vs T²
- [ ] Detection delay vs `excursions_ground_truth` on simulated data
- [ ] ADR-005 "Why EWMA/CUSUM in addition to Western Electric"

### Root cause
- [ ] `fct_spc_alarms` mart (moved from phase 2) feeding Grafana and Power BI
- [ ] Commonality analysis in SQL: for low-yield wafers, rank tool/chamber/recipe by over-representation (e.g. chi-square / Fisher / lift)
- [ ] Time-window aware (only chambers used in the excursion window)
- [ ] Evaluate: root-cause chamber in top-1 / top-3 for N injected excursions
- [ ] Excursion impact: dies lost, wafers affected

**Done when:** README has an ARL table and a root-cause accuracy number.

**CV lines:** *EWMA detected 0.5σ drift in N wafers vs M for Shewhart (ARL benchmark).* / *Commonality analysis ranked the true root-cause chamber top-1 in X/Y injected excursions.*

---

## Phase 4 — Grafana live monitoring (~4 days) → **M1: CV-ready**

- [ ] Datasource + dashboards provisioned from git (no click-ops)
- [ ] Dashboard 1 — **Fab overview**: WIP, yield trend, open alarms, top offending chambers
- [ ] Dashboard 2 — **SPC control charts**: variables for tool/chamber/parameter; frozen limits as bands; EWMA/T² panels
- [ ] Dashboard 3 — **Excursion review**: annotations for alarm time vs ground-truth start (detection delay visible)
- [ ] TimescaleDB `time_bucket` / continuous aggregates powering heavy panels
- [ ] Alert rules (e.g. T² beyond limit, chamber yield drop) → contact point (email/webhook)
- [ ] Screenshots + short GIF in README

**Done when:** `make up` gives a working Grafana at `localhost:3000` with all dashboards and a firing demo alert.

**M1 checklist:** README results tables filled · CI green · architecture diagram · 3–4 ADRs · CV bullets drafted.

---

## Phase 5 — FabEye integration + process ML (~1.5 weeks) → **M2: Standout**

Wafer-map classification already lives in [FabEye](https://github.com/anson10/FabEye) (WM-811K CNN/GNN/RF, lot-disjoint evaluation, conformal prediction, ONNX + FastAPI serving). **Do not rebuild it here.** WaferLens consumes FabEye as a service and adds what FabEye's README lists as missing: timestamps and process context.

### 5a — FabEye as the wafer-map classifier
- [ ] Add FabEye image as a `fabeye` service in docker-compose (API key via env)
- [ ] Simulator wafer maps exported in FabEye's format (0 = off-wafer, 1 = good, 2 = fail)
- [ ] Dagster asset: batch-score new wafers via `POST /predict/batch` → `fct_wafer_pattern` (pattern, confidence, conformal set, accept/review flag, model version)
- [ ] Domain-shift check: score simulated maps against **injected ground-truth patterns** → accuracy, coverage, accept rate vs FabEye's numbers on real lots (report honestly, even if it drops)
- [ ] Root cause using pattern: pattern × chamber commonality (e.g. edge-ring ↔ CMP chamber) → does adding pattern improve top-1 root-cause accuracy from Phase 3?
- [ ] Time-ordered evaluation FabEye couldn't do: detection delay of a pattern-based alarm vs SPC alarms on the same excursion
- [ ] Grafana: Prometheus datasource scraping FabEye `/metrics` → serving latency, prediction volume by pattern, review-queue rate
- [ ] Cross-link READMEs (WaferLens ↔ FabEye)

### 5b — SECOM: process-sensor fail prediction (new skill area: tabular ML)
- [ ] Data card: 591 sensors, heavy missingness, ~6.6% fails, timestamps
- [ ] **Time-ordered** train/test split (SECOM has timestamps) vs random split → leakage gap measured
- [ ] Missing-value + feature-selection strategy documented (drop/impute, variance, correlation, L1 / mutual information)
- [ ] Baselines: logistic regression → gradient boosting (LightGBM/XGBoost); imbalance handling
- [ ] Metrics: PR-AUC, recall at fixed false-alarm rate (not accuracy)
- [ ] SHAP / permutation importance → which sensors drive fails
- [ ] Scores written back to DB → visible in Grafana

### MLOps (new vs FabEye)
- [ ] MLflow tracking + model registry in docker-compose (SECOM runs)
- [ ] Dagster assets for SECOM training / batch scoring
- [ ] ADR-006 "Consume FabEye as a service instead of retraining"
- [ ] ADR-007 "SECOM evaluation: time split and PR-AUC"

**Done when:** README reports FabEye's accuracy on simulated maps with ground truth, root-cause accuracy with vs without pattern, and SECOM PR-AUC on a time split.

**CV lines:** *Integrated a separately deployed wafer-map classifier (FabEye) into the fab pipeline; pattern signals raised root-cause top-1 accuracy from X to Y.* / *Predicted wafer fails from 591 process sensors (SECOM) with PR-AUC X on a time-ordered split, tracked in MLflow.*

---

## Phase 6 — Streaming / real-time SPC (stretch, ~1 week)

- [ ] Redpanda in docker-compose
- [ ] Simulator "tool agents" publish measurement events (schema-versioned JSON/Avro)
- [ ] Consumer: online SPC (EWMA/CUSUM state per chamber) → alarms to DB
- [ ] Exactly-once-ish handling: idempotent writes, consumer offsets
- [ ] Grafana live panels with short refresh; end-to-end latency measured
- [ ] Demo script: start stream → inject drift → alarm appears in Grafana

**CV line:** *Real-time SPC on streaming tool data (Redpanda → TimescaleDB), alarm latency < N s.*

---

## Phase 7 — Power BI reporting (Windows side, ~1–1.5 weeks)

Setup across WSL ↔ Windows:
- [ ] Postgres container port reachable from Windows (`localhost:5432`); test with Power BI Desktop's PostgreSQL connector (Npgsql)
- [ ] Read-only DB role `powerbi_reader` limited to the marts schema
- [ ] Enable PBIP / TMDL save format; project lives in `powerbi/` in the repo
- [ ] `.gitignore` for Power BI cache files (`.pbi/cache.abf`, `localSettings.json`)

Model:
- [ ] Import dbt star schema (facts + dims), relationships single-direction, `dim_date` marked as date table
- [ ] DAX measures: die-weighted yield, yield Δ WoW/MoM, dies lost, alarm rate, mean detection delay
- [ ] Display folders + measure descriptions (reads like a real semantic model)

Report pages:
- [ ] Executive yield summary (KPIs, trend, by product/node)
- [ ] Yield Pareto (loss by bin / pattern / product)
- [ ] Commonality / root cause (chamber ranking, drillthrough)
- [ ] Excursion report (impact, detection delay, cost)
- [ ] Drillthrough lot → wafer → route history
- [ ] Bookmarks / tooltips pages
- [ ] Row-level security role (e.g. per product line)

Delivery:
- [ ] Screenshots + 1–2 min video walkthrough
- [ ] `powerbi/README.md` explaining model design + DAX highlights
- [ ] (Optional, in parallel) PL-300 certification

**CV line:** *Built a Power BI semantic model on a dbt star schema (DAX, RLS, drillthrough), version-controlled as PBIP.*

---

## Phase 8 — Launch (~3–4 days) → **M3: Complete**

- [ ] README: pitch → architecture diagram → results tables (ARL, root-cause accuracy, F1, PR-AUC, latency) → screenshots → quickstart
- [ ] "Excursion story" demo: CMP chamber drift → alarm → commonality → wafer-map pattern → yield impact
- [ ] 2–3 min demo video (link at top of README)
- [ ] Technical write-up (blog / LinkedIn article): what worked, what didn't, numbers
- [ ] Short German summary section in README (*Kurzbeschreibung*)
- [ ] All ADRs complete; `docs/` index
- [ ] Final CV bullets + LinkedIn project entry
- [ ] Repo hygiene: no crib files, no scratch scripts, clean commit history, pinned versions, tagged `v2.0.0` release

---

## Rules for the whole project

- Every claim in the README is reproducible by a `make` target.
- Every phase ends green in CI before the next starts.
- No tool goes in that can't be justified in two sentences (write the ADR).
- Commits: `type(scope): subject` + 3–5 bullets, one feature branch per checklist group.
