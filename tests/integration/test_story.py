"""Excursion stories on the dev fab: every query runs against the marts, every excursion renders."""

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
from waferlens.rootcause.story import load_story, render
from waferlens.simulate.run import SimulationResult, write_parquet

pytestmark = pytest.mark.integration

STORY_MARTS = ["+dim_excursion", "+fct_excursion_impact", "+fct_root_cause_eval",
               "+fct_root_cause_candidates", "+fct_excursion_detection", "+fct_spc_alarms",
               "+fct_pattern_detection", "+fct_wafer_pattern", "+fct_wafer_steps"]  # fmt: skip


@pytest.fixture(scope="module")
def marts(
    engine: Engine,
    test_db_url: str,
    dev: SimulationResult,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    path = tmp_path_factory.mktemp("story")
    write_parquet(dev, path)
    load(path, engine)
    dbt = ROOT / "dbt"
    env = {**os.environ, "POSTGRES_DB": str(make_url(test_db_url).database)}

    def build(*select: str) -> None:
        subprocess.run(
            ["dbt", "build", "--select", *select, "--exclude", "test_type:data",
             "--profiles-dir", str(dbt), "--project-dir", str(dbt)],
            check=True, capture_output=True, env=env,
        )  # fmt: skip

    build("+fct_wafer_steps", "+fct_wafer_yield")  # commonality reads these
    evaluate_excursions(engine)
    build(*STORY_MARTS)
    yield
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS staging, intermediate, marts CASCADE"))


def test_every_excursion_tells_a_story(engine: Engine, marts: None) -> None:
    with engine.connect() as conn:
        ids = (
            conn.execute(text("SELECT excursion_id FROM marts.dim_excursion ORDER BY 1"))
            .scalars()
            .all()
        )
    assert ids
    stories = [load_story(engine, i) for i in ids]
    doc = render(stories)
    assert doc.count("## Excursion ") == len(ids)
    ranked = [s for s in stories if s.excursion["true_rank"] is not None]
    assert ranked, "commonality ranked no excursion"
    for s in ranked:
        assert any(row["is_true_cause"] for row in s.suspects)  # the true cause is always listed


def test_an_unknown_excursion_is_an_error(engine: Engine, marts: None) -> None:
    with pytest.raises(ValueError, match="no excursion"):
        load_story(engine, 99_999)
