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

### Dagster — see `docs/pipeline.md` (generated) and ADR-005
- [x] Assets: `simulated_fab` → 24 warehouse tables (keys = dbt source names) → 40 dbt models; SPC and root-cause assets join in phase 3
- [x] dbt assets via `dagster-dbt` (models grouped by layer; 78 dbt tests become asset checks)
- [x] Schedule (`nightly_rebuild`, 03:00 UTC) + sensor (`new_parquet_drop`, ignores drops the pipeline wrote itself)
- [x] Data contracts as a **blocking** asset check on the Parquet drop (tested: a failed check stops the load)
- [x] Lineage as a generated Mermaid graph in `docs/pipeline.md` (`make pipeline-docs`) instead of a screenshot
- [x] Jobs `full_rebuild` and `ingest`; `make pipeline` runs `full_rebuild` headless, `make dagster` opens the UI
- [x] ADR-005 "Dagster for orchestration, modelled as assets"

**Done when:** one `dagster` materialization rebuilds everything end-to-end; `dbt test` green in CI.

**CV line:** *Built a star-schema analytics layer in dbt orchestrated as Dagster assets with data-quality checks.*

---

## Phase 3 — SPC & root-cause engine (~1.5 weeks)

Goal: detection that's **measured against ground truth**, not just "flags exist".

### SPC — see `docs/spc.md`
- [x] Phase I: robust limits (median, moving range, 4σ trim) from each series' first 30 days; persisted in `spc_control_limits`, versioned
- [x] Phase II: monitor every later point against frozen limits (reruns reuse them; `--relearn` writes a new version)
- [x] Shewhart + Western Electric rules 1–4 (vectorised)
- [x] EWMA chart (λ 0.2, L 3, exact limits)
- [x] CUSUM chart (k 0.5, h 5, reset after signal)
- [x] Hotelling T² for correlated parameter groups (all metrology parameters of a step, per chamber)
- [x] Limits per tool **and** per chamber (900 series on demo)
- [x] Unique constraint on alarms (idempotent reruns, tested)
- [x] hypothesis property tests: in-control false-alarm rates match theory (WE1 0.27%, WE4 0.78%, CUSUM ~0.22%); measured on demo too
- [x] `spc_results` Dagster asset between the dbt measurement mart and `fct_spc_alarms`

### Benchmarking — see `docs/spc_benchmark.md` (generated) and ADR-006
- [x] ARL harness: ARL₀ and ARL₁ for shifts 0–3σ (2,000 runs each), batch charts proven identical to the 1-D ones, within 3% of published tables
- [x] Results table + plot: Shewhart vs WE rules vs EWMA vs CUSUM vs T² (`docs/img/arl.svg`, false-alarm cost in the legend)
- [x] Detection delay vs `excursions_ground_truth`: `fct_excursion_detection` dbt mart with a placebo window as the chance baseline, chamber vs tool scope
- [x] ADR-006 "EWMA and CUSUM alongside Western Electric, limits per chamber"
- [x] Fixes the benchmark forced: F-based Phase II T² limit for estimated parameters (chi-square limit false-alarmed every ~5 points)

### Root cause
- [x] `fct_spc_alarms` mart (moved from phase 2) feeding Grafana and Power BI, + `spc_charts` dbt seed
- [x] Commonality analysis in SQL (`rootcause/commonality.py`): low yield = below the product's own normal; chambers and recipe versions ranked by 2×2 chi-square and lift; ad-hoc CLI for any window
- [x] Time-window aware (only chambers and recipes used inside the window; planted-data tests incl. a product-confounding trap)
- [x] Evaluate: true cause top-1 for 23/32 excursions that cost yield (72%), top-3 75%, random 0.8% (`fct_root_cause_eval`, `docs/root_cause.md`)
- [x] Excursion impact vs same-product, same-window controls: wafers affected, yield delta, dies lost (`fct_excursion_impact`)
- [x] SPC × commonality coverage: 35/40 excursions found by at least one method

**Done when:** README has an ARL table and a root-cause accuracy number.

**CV lines:** *EWMA and CUSUM detect a 0.5σ shift ~4× sooner than Shewhart (42/38 vs 156 points, ARL benchmark within 3% of published tables); on the fab's own ground truth, a median 8 wafers vs 33.* / *Commonality analysis in SQL ranked the true root-cause chamber or recipe first for 72% of yield-impacting excursions (random: 0.8%).*

**Status: phase 3 complete (2026-10-07).** / *Commonality analysis ranked the true root-cause chamber top-1 in X/Y injected excursions.*

---

## Phase 4 — Grafana live monitoring (~4 days) → **M1: CV-ready**

