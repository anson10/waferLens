"""Tool agents: readings come out in the batch engine's order, and a drift shifts only its
series, only from its start."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from waferlens.stream.producer import Drift, inject, read_readings

T0 = datetime(2026, 3, 1, tzinfo=UTC)


def _drop(tmp_path: Path) -> Path:
    rng = np.random.default_rng(0)
    n = 200
    df = pd.DataFrame({
        "time": [T0 + timedelta(minutes=int(m)) for m in rng.integers(0, 600, n)],
        "wafer_id": rng.integers(1, 50, n).astype("int32"),
        "route_step_id": rng.integers(1, 5, n).astype("int32"),
        "parameter_id": rng.integers(1, 3, n).astype("int16"),
        "chamber_id": rng.integers(1, 4, n).astype("int16"),
        "value": rng.normal(10, 1, n),
    })  # fmt: skip
    df.sample(frac=1, random_state=1).to_parquet(tmp_path / "tool_sensor_readings.parquet")
    return tmp_path


def test_readings_are_in_event_time_order_and_windowed(tmp_path: Path) -> None:
    drop = _drop(tmp_path)
    df = read_readings(drop)
    keys = list(zip(df["time"], df["wafer_id"], df["route_step_id"], df["parameter_id"],
                    strict=True))  # fmt: skip
    assert keys == sorted(keys)
    window = read_readings(drop, T0 + timedelta(hours=2), hours=3)
    assert window["time"].min() >= pd.Timestamp(T0 + timedelta(hours=2))
    assert window["time"].max() < pd.Timestamp(T0 + timedelta(hours=5))


def test_drift_shifts_only_its_series_from_its_start(tmp_path: Path) -> None:
    df = read_readings(_drop(tmp_path))
    drift = Drift(chamber_id=2, parameter_id=1, start=T0 + timedelta(hours=5), shift_sigma=2.0)
    out = inject(df, drift)
    series = (df["chamber_id"] == 2) & (df["parameter_id"] == 1)
    after = series & (df["time"] >= pd.Timestamp(drift.start))
    sigma = df.loc[series, "value"].std()
    np.testing.assert_allclose(out.loc[after, "value"] - df.loc[after, "value"], 2.0 * sigma)
    assert out.loc[~after, "value"].equals(df.loc[~after, "value"])
