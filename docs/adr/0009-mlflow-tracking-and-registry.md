# ADR-0009: MLflow for experiment tracking and the model registry

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

The SECOM experiment (ADR-0008) fits 17 configurations with walk-forward CV, scores a
holdout, and produces a model that Grafana's scores come from. Without tracking, the only
record of a run is the generated report, overwritten each time: no way to compare today's
run with last week's, or to say which model produced the scores in the database.

FabEye, the sister project, serves its model from a file baked into an image. WaferLens adds
the part FabEye lacks: run history and a registry with versions.

## Options considered

1. **Files only:** the Markdown report plus a pickled model in the repo. No history, models
   in git.
2. **MLflow:** open source, the most common tracking server in job ads; params, metrics and
   artifacts per run, nested runs for a model search, and a registry with numbered versions.
3. **Weights & Biases / Neptune:** hosted, polished UIs; an account and an external service
   for a portfolio project that should run with `make up`.
4. **DVC experiments:** git-centred and good for data versioning, weaker as a registry
   others can query.

## Decision

MLflow 3, as a `mlflow` service in docker-compose (SQLite backend and artifacts on a volume,
artifacts uploaded through the server), with the Python client in the package. One parent
run per experiment, one nested run per configuration with its CV metrics, holdout and
leakage-gap metrics on the parent, and the chosen pipeline registered as
`secom-fail-predictor`. The version number goes into `secom_model_versions` and onto every
score row, so Grafana's numbers trace back to an MLflow run.

## Consequences

- **Reproducible lineage:** score row → model version → MLflow run → params, metrics,
  pipeline artifact; a test loads the registered model back and predicts with it.
- **Tests need no server:** the tracking URI is configurable, and tests use a temporary
  SQLite store (MLflow 3 no longer accepts plain `./mlruns` directories).
- **Serialisation:** models are saved with cloudpickle, not MLflow 3's default skops,
  because the pipeline contains this package's own transformers; loading needs the
  `waferlens` package installed, which is true wherever the pipeline runs.
- **Telemetry off:** MLflow's usage telemetry is disabled in the client and the server.
- **Not production-grade:** SQLite and a local volume, no auth; a shared deployment would use
  Postgres and object storage.
