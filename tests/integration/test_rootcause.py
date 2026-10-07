"""Root-cause evaluation on the dev fab: one ranking per excursion window, rerunnable."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, make_url, text

from waferlens.db.models import Base
from waferlens.ingest.loader import load
from waferlens.orchestration.resources import ROOT
from waferlens.rootcause.evaluate import evaluate_excursions
from waferlens.simulate.run import SimulationResult, write_parquet

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def marts(
    engine: Engine,
    test_db_url: str,
    dev: SimulationResult,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    path = tmp_path_factory.mktemp("rootcause")
    write_parquet(dev, path)
    load(path, engine)
    dbt = ROOT / "dbt"
    env = {**os.environ, "POSTGRES_DB": str(make_url(test_db_url).database)}
    subprocess.run(
        ["dbt", "build", "--select", "+fct_wafer_steps", "+fct_wafer_yield", "--exclude",
         "test_type:data", "--profiles-dir", str(dbt), "--project-dir", str(dbt)],
        check=True, capture_output=True, env=env,
    )  # fmt: skip
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS staging, intermediate, marts CASCADE"))


def _scalar(engine: Engine, sql: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def test_every_excursion_window_gets_a_ranking(engine: Engine, marts: None) -> None:
    report = evaluate_excursions(engine)
    excursions = _scalar(engine, "SELECT count(*) FROM excursions_ground_truth")
    assert report.windows == excursions
    ranked = _scalar(engine, "SELECT count(DISTINCT excursion_id) FROM rootcause_candidates")
    assert ranked >= excursions - 1  # a window right at the end may hold no sorted wafers
    gaps = _scalar(
        engine,
        "SELECT count(*) FROM (SELECT excursion_id FROM rootcause_candidates "
        "GROUP BY excursion_id HAVING min(suspect_rank) <> 1) g",
    )
    assert gaps == 0


def test_rerun_replaces_the_rankings(engine: Engine, marts: None) -> None:
    first = evaluate_excursions(engine)
    again = evaluate_excursions(engine)
    assert again.candidates == first.candidates
    assert _scalar(engine, "SELECT count(*) FROM rootcause_candidates") == again.candidates


def test_true_causes_rank_far_above_chance(engine: Engine, marts: None) -> None:
    evaluate_excursions(engine)
    median_rank = _scalar(
        engine,
        """
        SELECT percentile_disc(0.5) WITHIN GROUP (ORDER BY c.suspect_rank)
        FROM rootcause_candidates c
        JOIN excursions_ground_truth e USING (excursion_id)
        WHERE (c.factor_type = 'chamber' AND c.chamber_id = e.chamber_id AND e.recipe_id IS NULL)
           OR (c.factor_type = 'recipe' AND c.recipe_id = e.recipe_id)
        """,
    )
    candidates = _scalar(engine, "SELECT count(*) / count(DISTINCT excursion_id) "
                                 "FROM rootcause_candidates")  # fmt: skip
    assert median_rank <= candidates / 4  # random ranking would put the median near the middle
