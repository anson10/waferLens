"""SECOM modelling on synthetic data: time order, no leakage from test rows, and metrics that
mean what they say."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.unit.ml.conftest import SIGNAL
from waferlens.ml.secom import (
    GRID,
    Config,
    Dataset,
    DropCorrelated,
    DropUseless,
    bootstrap_pr_auc,
    importance,
    random_split,
    recall_and_fpr,
    score,
    threshold_at_false_alarm_rate,
    time_split,
    walk_forward,
)


def test_dataset_is_in_time_order_with_named_sensors(data: Dataset) -> None:
    assert data.time.is_monotonic_increasing
    assert list(data.X.columns[:3]) == ["s001", "s002", "s003"]
    assert data.X.index.equals(data.y.index)


def test_time_split_trains_on_the_past(data: Dataset) -> None:
    train, test = time_split(data)
    assert train.time.max() <= test.time.min()
    assert len(test.y) == round(0.3 * len(data.y))
    assert train.y.mean() > test.y.mean()  # the planted drift: fails get rarer


def test_random_split_is_stratified_and_mixes_time(data: Dataset) -> None:
    train, test = random_split(data, seed=1)
    assert abs(train.y.mean() - test.y.mean()) < 0.01
    assert train.time.max() > test.time.min()


def test_useless_sensors_are_judged_on_training_rows_only(data: Dataset) -> None:
    train, _ = time_split(data)
    keep = DropUseless().fit(train.X).keep_
    assert "s007" not in keep  # constant
    assert "s009" not in keep  # 80% missing
    assert SIGNAL in keep


def test_correlated_duplicates_are_pruned() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(size=200)
    X = np.column_stack([a, a * 2 + 0.001 * rng.normal(size=200), rng.normal(size=200)])
    assert DropCorrelated().fit(X).get_support().tolist() == [True, False, True]


@pytest.mark.parametrize("config", GRID, ids=lambda c: c.name)
def test_every_pipeline_fits_and_never_sees_test_rows(data: Dataset, config: Config) -> None:
    train, test = time_split(data)
    pipe = config.build().fit(train.X, train.y)
    s = pipe.predict_proba(test.X)[:, 1]
    assert s.shape == (len(test.y),)
    assert np.isfinite(s).all()
    if "impute" in pipe.named_steps:
        kept = pipe.named_steps["drop"].keep_
        medians = pipe.named_steps["impute"].statistics_
        np.testing.assert_allclose(medians, train.X[kept].median().to_numpy())


def test_native_missing_values_only_for_lightgbm() -> None:
    with pytest.raises(ValueError, match="native"):
        Config("logreg", "native", "none").build()


def test_walk_forward_predicts_only_from_the_past(data: Dataset) -> None:
    train, _ = time_split(data)
    oof = walk_forward(Config("logreg", "median", "none"), train, folds=4)
    block = len(train.y) // 5
    assert oof.index.equals(train.y.index[len(train.y) - len(oof) :])  # all but the first block
    assert len(oof) >= 4 * block


def test_planted_sensor_is_found_by_both_models(data: Dataset) -> None:
    train, test = time_split(data)
    for config in (Config("logreg", "median+indicator", "none"), Config("lgbm", "native", "none")):
        pipe = config.build().fit(train.X, train.y)
        assert importance(pipe, test.X).index[0] == SIGNAL, config.name
        assert score(test.y, pipe.predict_proba(test.X)[:, 1]).pr_auc > 2 * test.y.mean()


def test_threshold_keeps_false_alarms_within_budget() -> None:
    rng = np.random.default_rng(3)
    y = pd.Series(rng.random(1000) < 0.1).astype(int)
    s = pd.Series(rng.random(1000) + 0.5 * y)
    for rate in (0.05, 0.10):
        threshold = threshold_at_false_alarm_rate(y, s, rate)
        recall, fpr = recall_and_fpr(y, s.to_numpy(), threshold)
        assert fpr <= rate
        assert fpr > rate - 0.01  # and uses the budget
        assert recall > rate


def test_bootstrap_interval_contains_the_estimate(data: Dataset) -> None:
    y = data.y
    s = data.X[SIGNAL].fillna(0).to_numpy()
    lo, hi = bootstrap_pr_auc(y, s, n=300)
    assert lo < score(y, s).pr_auc < hi
