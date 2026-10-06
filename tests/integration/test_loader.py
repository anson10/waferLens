"""Loader against the real database: completeness, derived bin counts, idempotency,
atomicity, sequences and schema integrity after the foreign-key drop/re-add."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from tests.conftest import frame
from waferlens.db.models import Base
from waferlens.ingest.contracts import ContractError
from waferlens.ingest.loader import LoadReport, load
from waferlens.simulate.run import SimulationResult, write_parquet

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def data_dir(dev: SimulationResult, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("dev")
    write_parquet(dev, path)
    return path


@pytest.fixture(scope="module")
def loaded(engine: Engine, data_dir: Path) -> Iterator[LoadReport]:
    report = load(data_dir, engine)
    yield report
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} CASCADE"))


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
            for t in Base.metadata.tables
        }


def test_every_row_is_loaded(engine: Engine, loaded: LoadReport, dev: SimulationResult) -> None:
    counts = _counts(engine)
    for name in dev.tables:
        assert counts[name] == len(frame(dev, name)), name
    assert loaded.rows["tool_sensor_readings"] == counts["tool_sensor_readings"]


def test_bin_summary_agrees_with_wafer_maps(
    engine: Engine, loaded: LoadReport, dev: SimulationResult
) -> None:
    maps = dev.tables["wafer_maps"]
    assert isinstance(maps, pa.Table)
    expected: dict[tuple[int, int], int] = {}
    wafer_ids = maps.column("wafer_id").to_numpy()
    for wafer_id, grid in zip(wafer_ids, maps.column("bin_map").to_pylist(), strict=True):
        codes, counts = np.unique(np.array(grid), return_counts=True)
        for code, n in zip(codes, counts, strict=True):
            if code > 0:
                expected[(int(wafer_id), int(code))] = int(n)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT wafer_id, bin_code, die_count FROM wafer_bin_summary"))
        actual = {(w, b): n for w, b, n in rows}
    assert actual == expected


def test_yield_view_matches_simulation(
    engine: Engine, loaded: LoadReport, dev: SimulationResult
) -> None:
    with engine.connect() as conn:
        mean = conn.execute(text("SELECT avg(yield_pct) FROM wafer_yield")).scalar_one()
    summary = dev.summary["yield_pct"]
    assert isinstance(summary, dict)
    assert float(mean) == pytest.approx(summary["mean"], abs=0.01)


def test_values_and_maps_round_trip_exactly(
    engine: Engine, loaded: LoadReport, dev: SimulationResult
) -> None:
    sensors = frame(dev, "tool_sensor_readings").sample(200, random_state=0)
    with engine.connect() as conn:
        for row in ({str(k): v for k, v in r.items()} for r in sensors.to_dict("records")):
            value = conn.execute(
                text("SELECT value FROM tool_sensor_readings WHERE time = :time AND "
                     "wafer_id = :wafer_id AND route_step_id = :route_step_id AND "
                     "parameter_id = :parameter_id"),
                row,
            ).scalar_one()  # fmt: skip
            assert value == row["value"]
        maps = frame(dev, "wafer_maps").head(20)
        for row in maps.to_dict("records"):
            stored = conn.execute(
                text("SELECT bin_map FROM wafer_maps WHERE wafer_id = :w"), {"w": row["wafer_id"]}
            ).scalar_one()
            assert stored == [list(r) for r in row["bin_map"]]


def test_sequences_continue_after_loaded_ids(engine: Engine, loaded: LoadReport) -> None:
    with engine.connect() as conn:
        top = conn.execute(text("SELECT max(event_id) FROM lot_events")).scalar_one()
        nxt = conn.execute(
            text("SELECT nextval(pg_get_serial_sequence('lot_events', 'event_id'))")
        ).scalar_one()
    assert nxt == top + 1


def test_foreign_keys_are_back_and_schema_unchanged(
    engine: Engine, loaded: LoadReport, alembic_cfg: Config
) -> None:
    expected = sum(len(t.foreign_key_constraints) for t in Base.metadata.tables.values())
    with engine.connect() as conn:
        actual = conn.execute(
            text("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid = "
                 "c.connamespace WHERE c.contype = 'f' AND n.nspname = 'public'")
        ).scalar_one()  # fmt: skip
    assert actual == expected
    command.check(alembic_cfg)


def test_loading_twice_gives_the_same_result(
    engine: Engine, loaded: LoadReport, data_dir: Path
) -> None:
    before = _counts(engine)
    load(data_dir, engine)
    assert _counts(engine) == before


def test_failed_load_leaves_previous_data_intact(
    engine: Engine, loaded: LoadReport, data_dir: Path, tmp_path: Path
) -> None:
    before = _counts(engine)
    broken = tmp_path / "broken"
    shutil.copytree(data_dir, broken)
    wafers = pq.read_table(broken / "wafers.parquet").to_pandas()
    wafers.loc[0, "lot_id"] = 999_999  # orphan: no such lot
    pq.write_table(pa.Table.from_pandas(wafers, preserve_index=False), broken / "wafers.parquet")

    # Skipping contracts, the database's own foreign key catches it when re-added.
    with pytest.raises(Exception, match="fk_wafers_lot_id_lots"):
        load(broken, engine, validate=False)
    assert _counts(engine) == before


def test_contracts_stop_bad_data_before_the_database(
    engine: Engine, loaded: LoadReport, data_dir: Path, tmp_path: Path
) -> None:
    before = _counts(engine)
    broken = tmp_path / "broken"
    shutil.copytree(data_dir, broken)
    lots = pq.read_table(broken / "lots.parquet").to_pandas()
    lots.loc[0, "status"] = None
    pq.write_table(pa.Table.from_pandas(lots, preserve_index=False), broken / "lots.parquet")
    with pytest.raises(ContractError, match=r"lots\.status"):
        load(broken, engine)
    assert _counts(engine) == before


def _fk_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM pg_constraint WHERE contype = 'f'")
        ).scalar_one()


def test_cli_loads_and_reports(
    engine: Engine,
    loaded: LoadReport,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from waferlens.ingest.__main__ import main

    monkeypatch.setattr("waferlens.ingest.loader.get_engine", lambda: engine)
    monkeypatch.setattr("sys.argv", ["ingest", "--data", str(data_dir)])
    main()
    out = capsys.readouterr().out
    assert "tool_sensor_readings" in out
    assert f"from {data_dir}" in out


def test_benchmark_leaves_data_and_constraints_unchanged(
    engine: Engine, loaded: LoadReport, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from waferlens.ingest.benchmark import METHODS, run_benchmark

    monkeypatch.setattr("waferlens.ingest.benchmark.get_engine", lambda: engine)
    before, fks = _counts(engine), _fk_count(engine)
    results = run_benchmark(data_dir, rows=300)
    assert [name for name, _, _ in results] == list(METHODS)
    assert all(n == 300 and seconds > 0 for _, n, seconds in results)
    assert _counts(engine) == before
    assert _fk_count(engine) == fks
