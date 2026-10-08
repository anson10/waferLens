# Docs

Every report here is generated from the warehouse by a `make` target, so the numbers in it can
be reproduced; the rest describe how a part works.

## Results

| Doc | What it answers | Regenerate |
|---|---|---|
| [Excursion stories](excursion_story.md) | Three excursions end to end: alarm, suspects, wafers, cost | `make story` |
| [SPC benchmark](spc_benchmark.md) | How early each chart catches a shift, simulated and on the fab's ground truth | `make spc-report` |
| [Root cause](root_cause.md) | How often commonality names the true cause, and how SPC and commonality cover each other | `make rootcause-report` |
| [FabEye on simulated maps](fabeye_eval.md) | Where FabEye's guarantees break on a different fab | `make fabeye-report` |
| [SECOM model](secom_model.md) | Fail prediction on real fab data, time-ordered against a random split | `make secom-model` |
| [Performance](perf.md) | Load times, query plans, TimescaleDB continuous aggregates (measured, written by hand) | `make bench-load`, `make explain` |

## How it works

| Doc | Contents |
|---|---|
| [Schema](schema.md) | Tables, keys and hypertables of the warehouse |
| [Simulator](simulator.md) | The simulated fab, its excursion physics and the ground-truth log |
| [dbt models](dbt.md) | Staging, intermediate and mart models with their tests (generated: `make dbt-docs`) |
| [Pipeline](pipeline.md) | The Dagster assets and their dependencies (generated: `make pipeline-docs`) |
| [SPC engine](spc.md) | Phase I limits, the charts and rules, how alarms are stored |
| [SECOM data card](data/secom.md) | The UCI SECOM dataset and its drifting fail rate |
| [Power BI](../powerbi/README.md) | The semantic model, DAX highlights, row-level security |

## Decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-postgres-timescaledb.md) | PostgreSQL + TimescaleDB as the single datastore |
| [0002](adr/0002-chamber-level-genealogy.md) | Chamber-level wafer genealogy |
| [0003](adr/0003-wafer-maps-as-arrays.md) | Wafer maps as 2-D arrays, not one row per die |
| [0004](adr/0004-dbt-star-schema-marts.md) | dbt for transformations, marts as a star schema |
| [0005](adr/0005-dagster-orchestration.md) | Dagster for orchestration, modelled as assets |
| [0006](adr/0006-ewma-cusum-alongside-western-electric.md) | EWMA and CUSUM alongside Western Electric, limits per chamber |
| [0007](adr/0007-grafana-dashboards-as-code.md) | Grafana for live monitoring, dashboards generated as code |
| [0008](adr/0008-secom-time-split-and-pr-auc.md) | SECOM evaluation: time-ordered split, walk-forward selection, PR-AUC |
| [0009](adr/0009-mlflow-tracking-and-registry.md) | MLflow for experiment tracking and the model registry |
| [0010](adr/0010-consume-fabeye-as-a-service.md) | Consume FabEye as a service instead of retraining |
| [0011](adr/0011-power-bi-import-on-marts-pbip.md) | Power BI in Import mode on the dbt marts, saved as PBIP |
| [0012](adr/0012-real-time-spc-on-redpanda.md) | Real-time SPC on Redpanda, exactly once through Postgres |

New decisions start from the [template](adr/0000-template.md).
