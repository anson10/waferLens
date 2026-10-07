"""Grafana's SQL on the dev fab, run as the read-only grafana_reader role: every variable,
annotation, panel and alert query executes after macro expansion, and the role can't write.

Variables are set to the excursion the README screenshots show (a sensor excursion SPC
caught), and each variable query must return values.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from datetime import datetime

import numpy as np
import pytest
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.exc import ProgrammingError

from waferlens.dashboards.build import DASHBOARDS
from waferlens.dashboards.screenshots import EXAMPLE_SQL
from waferlens.dashboards.sql import alert_queries, dashboard_queries, expand
from waferlens.db.models import Base
from waferlens.ingest.loader import load
from waferlens.orchestration.resources import ROOT
from waferlens.rootcause.evaluate import evaluate_excursions
from waferlens.simulate.run import SimulationResult, write_parquet
from waferlens.spc import charts
from waferlens.spc.engine import SpcConfig, run_spc

pytestmark = pytest.mark.integration


def _dbt(test_db_url: str, *select: str) -> None:
    dbt = ROOT / "dbt"
    args = ["--select", *select] if select else []
    subprocess.run(
        ["dbt", "build", *args, "--exclude", "test_type:data",
         "--profiles-dir", str(dbt), "--project-dir", str(dbt)],
        check=True, capture_output=True,
        env={**os.environ, "POSTGRES_DB": str(make_url(test_db_url).database)},
    )  # fmt: skip


@pytest.fixture(scope="module")
def fab(
    engine: Engine,
    test_db_url: str,
    dev: SimulationResult,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """The whole pipeline: load, marts the engines read, SPC, root cause, every mart."""
    path = tmp_path_factory.mktemp("grafana")
    write_parquet(dev, path)
    load(path, engine)
    _dbt(test_db_url, "+fct_measurements", "+dim_chamber", "+fct_wafer_steps",
         "+fct_wafer_yield")  # fmt: skip
    run_spc(engine, SpcConfig(baseline_days=7), relearn=True)  # dev covers 30 days
    evaluate_excursions(engine)
    _dbt(test_db_url)
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS staging, intermediate, marts CASCADE"))


@pytest.fixture(scope="module")
def reader(test_db_url: str) -> Iterator[Engine]:
    url = make_url(test_db_url).set(username="grafana_reader", password="grafana_reader")
    eng = create_engine(url)
    yield eng
    eng.dispose()


def _time_range(conn: Connection) -> tuple[datetime, datetime]:
    row = conn.execute(text("SELECT min(time), max(time) FROM tool_sensor_readings")).one()
    return row[0], row[1]


@pytest.mark.parametrize("name", sorted(DASHBOARDS))
def test_every_dashboard_query_runs_as_the_reader(fab: None, reader: Engine, name: str) -> None:
    empty: list[str] = []
    with reader.connect() as conn:
        ex = conn.execute(text(EXAMPLE_SQL)).mappings().one()
        variables = {"tool": ex["tool_id"], "chamber": ex["chamber_id"],
                     "parameter": ex["parameter_id"], "excursion": ex["excursion_id"]}  # fmt: skip
        start, end = _time_range(conn)
        for q in dashboard_queries(name):
            if not conn.execute(text(expand(q.sql, variables, start, end))).first():
                empty.append(q.where)
    # Only T² may be empty: not every chamber's steps are followed by metrology.
    assert set(empty) <= {"spc / panel 4 / A"}, empty


def test_alert_queries_run_as_the_reader(fab: None, reader: Engine) -> None:
    with reader.connect() as conn:
        for q in alert_queries():
            conn.execute(text(q.sql)).all()


def test_sql_ewma_matches_the_python_chart(fab: None, engine: Engine) -> None:
    z = np.random.default_rng(7).normal(size=200)
    with engine.connect() as conn:
        conn.execute(text("CREATE TEMP TABLE zs (i int, z float8)"))
        conn.execute(text("INSERT INTO zs VALUES (:i, :z)"),
                     [{"i": i, "z": float(v)} for i, v in enumerate(z)])  # fmt: skip
        sql_ewma = (
            conn.execute(text("SELECT ewma(z, 0.2) OVER (ORDER BY i) FROM zs ORDER BY i"))
            .scalars()
            .all()
        )
    np.testing.assert_allclose(sql_ewma, charts.ewma(z, 0.2)[0], atol=1e-12)


@pytest.mark.parametrize("statement", [
    "DELETE FROM lots",
    "UPDATE marts.fct_wafer_yield SET yield_pct = 100",
    "CREATE TABLE public.scratch (i int)",
])  # fmt: skip
def test_the_reader_cannot_write(fab: None, reader: Engine, statement: str) -> None:
    with reader.connect() as conn, pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text(statement))
