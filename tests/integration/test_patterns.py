"""FabEye scoring on the dev fab with a fake FabEye: every sorted wafer gets one prediction,
the evaluation joins the simulator's ground truth, and a fab reload clears stale scores."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from dagster import materialize
from sqlalchemy import Engine, text

from tests.fake_fabeye import fake_fabeye
from waferlens.db.models import Base
from waferlens.ingest.loader import load
from waferlens.orchestration.assets import wafer_patterns
from waferlens.orchestration.resources import FabEyeService, Warehouse
from waferlens.patterns.evaluate import evaluate
from waferlens.patterns.fabeye import FabEye
from waferlens.patterns.score import score_wafers
from waferlens.simulate.run import SimulationResult, write_parquet

pytestmark = pytest.mark.integration

REFERENCE = {"coverage": 0.893, "worst_class_coverage": 0.862,
             "accept": {"target_error": 0.02, "unseen_lot_accept_rate": 0.962,
                        "unseen_lot_error_among_accepted": 0.019}}  # fmt: skip


@pytest.fixture(scope="module")
def drop(dev: SimulationResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("patterns")
    write_parquet(dev, path)
    return path


@pytest.fixture(scope="module")
def loaded(engine: Engine, drop: Path) -> Iterator[None]:
    load(drop, engine)
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))


@pytest.fixture
def fabeye() -> Iterator[FabEye]:
    with fake_fabeye() as client:
        yield client


def _count(engine: Engine, sql: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def test_every_sorted_wafer_gets_one_prediction(
    engine: Engine, loaded: None, fabeye: FabEye
) -> None:
    report = score_wafers(engine, fabeye)
    maps = _count(engine, "SELECT count(*) FROM wafer_maps")
    assert report.wafers == maps == _count(engine, "SELECT count(*) FROM wafer_patterns")
    assert report.model == "wafer_cnn.onnx · api 2.0"
    again = score_wafers(engine, fabeye)  # replaces, never appends
    assert again.wafers == _count(engine, "SELECT count(*) FROM wafer_patterns")


def test_evaluation_joins_the_ground_truth(engine: Engine, loaded: None, fabeye: FabEye) -> None:
    score_wafers(engine, fabeye)
    ev = evaluate(engine, REFERENCE)
    truth = _count(engine, "SELECT count(*) FROM wafer_pattern_truth")
    assert truth > 0
    assert int((ev.frame["truth"] != "none").sum()) == truth
    # the fake only knows "Center": every center wafer whose middle die failed is found
    classes = ev.per_class.set_index("class")["true"].to_dict()
    assert classes["Center"] > 0
    assert ev.majority_accuracy == pytest.approx(1 - truth / len(ev.frame))


def test_dagster_asset_scores_and_a_reload_clears(
    engine: Engine, test_db_url: str, loaded: None, drop: Path, fabeye: FabEye
) -> None:
    result = materialize([wafer_patterns], resources={
        "warehouse": Warehouse(database_url=test_db_url),
        "fabeye": FabEyeService(url=fabeye.url, api_key=fabeye.api_key),
    })  # fmt: skip
    assert result.success
    assert _count(engine, "SELECT count(*) FROM wafer_patterns") > 0
    load(drop, engine)  # a new fab: the old predictions would describe other wafers
    assert _count(engine, "SELECT count(*) FROM wafer_patterns") == 0