- [x] Datasource + dashboards provisioned from git (no click-ops); dashboards generated by `src/waferlens/dashboards/build.py`, drift-tested
- [x] Read-only `grafana_reader` role (migration 0006 + dbt `+grants`), tested to be unable to write
- [x] Dashboard 1 — **Fab overview**: WIP, yield trend, alarms per day, top offending chambers, excursions linking to their review
- [x] Dashboard 2 — **SPC control charts**: variables for tool/chamber/parameter; frozen limits; EWMA (SQL `ewma()` aggregate, matches Python) and T² panels
- [x] Dashboard 3 — **Excursion review**: annotations for first alarm per chart vs ground-truth window (detection delay visible), impact, commonality suspects
- [x] TimescaleDB continuous aggregate `sensor_daily` powering the daily-mean panel (303 → 3.1 ms, docs/perf.md)
- [x] Alert rules (EWMA burst on a chamber, chamber yield drop) → webhook contact point; demo alert fires
- [x] Every dashboard and alert query runs as `grafana_reader` in an integration test
- [x] ADR-007 "Grafana for live monitoring, dashboards generated as code"
- [x] Screenshots in README (`make screenshots`, Grafana image renderer)
- [ ] Short GIF in README — skipped for now; the static screenshots carry the story

**Done when:** `make up` gives a working Grafana at `localhost:3000` with all dashboards and a firing demo alert.

**M1 checklist:** README results tables filled · CI green · architecture diagram · 3–4 ADRs · CV bullets drafted.

---

## Phase 5 — FabEye integration + process ML (~1.5 weeks) → **M2: Standout**

