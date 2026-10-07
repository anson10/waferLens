"""SECOM fail prediction: data, preprocessing, models and an evaluation that respects time.

The fail rate drifts from 22% in July to 3% in September (docs/data/secom.md), so every
estimate here is forward in time: the holdout is the last 30% of runs, and model selection
uses walk-forward folds inside the training period. A random split is computed only to
measure how much it would flatter the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.feature_selection import SelectFromModel, SelectKBest, mutual_info_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedShuffleSplit, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import Engine, text

ModelName = Literal["logreg", "lgbm"]
Missing = Literal["median", "median+indicator", "native"]
Selection = Literal["none", "corr", "l1", "mutual_info"]

TEST_FRACTION = 0.3
WALK_FORWARD_FOLDS = 4
FALSE_ALARM_RATES = (0.05, 0.10)
SEED = 42

WIDE_SQL = """
    -- One row per run; a sensor with no reading for a run is missing (NaN), not zero.
    SELECT r.run_id, r.run_time, r.failed, s.sensor_no, s.value
    FROM secom_runs AS r
    LEFT JOIN secom_readings AS s ON s.run_id = r.run_id
"""


@dataclass(frozen=True)
class Dataset:
    """Runs in time order: X has one column per sensor (NaN = not recorded)."""

    X: pd.DataFrame
    y: pd.Series
    time: pd.Series

    def split_at(self, k: int) -> tuple[Dataset, Dataset]:
        return self.take(np.arange(k)), self.take(np.arange(k, len(self.y)))

    def take(self, idx: np.ndarray) -> Dataset:
        return Dataset(self.X.iloc[idx], self.y.iloc[idx], self.time.iloc[idx])


def load(engine: Engine) -> Dataset:
    with engine.connect() as conn:
        long = pd.read_sql(text(WIDE_SQL), conn)
    runs = long.drop_duplicates("run_id").set_index("run_id")[["run_time", "failed"]]
    X = long.dropna(subset=["sensor_no"]).pivot(index="run_id", columns="sensor_no", values="value")
    X = X.reindex(index=runs.index, columns=range(1, 591))
    return to_dataset(X, runs["failed"], runs["run_time"])


def to_dataset(X: pd.DataFrame, failed: pd.Series, time: pd.Series) -> Dataset:
    """Sorts by time (ties by run id) and names sensor columns s001..s590."""
    order = np.lexsort((X.index.to_numpy(), pd.to_datetime(time).to_numpy()))
    X = X.iloc[order].astype(float)
    X.columns = [f"s{int(c):03d}" if not str(c).startswith("s") else str(c) for c in X.columns]
    return Dataset(X, failed.iloc[order].astype(int), pd.to_datetime(time).iloc[order])


def time_split(data: Dataset, test_fraction: float = TEST_FRACTION) -> tuple[Dataset, Dataset]:
    """Train on the earliest runs, test on the latest ones."""
    return data.split_at(round(len(data.y) * (1 - test_fraction)))


def random_split(
    data: Dataset, seed: int, test_fraction: float = TEST_FRACTION
) -> tuple[Dataset, Dataset]:
    """Stratified random split of the same size: the evaluation a time-blind notebook uses."""
    split = StratifiedShuffleSplit(n_splits=1, test_size=test_fraction, random_state=seed)
    train, test = next(split.split(data.X, data.y))
    return data.take(np.sort(train)), data.take(np.sort(test))


# --------------------------------------------------------------------------- preprocessing


class DropUseless(TransformerMixin, BaseEstimator):
    """Drops sensors that are constant or mostly missing *in the training data*."""

    def __init__(self, max_missing: float = 0.5) -> None:
        self.max_missing = max_missing

    def fit(self, X: pd.DataFrame, y: Any = None) -> DropUseless:
        missing = X.isna().mean()
        constant = X.nunique(dropna=True) <= 1
        self.keep_ = [c for c in X.columns if missing[c] <= self.max_missing and not constant[c]]
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return X[self.keep_]

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        return np.asarray(self.keep_, dtype=object)


class DropCorrelated(TransformerMixin, BaseEstimator):
    """Keeps the first of every group of sensors correlated above ``threshold``."""

    def __init__(self, threshold: float = 0.95) -> None:
        self.threshold = threshold

    def fit(self, X: Any, y: Any = None) -> DropCorrelated:
        corr = np.abs(np.nan_to_num(np.corrcoef(np.asarray(X, dtype=float), rowvar=False)))
        drop = np.zeros(corr.shape[0], dtype=bool)
        for i in range(corr.shape[0]):
            if not drop[i]:
                drop[i + 1 :] |= corr[i, i + 1 :] > self.threshold
        self.support_ = ~drop
        return self

    def transform(self, X: Any) -> Any:
        return np.asarray(X)[:, self.support_]

    def get_support(self) -> np.ndarray:
        return self.support_

    def get_feature_names_out(self, input_features: Any = None) -> np.ndarray:
        return np.asarray(input_features, dtype=object)[self.support_]


def _selector(selection: Selection) -> list[tuple[str, Any]]:
    if selection == "corr":
        return [("select", DropCorrelated())]
    if selection == "l1":
        l1 = LogisticRegression(l1_ratio=1.0, C=0.1, solver="liblinear", class_weight="balanced",
                                random_state=SEED)  # fmt: skip
        return [("select", SelectFromModel(l1))]
    if selection == "mutual_info":
        return [("select", SelectKBest(lambda X, y: mutual_info_classif(X, y, random_state=SEED),
                                       k=40))]  # fmt: skip
    return []


def build(model: ModelName, missing: Missing, selection: Selection) -> Pipeline:
    """Every step is fitted on training data only, so nothing leaks from the test runs."""
    if missing == "native" and (model != "lgbm" or selection != "none"):
        raise ValueError("native missing values need lgbm without feature selection")
    steps: list[tuple[str, Any]] = [("drop", DropUseless())]
    if missing != "native":  # LightGBM learns which branch a missing value takes
        steps.append(
            (
                "impute",
                SimpleImputer(strategy="median", add_indicator=missing == "median+indicator"),
            )
        )
        steps.append(("scale", StandardScaler()))  # fmt: skip
    steps += _selector(selection)
    if model == "logreg":
        clf: Any = LogisticRegression(C=0.05, class_weight="balanced", max_iter=5000,
                                      random_state=SEED)  # fmt: skip
    else:
        # Small, heavily regularised trees: 1,000 training runs with ~80 fails.
        clf = LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=7,
                             min_child_samples=20, subsample=0.8, subsample_freq=1,
                             colsample_bytree=0.5, reg_lambda=1.0, class_weight="balanced",
                             random_state=SEED, verbose=-1)  # fmt: skip
    steps.append(("model", clf))
    return Pipeline(steps)


@dataclass(frozen=True)
class Config:
    model: ModelName
    missing: Missing
    selection: Selection

    @property
    def name(self) -> str:
        return f"{self.model} · {self.missing} · {self.selection}"

    def build(self) -> Pipeline:
        return build(self.model, self.missing, self.selection)


GRID = [*(Config(m, mi, s) for m in ("logreg", "lgbm")
          for mi in ("median", "median+indicator")
          for s in ("none", "corr", "l1", "mutual_info")),
        Config("lgbm", "native", "none")]  # fmt: skip


# --------------------------------------------------------------------------- evaluation


def walk_forward(config: Config, train: Dataset, folds: int = WALK_FORWARD_FOLDS) -> pd.Series:
    """Out-of-fold scores from expanding windows: each fold is predicted by a model trained
    only on the runs before it. The first block is never predicted."""
    scores = pd.Series(np.nan, index=train.y.index)
    for fit_idx, pred_idx in TimeSeriesSplit(n_splits=folds).split(train.X):
        part = train.take(fit_idx)
        if part.y.nunique() < 2:
            continue
        pipe = config.build().fit(part.X, part.y)
        scores.iloc[pred_idx] = pipe.predict_proba(train.X.iloc[pred_idx])[:, 1]
    return scores.dropna()


def threshold_at_false_alarm_rate(y: pd.Series, scores: pd.Series, rate: float) -> float:
    """Lowest threshold whose false-alarm rate on (y, scores) stays at or below ``rate``."""
    negatives = np.sort(scores[y == 0].to_numpy())[::-1]
    k = int(np.floor(rate * len(negatives)))
    return float(negatives[k]) + 1e-12 if k < len(negatives) else float(negatives[-1])


@dataclass(frozen=True)
class Scores:
    pr_auc: float
    roc_auc: float
    prevalence: float
    n: int
    fails: int


def score(y: pd.Series, s: pd.Series | np.ndarray) -> Scores:
    return Scores(float(average_precision_score(y, s)), float(roc_auc_score(y, s)),
                  float(y.mean()), len(y), int(y.sum()))  # fmt: skip


def recall_and_fpr(y: pd.Series, s: np.ndarray, threshold: float) -> tuple[float, float]:
    alarm = s >= threshold
    recall = float(alarm[y.to_numpy() == 1].mean())
    fpr = float(alarm[y.to_numpy() == 0].mean())
    return recall, fpr


def bootstrap_pr_auc(
    y: pd.Series, s: np.ndarray, n: int = 2000, seed: int = SEED
) -> tuple[float, float]:
    """95% interval for PR-AUC, resampling runs (stratified, so every sample has fails)."""
    rng = np.random.default_rng(seed)
    yy = y.to_numpy()
    pos, neg = np.flatnonzero(yy == 1), np.flatnonzero(yy == 0)
    stats = []
    for _ in range(n):
        idx = np.concatenate([rng.choice(pos, len(pos)), rng.choice(neg, len(neg))])
        stats.append(average_precision_score(yy[idx], s[idx]))
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return float(lo), float(hi)


def roc_points(y: pd.Series, s: np.ndarray) -> pd.DataFrame:
    fpr, tpr, thr = roc_curve(y, s)
    return pd.DataFrame({"fpr": fpr, "recall": tpr, "threshold": thr})


def importance(pipe: Pipeline, X: pd.DataFrame) -> pd.Series:
    """Mean |contribution| per input sensor on X: TreeSHAP for LightGBM (built in, via
    ``pred_contrib``), |coefficient| x feature sd (=1 after scaling) for logistic
    regression. Indicator columns count towards their sensor."""
    head = pipe[:-1]
    Z = head.transform(X)
    names = [str(n) for n in cast(Any, head.get_feature_names_out())]
    model: Any = pipe[-1]
    if isinstance(model, LGBMClassifier):
        contrib = np.asarray(model.predict(Z, pred_contrib=True))[:, :-1]  # last column = bias
        values = np.abs(contrib).mean(axis=0)
    else:
        values = np.abs(model.coef_[0])
    out = pd.Series(values, index=[_sensor(n) for n in names])
    return out.groupby(level=0).sum().sort_values(ascending=False)


def _sensor(feature: str) -> str:
    # "missingindicator_s123" -> "s123"
    return feature.rsplit("_", 1)[-1] if feature.startswith("missingindicator") else feature
