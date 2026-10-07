"""Writes the latest SECOM experiment to the database for Grafana: the model version and its
holdout result, one out-of-sample score per run, and sensor importance.

The three tables hold the latest model only (MLflow keeps the history), replaced in one
transaction so a dashboard never sees half of two models.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, delete, insert

from waferlens.db.models import SecomModelVersion, SecomScore, SecomSensorImportance
from waferlens.ml.experiment import Experiment


def write_results(engine: Engine, exp: Experiment) -> dict[str, int]:
    version = exp.model_version
    chosen = exp.chosen
    model_row = {
        "model_version": version,
        "config": chosen.config.name,
        "trained_at": datetime.now(UTC),
        "train_runs": len(exp.train.y),
        "test_runs": chosen.scores.n,
        "test_fails": chosen.scores.fails,
        "test_starts": exp.test.time.iloc[0].to_pydatetime(),
        "holdout_pr_auc": chosen.scores.pr_auc,
        "holdout_pr_auc_low": chosen.ci[0],
        "holdout_pr_auc_high": chosen.ci[1],
        "holdout_prevalence": chosen.scores.prevalence,
        "random_split_pr_auc": float(chosen.random_split.mean()),
        "baseline_pr_auc": exp.baseline.scores.pr_auc,
        "alarm_threshold": float(exp.extras["threshold"]),
        "mlflow_run_id": str(exp.extras["mlflow_run_id"]),
    }
    score_rows = [
        {"run_id": int(r["run_id"]), "model_version": version, "split": str(r["split"]),
         "score": float(r["score"]), "alarm": bool(r["alarm"])}
        for r in exp.run_scores.to_dict("records")
    ]  # fmt: skip
    missing = exp.train.X.isna().mean()
    importance_rows = [
        {"sensor_no": int(str(sensor)[1:]), "model_version": version,
         "importance": float(value), "importance_rank": rank,
         "missing_pct": 100 * float(missing[str(sensor)])}
        for rank, (sensor, value) in enumerate(exp.importance.items(), start=1)
    ]  # fmt: skip
    with engine.begin() as conn:
        for model in (SecomScore, SecomSensorImportance, SecomModelVersion):
            conn.execute(delete(model))
        conn.execute(insert(SecomModelVersion), [model_row])
        conn.execute(insert(SecomScore), score_rows)
        conn.execute(insert(SecomSensorImportance), importance_rows)
    return {"scores": len(score_rows), "sensors": len(importance_rows)}
