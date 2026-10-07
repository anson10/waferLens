"""The SECOM model against the database: SECOM in, results out for Grafana, and a SECOM
reload clearing the stale results."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import Engine, make_url, text

from tests.unit.ml.conftest import synthetic
from waferlens.db.models import ExternalBase
from waferlens.ingest.secom import Secom, load_secom
from waferlens.ml import secom
from waferlens.ml.experiment import Experiment, run_experiment
from waferlens.ml.secom import Config, Dataset
from waferlens.ml.store import write_results

pytestmark = pytest.mark.integration

GRID = [Config("logreg", "median", "none"), Config("lgbm", "native", "none")]
RESULT_TABLES = ("secom_model_versions", "secom_scores", "secom_sensor_importance")


def _as_secom(data: Dataset) -> Secom:
    runs = pd.DataFrame({"run_id": data.y.index.astype(np.int16), "run_time": data.time.to_numpy(),
                         "failed": data.y.astype(bool).to_numpy()})  # fmt: skip
    stacked = data.X.rename(columns=lambda c: int(c[1:])).stack().dropna()
    long = pd.DataFrame({"value": stacked}).reset_index()
    long.columns = ["run_id", "sensor_no", "value"]
    return Secom(runs, long.astype({"run_id": np.int16, "sensor_no": np.int16}))


@pytest.fixture(scope="module")
def data() -> Dataset:
    return synthetic()


@pytest.fixture(scope="module")
def loaded(engine: Engine, data: Dataset) -> Iterator[None]:
    load_secom(_as_secom(data), engine)
    yield
    names = ", ".join(t.name for t in ExternalBase.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))


@pytest.fixture(scope="module")
def exp(engine: Engine, loaded: None, tmp_path_factory: pytest.TempPathFactory) -> Experiment:
    uri = f"sqlite:///{Path(tmp_path_factory.mktemp('mlflow')) / 'mlflow.db'}"
    return run_experiment(secom.load(engine), uri, grid=GRID, random_split_seeds=2)


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_load_rebuilds_the_wide_frame(engine: Engine, loaded: None, data: Dataset) -> None:
    from_db = secom.load(engine)
    assert from_db.X.shape == (len(data.y), 590)
    pd.testing.assert_frame_equal(from_db.X[data.X.columns], data.X, check_names=False)
    assert from_db.X.iloc[:, len(data.X.columns) :].isna().all().all()  # sensors not in the data
    assert from_db.y.tolist() == data.y.tolist()


def test_results_land_for_grafana(engine: Engine, test_db_url: str, exp: Experiment) -> None:
    written = write_results(engine, exp)
    assert _count(engine, "secom_scores") == written["scores"] == len(exp.run_scores)
    assert _count(engine, "secom_model_versions") == 1
    reader = make_url(test_db_url).set(username="grafana_reader", password="grafana_reader")
    from sqlalchemy import create_engine

    eng = create_engine(reader)
    try:
        with eng.connect() as conn:
            for table in RESULT_TABLES:
                conn.execute(text(f"SELECT * FROM {table} LIMIT 1")).all()
            top = conn.execute(text("SELECT sensor_no FROM secom_sensor_importance "
                                    "WHERE importance_rank = 1")).scalar_one()  # fmt: skip
    finally:
        eng.dispose()
    assert top == 5  # the planted sensor


def test_rewriting_replaces_the_previous_model(engine: Engine, exp: Experiment) -> None:
    write_results(engine, exp)
    write_results(engine, exp)
    assert _count(engine, "secom_model_versions") == 1
    assert _count(engine, "secom_scores") == len(exp.run_scores)


def test_secom_reload_clears_stale_results(engine: Engine, data: Dataset, exp: Experiment) -> None:
    write_results(engine, exp)
    load_secom(_as_secom(data), engine)  # would fail on the scores' foreign key without clearing
    assert [_count(engine, t) for t in RESULT_TABLES] == [0, 0, 0]
    assert _count(engine, "secom_runs") == len(data.y)


def test_dagster_asset_trains_and_writes(
    engine: Engine, test_db_url: str, data: Dataset, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from dagster import materialize

    from waferlens.orchestration.assets import secom_model
    from waferlens.orchestration.resources import Tracking, Warehouse

    load_secom(_as_secom(data), engine)
    monkeypatch.setattr("waferlens.ml.experiment.GRID", GRID)  # keep it fast
    result = materialize([secom_model], resources={
        "warehouse": Warehouse(database_url=test_db_url),
        "tracking": Tracking(tracking_uri=f"sqlite:///{tmp_path / 'mlflow.db'}"),
    })  # fmt: skip
    assert result.success
    assert _count(engine, "secom_model_versions") == 1
    assert _count(engine, "secom_scores") > 0


def test_secom_dashboard_queries_run_as_the_reader(
    engine: Engine, test_db_url: str, data: Dataset, exp: Experiment
) -> None:
    from sqlalchemy import create_engine

    from waferlens.dashboards.sql import dashboard_queries, expand

    load_secom(_as_secom(data), engine)
    write_results(engine, exp)
    reader = create_engine(
        make_url(test_db_url).set(username="grafana_reader", password="grafana_reader")
    )
    empty = []
    try:
        with reader.connect() as conn:
            for q in dashboard_queries("secom"):
                sql = expand(q.sql, {"sensor": 5}, data.time.iloc[0], data.time.iloc[-1])
                if not conn.execute(text(sql)).first():
                    empty.append(q.where)
    finally:
        reader.dispose()
    assert empty == []
