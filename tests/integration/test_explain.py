"""The key workload queries run on loaded data and their plans can be summarised."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from waferlens.db.explain import QUERY_DIR, measure, queries
from waferlens.db.models import Base
from waferlens.ingest.loader import load
from waferlens.simulate.run import SimulationResult, write_parquet

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def loaded_dev(
    engine: Engine, dev: SimulationResult, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    path = tmp_path_factory.mktemp("explain")
    write_parquet(dev, path)
    load(path, engine)
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))


def test_query_files_are_found() -> None:
    assert len(queries()) == len(list(QUERY_DIR.glob("*.sql"))) >= 7


@pytest.mark.parametrize("name", sorted(queries()))
def test_workload_query_runs_and_returns_rows(engine: Engine, loaded_dev: None, name: str) -> None:
    stats = measure(engine, name, queries()[name], runs=1)
    assert stats.ms > 0
    assert stats.rows > 0, f"{name} returned nothing on the dev fab"
    assert stats.scans


def test_wafer_yield_is_materialized_and_refreshed_by_the_loader(
    engine: Engine, loaded_dev: None, dev: SimulationResult
) -> None:
    with engine.connect() as conn:
        kind = conn.execute(
            text("SELECT relkind FROM pg_class WHERE relname = 'wafer_yield'")
        ).scalar_one()
        rows = conn.execute(text("SELECT count(*) FROM wafer_yield")).scalar_one()
    assert kind == "m"  # materialized view
    assert rows == dev.summary["wafers_sorted"]
