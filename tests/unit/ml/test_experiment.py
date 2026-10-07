"""The experiment end to end on synthetic data, with MLflow on a local SQLite store."""

from __future__ import annotations

from pathlib import Path

import mlflow
import pytest
from mlflow.sklearn import load_model
from mlflow.tracking import MlflowClient

from tests.unit.ml.conftest import SIGNAL
from waferlens.ml.experiment import REGISTERED_MODEL, Experiment, run_experiment
from waferlens.ml.report import render
from waferlens.ml.secom import Config, Dataset

GRID = [Config("logreg", "median", "none"), Config("lgbm", "native", "none")]


@pytest.fixture(scope="module")
def exp(data: Dataset, tmp_path_factory: pytest.TempPathFactory) -> Experiment:
    uri = f"sqlite:///{tmp_path_factory.mktemp('mlflow') / 'mlflow.db'}"
    return run_experiment(data, uri, grid=GRID, random_split_seeds=3)


def test_selection_scores_every_config_and_picks_the_best(exp: Experiment) -> None:
    assert [c for c, _ in exp.selection] == GRID
    assert exp.chosen.config == max(exp.selection, key=lambda cs: cs[1].pr_auc)[0]
    assert exp.baseline.config.model == "logreg"


def test_holdout_is_the_latest_runs_and_beats_chance(exp: Experiment) -> None:
    assert exp.train.time.max() <= exp.test.time.min()
    s = exp.chosen.scores
    assert s.n == len(exp.test.y)
    assert s.pr_auc > s.prevalence
    assert exp.importance.index[0] == SIGNAL


def test_every_scored_run_is_out_of_sample(exp: Experiment) -> None:
    by_split = exp.run_scores.groupby("split")["run_id"]
    holdout = set(by_split.get_group("holdout"))
    assert holdout == set(exp.test.y.index)
    assert set(by_split.get_group("walk_forward")) <= set(exp.train.y.index)
    assert exp.run_scores["run_id"].is_unique


def test_model_is_registered_and_loads(exp: Experiment) -> None:
    mlflow.set_tracking_uri(exp.extras["tracking_uri"])
    version = MlflowClient().get_model_version(REGISTERED_MODEL, exp.model_version[1:])
    model = load_model(f"models:/{REGISTERED_MODEL}/{version.version}")
    assert model is not None
    assert model.predict_proba(exp.test.X.iloc[:5]).shape == (5, 2)
    parent = MlflowClient().get_run(exp.extras["mlflow_run_id"])
    assert parent.data.metrics["holdout_pr_auc"] == pytest.approx(exp.chosen.scores.pr_auc)


def test_report_renders(exp: Experiment, tmp_path: Path) -> None:
    md = render(exp)
    assert "# SECOM fail prediction" in md
    assert exp.chosen.config.name in md
    assert SIGNAL in md
    assert "nan" not in md.lower()
