"""A small SECOM-like dataset with one planted signal and a drifting fail rate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from waferlens.ml.secom import Dataset, to_dataset

SIGNAL = "s005"


def synthetic(n: int = 600, sensors: int = 40, seed: int = 0) -> Dataset:
    """Fails become rarer over time; sensor 5 shifts on fails. Sensor 7 is constant, sensor 9
    is 80% missing, sensor 11 duplicates sensor 12, and ~5% of cells are missing."""
    rng = np.random.default_rng(seed)
    p_fail = np.linspace(0.25, 0.05, n)
    failed = rng.random(n) < p_fail
    X = rng.normal(size=(n, sensors))
    X[:, 4] += 1.5 * failed
    X[:, 6] = 3.0
    X[rng.random((n, sensors)) < 0.05] = np.nan
    X[rng.random(n) < 0.8, 8] = np.nan
    X[:, 10] = X[:, 11]
    frame = pd.DataFrame(X, index=pd.RangeIndex(1, n + 1, name="run_id"),
                         columns=range(1, sensors + 1))  # fmt: skip
    time = pd.Series(pd.date_range("2008-07-19", periods=n, freq="2h", tz="UTC"), index=frame.index)
    # shuffle the rows so to_dataset has to put them back in time order
    order = rng.permutation(n)
    return to_dataset(frame.iloc[order], pd.Series(failed, index=frame.index).iloc[order],
                      time.iloc[order])  # fmt: skip


@pytest.fixture(scope="session")
def data() -> Dataset:
    return synthetic()
