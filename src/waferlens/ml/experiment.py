"""The SECOM experiment, end to end, logged to MLflow.

1. Selection: every configuration in ``GRID`` is scored by walk-forward CV on the training
   period (first 70% of runs). The holdout is not looked at.
2. Holdout: the best configuration, and the best logistic regression as the baseline, are
   refitted on the whole training period and scored once on the last 30% of runs.
3. Leakage gap: the same configurations on stratified random splits of the same size.
4. The chosen model is registered in MLflow; its scores and sensor importance go to the
   database for Grafana (``waferlens.ml.store``).
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd
from mlflow.sklearn import log_model
from mlflow.tracking import MlflowClient
from sklearn.pipeline import Pipeline

from waferlens.ml.secom import (
    FALSE_ALARM_RATES,
    GRID,
    SEED,
    Config,
    Dataset,
    Scores,
    bootstrap_pr_auc,
    importance,
    random_split,
    recall_and_fpr,
    roc_points,
    score,
    threshold_at_false_alarm_rate,
    time_split,
    walk_forward,
)

EXPERIMENT = "secom-fail-prediction"
REGISTERED_MODEL = "secom-fail-predictor"
RANDOM_SPLIT_SEEDS = 20
os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")  # no usage data leaves the machine
ALARM_RATE = 0.10  # false-alarm budget the stored alarm flag is set for


@dataclass
class Holdout:
    config: Config
    scores: Scores
    ci: tuple[float, float]
    # per false-alarm budget: threshold from the training period -> (recall, actual rate)
    forward: dict[float, tuple[float, float]]
    # per false-alarm budget: recall if the threshold were set on the holdout itself
    hindsight: dict[float, float]
    random_split: np.ndarray  # PR-AUC on random splits of the same size


@dataclass
class Experiment:
    train: Dataset
    test: Dataset
    selection: list[tuple[Config, Scores]]
    chosen: Holdout
    baseline: Holdout
    importance: pd.Series
    run_scores: pd.DataFrame  # run_id, score, split, alarm
    model_version: str
    extras: dict[str, Any] = field(default_factory=dict)


def _hindsight_recall(y: pd.Series, s: np.ndarray, rate: float) -> float:
    roc = roc_points(y, s)
    return float(roc.loc[roc["fpr"] <= rate, "recall"].max())


def _holdout(config: Config, data: Dataset, train: Dataset, test: Dataset,
             oof: pd.Series, seeds: int) -> tuple[Holdout, Pipeline, np.ndarray]:  # fmt: skip
    pipe = config.build().fit(train.X, train.y)
    s = pipe.predict_proba(test.X)[:, 1]
    oof_y = train.y.loc[oof.index]
    forward = {}
    for rate in FALSE_ALARM_RATES:
        threshold = threshold_at_false_alarm_rate(oof_y, oof, rate)
        forward[rate] = recall_and_fpr(test.y, s, threshold)
    random_scores = []
    for seed in range(seeds):
        a, b = random_split(data, seed)
        p = config.build().fit(a.X, a.y)
        random_scores.append(score(b.y, p.predict_proba(b.X)[:, 1]).pr_auc)
    result = Holdout(
        config=config,
        scores=score(test.y, s),
        ci=bootstrap_pr_auc(test.y, s),
        forward=forward,
        hindsight={rate: _hindsight_recall(test.y, s, rate) for rate in FALSE_ALARM_RATES},
        random_split=np.array(random_scores),
    )
    return result, pipe, s


def _log_scores(prefix: str, s: Scores) -> None:
    mlflow.log_metrics({f"{prefix}_pr_auc": s.pr_auc, f"{prefix}_roc_auc": s.roc_auc,
                        f"{prefix}_prevalence": s.prevalence})  # fmt: skip


def run_experiment(data: Dataset, tracking_uri: str, *,
                   grid: list[Config] | None = None,
                   random_split_seeds: int = RANDOM_SPLIT_SEEDS) -> Experiment:  # fmt: skip
    warnings.filterwarnings("ignore", category=UserWarning)  # LightGBM feature-name chatter
    mlflow.set_tracking_uri(tracking_uri)
    _set_experiment(tracking_uri)
    train, test = time_split(data)
    grid = grid or GRID

    with mlflow.start_run(run_name="secom-experiment") as parent:
        mlflow.log_params({"train_runs": len(train.y), "train_fails": int(train.y.sum()),
                           "test_runs": len(test.y), "test_fails": int(test.y.sum()),
                           "test_starts": str(test.time.iloc[0]), "seed": SEED})  # fmt: skip

        # 1. selection on walk-forward CV
        selection: list[tuple[Config, Scores]] = []
        oofs: dict[Config, pd.Series] = {}
        for config in grid:
            with mlflow.start_run(run_name=config.name, nested=True):
                oof = walk_forward(config, train)
                cv = score(train.y.loc[oof.index], oof)
                mlflow.log_params({"model": config.model, "missing": config.missing,
                                   "selection": config.selection})  # fmt: skip
                _log_scores("cv", cv)
            selection.append((config, cv))
            oofs[config] = oof
        chosen_cfg = max(selection, key=lambda cs: cs[1].pr_auc)[0]
        baseline_cfg = max((cs for cs in selection if cs[0].model == "logreg"),
                           key=lambda cs: cs[1].pr_auc)[0]  # fmt: skip

        # 2 + 3. holdout once, and the random-split comparison
        baseline, baseline_pipe, _ = _holdout(baseline_cfg, data, train, test, oofs[baseline_cfg],
                                  random_split_seeds)  # fmt: skip
        chosen, pipe, test_scores = _holdout(chosen_cfg, data, train, test, oofs[chosen_cfg],
                                             random_split_seeds)  # fmt: skip
        mlflow.log_params({"chosen": chosen_cfg.name, "baseline": baseline_cfg.name})
        _log_scores("holdout", chosen.scores)
        mlflow.log_metrics({
            "holdout_pr_auc_ci_low": chosen.ci[0], "holdout_pr_auc_ci_high": chosen.ci[1],
            "random_split_pr_auc_mean": float(chosen.random_split.mean()),
            "baseline_holdout_pr_auc": baseline.scores.pr_auc,
            **{f"holdout_recall_at_far_{r:.2f}": chosen.forward[r][0] for r in FALSE_ALARM_RATES},
        })  # fmt: skip

        imp = importance(pipe, test.X)
        mlflow.log_dict({str(k): float(v) for k, v in imp.head(30).items()},
                        "importance_top30.json")  # fmt: skip

        # 4. register the chosen model (trained on the training period only)
        # cloudpickle, not skops: the pipeline holds this package's own transformers.
        info = log_model(pipe, name="model", input_example=test.X.iloc[:2],
                                        serialization_format="cloudpickle",
                                        registered_model_name=REGISTERED_MODEL)  # fmt: skip
        version = _registered_version(info.model_uri, parent.info.run_id)

    threshold = threshold_at_false_alarm_rate(train.y.loc[oofs[chosen_cfg].index],
                                              oofs[chosen_cfg], ALARM_RATE)  # fmt: skip
    oof = oofs[chosen_cfg]
    run_scores = pd.concat([
        pd.DataFrame({"run_id": oof.index, "score": oof.to_numpy(), "split": "walk_forward"}),
        pd.DataFrame({"run_id": test.y.index, "score": test_scores, "split": "holdout"}),
    ], ignore_index=True)  # fmt: skip
    run_scores["alarm"] = run_scores["score"] >= threshold
    return Experiment(train, test, selection, chosen, baseline, imp, run_scores, version,
                      {"threshold": threshold, "tracking_uri": tracking_uri,
                       "mlflow_run_id": parent.info.run_id,
                       "baseline_importance": importance(baseline_pipe, test.X)})  # fmt: skip


def _set_experiment(tracking_uri: str) -> None:
    """With a local SQLite store, MLflow would write artifacts to ./mlruns in the working
    directory; keep them next to the database instead."""
    if mlflow.get_experiment_by_name(EXPERIMENT) is None and tracking_uri.startswith("sqlite:///"):
        artifacts = Path(tracking_uri.removeprefix("sqlite:///")).parent / "mlartifacts"
        mlflow.create_experiment(EXPERIMENT, artifact_location=artifacts.as_uri())
    mlflow.set_experiment(EXPERIMENT)


def _registered_version(model_uri: str, run_id: str) -> str:
    client = MlflowClient()
    versions = client.search_model_versions(f"name = '{REGISTERED_MODEL}' and run_id = '{run_id}'")
    return f"v{max(int(v.version) for v in versions)}" if versions else model_uri