Wafer-map classification already lives in [FabEye](https://github.com/anson10/FabEye) (WM-811K CNN/GNN/RF, lot-disjoint evaluation, conformal prediction, ONNX + FastAPI serving). **Do not rebuild it here.** WaferLens consumes FabEye as a service and adds what FabEye's README lists as missing: timestamps and process context.

### 5a — FabEye as the wafer-map classifier — see `docs/fabeye_eval.md` (generated) and ADR-010
- [x] Add FabEye as a `fabeye` service in docker-compose, built from its GitHub repo at a pinned commit (API key via env)
- [x] Simulator logs per-wafer pattern ground truth (`wafer_pattern_truth`); maps sent in FabEye's format (0 = off-wafer, 1 = good, 2 = fail)
- [x] Dagster asset `wafer_patterns`: batch-score every sorted wafer via `POST /predict/batch` → `fct_wafer_pattern` (pattern, confidence, conformal set, accept/review flag, model version)
- [x] Domain-shift check against **injected ground-truth patterns**: macro-F1 0.909 (0.858 on real lots), but Random set coverage 52% vs ~90% (strong random fields called Near-full); 450 empty prediction sets
- [x] Root cause using pattern: pattern-led commonality ranks the true chamber 1st for 13/13 spatial excursions (yield: 11/13); picking the pattern from the time window fails (top-1 72% → 47%), reported as is
- [x] Time-ordered evaluation FabEye couldn't do: pattern alarm (`fct_pattern_alarms`) caught 13/13 spatial excursions vs SPC 0/13, median 52 h after start (sort lag 45 h); placebo windows alarmed 4/13 (overlap)
- [x] Grafana: Prometheus datasource scraping FabEye `/metrics` → "FabEye serving" dashboard (volume by pattern, review queue, latency, errors)
- [x] Cross-link READMEs (WaferLens ↔ FabEye)

### 5b — SECOM: process-sensor fail prediction (new skill area: tabular ML) — see `docs/secom_model.md` (generated) and ADR-008
- [x] Data card: 590 sensors (the source says 591), heavy missingness, ~6.6% fails, timestamps (`docs/data/secom.md`, phase 1)
- [x] **Time-ordered** train/test split (last 30% holdout, scored once) vs 20 random splits → leakage gap measured (random split 2.7x higher)
- [x] Missing-value + feature-selection strategy compared in walk-forward CV (median, median + was-missing indicators, LightGBM native; none, correlation pruning, L1, mutual information)
- [x] Baselines: logistic regression → LightGBM; imbalance via balanced class weights
- [x] Metrics: PR-AUC with bootstrap CI and chance level, recall at 5% / 10% false-alarm rate (forward threshold vs hindsight)
- [x] TreeSHAP (LightGBM `pred_contrib`) / coefficient importance → which sensors drive fails (sensor 60 first in both models)
- [x] Scores written back to DB (`secom_scores`, `secom_sensor_importance`, `secom_model_versions`) → SECOM dashboard in Grafana

### MLOps (new vs FabEye)
- [x] MLflow tracking + model registry in docker-compose (nested run per configuration, `secom-fail-predictor` versions)
- [x] Dagster asset `secom_model` (train, register, score, write)
- [x] ADR-008 "SECOM evaluation: time-ordered split, walk-forward selection, PR-AUC"
- [x] ADR-009 "MLflow for experiment tracking and the model registry"
- [x] ADR-010 "Consume FabEye as a service instead of retraining"

**Done when:** README reports FabEye's accuracy on simulated maps with ground truth, root-cause accuracy with vs without pattern, and SECOM PR-AUC on a time split.

**CV lines:** *Integrated a separately deployed wafer-map classifier (FabEye) into the fab pipeline; pattern signals raised root-cause top-1 accuracy from X to Y.* / *Predicted wafer fails from 591 process sensors (SECOM) with PR-AUC X on a time-ordered split, tracked in MLflow.*

---

## Phase 6 — Streaming / real-time SPC (stretch, ~1 week) — ADR-012, `make stream-demo`

- [x] Redpanda in docker-compose (opt-in `stream` profile, 512 MB)
- [x] Tool agents replay the simulator's sensor readings as events (versioned JSON `waferlens.sensor_reading/v1`, keyed by chamber)
- [x] Consumer: online EWMA/CUSUM per chamber x sensor on the frozen limits → `stream_alarms`; equals the batch engine's alarms exactly (tested, with a restart)
- [x] Exactly once: alarms, chart state and offsets commit in one Postgres transaction; replays skipped; tested
- [x] Grafana "Real-time SPC" dashboard (5 s refresh); latency p50 ~270 ms, p95 ~515 ms (monotonic clock: WSL2's wall clock steps ~1 s)
- [x] `make stream-demo`: a day of events, +2σ drift injected, caught by CUSUM after 3 points

**CV line:** *Real-time SPC on streaming tool data (Redpanda → TimescaleDB), alarm latency < N s.*

---

## Phase 7 — Power BI reporting (Windows side, ~1–1.5 weeks) — ADR-011

Setup across WSL ↔ Windows:
- [x] Postgres container port reachable from Windows (`localhost:5432`, `Test-NetConnection` OK); [x] connect with Power BI Desktop's PostgreSQL connector
- [x] Read-only DB role `powerbi_reader` limited to the marts schema (migration 0011, dbt grants, tested; `make powerbi-check`)
- [x] Enable PBIP / TMDL save format; project lives in `powerbi/` in the repo
- [x] `.gitignore` for Power BI cache files (`.pbi/cache.abf`, `localSettings.json`, `*.pbix`)
- [x] `dim_excursion` mart added, so the excursion-grain facts share one dimension
- [x] ADR-011 "Power BI in Import mode on the dbt marts, saved as PBIP"

Model:
- [x] Import dbt star schema (facts + dims), relationships single-direction, `dim_date` marked as date table
- [x] DAX measures: die-weighted yield, yield Δ WoW/MoM, dies lost, alarm rate, mean detection delay
- [x] Display folders + measure descriptions (reads like a real semantic model)

Report pages:
- [x] Executive yield summary (KPIs, trend, by product/node)
- [x] Yield Pareto (loss by bin / pattern / product)
- [x] Commonality / root cause (chamber ranking, drillthrough)
- [x] Excursion report (impact, detection delay, cost)
- [x] Process control (alarms by tool type and chart family, alarm density per chamber, FabEye review load)
- [x] Drillthrough to wafer → route history, bins, FabEye pattern
- [x] Tooltip page (chamber, excursion-window aware); [x] bookmarks (two excursion stories + reset)
- [x] Performance Analyzer pass, slowest visual noted in `powerbi/README.md`
- [x] Row-level security roles per product line

Delivery:
- [x] Screenshots (`powerbi/images/`, in the README)
- [x] `powerbi/README.md` explaining model design + DAX highlights

**CV line:** *Built a Power BI semantic model on a dbt star schema (DAX, RLS, drillthrough), version-controlled as PBIP.*

---

## Phase 8 — Launch (~3–4 days) → **M3: Complete**

- [x] README: pitch → architecture diagram → results tables (ARL, root-cause accuracy, F1, PR-AUC, latency) → screenshots → quickstart
- [x] "Excursion story" demo (`make story` → `docs/excursion_story.md`): a drift (alarm → commonality → spared wafers → cost), a spatial pattern SPC can't see (FabEye → pattern alarm → pattern-led commonality), and commonality's miss
- [ ] 2–3 min demo video (link at top of README)
- [ ] Technical write-up (blog / LinkedIn article): what worked, what didn't, numbers
- [x] Short German summary section in README (*Kurzbeschreibung*)
- [x] All ADRs complete; `docs/` index
- [ ] Final CV bullets + LinkedIn project entry
- [ ] Repo hygiene: no crib files, no scratch scripts, clean commit history, pinned versions, tagged `v2.0.0` release

---

## Rules for the whole project

- Every claim in the README is reproducible by a `make` target.
- Every phase ends green in CI before the next starts.
- No tool goes in that can't be justified in two sentences (write the ADR).
- Commits: `type(scope): subject` + 3–5 bullets, one feature branch per checklist group.
