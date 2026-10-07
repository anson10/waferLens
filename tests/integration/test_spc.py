"""SPC engine on the dev fab: frozen limits, versioned relearning, idempotent alarms that
concentrate where the simulator injected excursions."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, make_url, text

from waferlens.db.models import Base
from waferlens.ingest.loader import load
from waferlens.orchestration.resources import ROOT
from waferlens.simulate.run import SimulationResult, write_parquet
from waferlens.spc.engine import SpcConfig, run_spc

pytestmark = pytest.mark.integration

CONFIG = SpcConfig(baseline_days=7)  # dev covers 30 days


@pytest.fixture(scope="module")
def marts(
    engine: Engine,
    test_db_url: str,
    dev: SimulationResult,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    path = tmp_path_factory.mktemp("spc")
    write_parquet(dev, path)
    load(path, engine)
    dbt = ROOT / "dbt"
    env = {"POSTGRES_DB": str(make_url(test_db_url).database)}
    subprocess.run(
        ["dbt", "build", "--select", "+fct_measurements", "+dim_chamber", "--exclude",
         "test_type:data", "--profiles-dir", str(dbt), "--project-dir", str(dbt)],
        check=True, capture_output=True, env={**os.environ, **env},
    )  # fmt: skip
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS staging, intermediate, marts CASCADE"))


def _scalar(engine: Engine, sql: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def test_first_run_learns_limits_and_raises_alarms(engine: Engine, marts: None) -> None:
    report = run_spc(engine, CONFIG, relearn=True)
    assert report.limits_new > 100
    assert sum(report.alarms.values()) > 0
    assert set(report.alarms) <= {"we1", "we2", "we3", "we4", "ewma", "cusum", "t2"}
    assert _scalar(engine, "SELECT count(*) FROM spc_alarms") == sum(report.alarms.values())


def test_rerun_reuses_frozen_limits_and_is_idempotent(engine: Engine, marts: None) -> None:
    first = run_spc(engine, CONFIG)
    again = run_spc(engine, CONFIG)
    assert again.limits_new == 0
    assert again.limits_reused == first.limits_new + first.limits_reused
    assert again.alarms == first.alarms
    duplicates = _scalar(
        engine,
        "SELECT count(*) FROM (SELECT limit_id, chart, wafer_id, route_step_id, pass_no "
        "FROM spc_alarms GROUP BY 1, 2, 3, 4, 5 HAVING count(*) > 1) d",
    )
    assert duplicates == 0


def test_relearn_writes_a_new_version_and_alarms_follow_it(engine: Engine, marts: None) -> None:
    before = _scalar(engine, "SELECT max(version) FROM spc_control_limits")
    run_spc(engine, CONFIG, relearn=True)
    assert _scalar(engine, "SELECT max(version) FROM spc_control_limits") == before + 1
    stale = _scalar(
        engine,
        "SELECT count(*) FROM spc_alarms a JOIN spc_control_limits l USING (limit_id) "
        f"WHERE l.version <> {before + 1}",
    )
    assert stale == 0


def test_alarms_concentrate_inside_excursion_windows(engine: Engine, marts: None) -> None:
    """On a chamber's primary sensor, the alarm rate inside its injected step shift or drift
    is far above the rate elsewhere."""
    run_spc(engine, CONFIG)
    with engine.connect() as conn:  # closed, so no open transaction blocks teardown
        rates = conn.execute(
            text("""
            WITH pts AS (
                SELECT f.wafer_id, f.route_step_id, f.pass_no, l.limit_id,
                       EXISTS (SELECT 1 FROM excursions_ground_truth e
                               WHERE e.chamber_id = f.chamber_id
                                 AND e.parameter_id = f.parameter_id
                                 AND e.excursion_type IN ('step_shift', 'drift')
                                 AND f.measured_at >= e.start_time
                                 AND f.measured_at < e.end_time) AS inside
                FROM marts.fct_measurements f
                JOIN spc_control_limits l ON l.source = 'sensor' AND l.scope = 'chamber'
                 AND l.chamber_id = f.chamber_id AND l.parameter_id = f.parameter_id
                WHERE f.source = 'sensor' AND f.measured_at >= l.baseline_end
            )
            SELECT p.inside, avg((a.alarm_id IS NOT NULL)::int)::float AS rate, count(*) AS n
            FROM pts p
            LEFT JOIN spc_alarms a ON a.limit_id = p.limit_id AND a.wafer_id = p.wafer_id
             AND a.route_step_id = p.route_step_id AND a.pass_no = p.pass_no AND a.chart = 'we1'
            GROUP BY p.inside
            """)
        ).all()
    by_inside = {r.inside: r for r in rates}
    if True not in by_inside or by_inside[True].n < 30:
        pytest.skip("this dev seed has no sensor excursion after the baseline window")
    assert by_inside[True].rate > 5 * by_inside[False].rate
