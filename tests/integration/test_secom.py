"""Loading SECOM into the database, and its isolation from fab reloads."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import Engine, text

from waferlens.db.models import SECOM_SENSORS, Base
from waferlens.ingest.loader import load
from waferlens.ingest.secom import Secom, load_secom
from waferlens.simulate.run import SimulationResult, write_parquet

pytestmark = pytest.mark.integration


@pytest.fixture
def secom() -> Secom:
    rng = np.random.default_rng(0)
    runs = pd.DataFrame(
        {
            "run_id": np.arange(1, 21, dtype=np.int16),
            "run_time": pd.date_range("2008-07-19", periods=20, freq="h", tz="UTC"),
            "failed": rng.random(20) < 0.2,
        }
    )
    run, sensor = np.meshgrid(np.arange(1, 21), np.arange(1, SECOM_SENSORS + 1), indexing="ij")
    keep = rng.random(run.shape) > 0.05  # ~5% missing, like the real data
    readings = pd.DataFrame(
        {
            "run_id": run[keep].astype(np.int16),
            "sensor_no": sensor[keep].astype(np.int16),
            "value": rng.normal(size=int(keep.sum())),
        }
    )
    return Secom(runs, readings)


@pytest.fixture
def cleanup(engine: Engine) -> Iterator[None]:
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE secom_readings, secom_runs, {names} CASCADE"))


def _secom_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as conn:
        runs = conn.execute(text("SELECT count(*) FROM secom_runs")).scalar_one()
        readings = conn.execute(text("SELECT count(*) FROM secom_readings")).scalar_one()
    return runs, readings


def test_load_writes_every_row(engine: Engine, secom: Secom, cleanup: None) -> None:
    counts = load_secom(secom, engine)
    assert counts == {"secom_runs": 20, "secom_readings": len(secom.readings)}
    assert _secom_counts(engine) == (20, len(secom.readings))
    with engine.connect() as conn:
        failed = conn.execute(text("SELECT count(*) FROM secom_runs WHERE failed")).scalar_one()
        fk = conn.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conname = "
                 "'fk_secom_readings_run_id_secom_runs'")
        ).scalar_one()  # fmt: skip
    assert failed == int(secom.runs["failed"].sum())
    assert fk == 1


def test_reloading_replaces_instead_of_appending(
    engine: Engine, secom: Secom, cleanup: None
) -> None:
    load_secom(secom, engine)
    load_secom(secom, engine)
    assert _secom_counts(engine) == (20, len(secom.readings))


def test_fab_reload_leaves_secom_alone(
    engine: Engine,
    secom: Secom,
    dev: SimulationResult,
    tmp_path: Path,
    cleanup: None,
) -> None:
    load_secom(secom, engine)
    write_parquet(dev, tmp_path)
    load(tmp_path, engine)
    assert _secom_counts(engine) == (20, len(secom.readings))
