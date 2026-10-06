"""Data contracts accept the simulator's output and reject each kind of broken input."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

from tests.conftest import frame
from waferlens.ingest.contracts import ContractError, Tables, check_tables
from waferlens.ingest.loader import array_literals
from waferlens.simulate.run import SimulationResult


@pytest.fixture
def tables(dev: SimulationResult) -> Tables:
    return dict(dev.tables)  # shallow: each test replaces the table it breaks


def _replace_map(tables: Tables, wafer_pos: int, grid: list[list[int]]) -> None:
    maps = tables["wafer_maps"]
    assert isinstance(maps, pa.Table)
    bin_map = maps.column("bin_map").to_pylist()
    bin_map[wafer_pos] = grid
    tables["wafer_maps"] = maps.set_column(
        maps.schema.get_field_index("bin_map"), "bin_map",
        pa.array(bin_map, type=pa.list_(pa.list_(pa.int16()))),
    )  # fmt: skip


def test_simulator_output_passes(tables: Tables) -> None:
    check_tables(tables)


def _drop_table(t: Tables) -> None:
    del t["wafers"]


def _extra_column(t: Tables) -> None:
    t["lots"] = frame_of(t, "lots").assign(colour="blue")


def _null_in_required(t: Tables) -> None:
    df = frame_of(t, "wafers").copy()
    df["wafer_code"] = df["wafer_code"].astype(object)
    df.loc[0, "wafer_code"] = None
    t["wafers"] = df


def _duplicate_key(t: Tables) -> None:
    df = frame_of(t, "chambers")
    t["chambers"] = pd.concat([df, df.iloc[[0]]], ignore_index=True)


def _text_in_integer(t: Tables) -> None:
    t["wafers"] = frame_of(t, "wafers").assign(slot=lambda d: d["slot"].astype(str))


def _naive_timestamps(t: Tables) -> None:
    t["lots"] = frame_of(t, "lots").assign(
        start_time=lambda d: d["start_time"].dt.tz_localize(None)
    )


def _metrology_before_step(t: Tables) -> None:
    df = frame_of(t, "metrology_measurements")
    earlier = df["time"].where(df.index != 0, df["time"] - pd.Timedelta(days=30))
    t["metrology_measurements"] = df.assign(time=earlier)


def _sensor_on_wrong_chamber(t: Tables) -> None:
    df = frame_of(t, "tool_sensor_readings").copy()
    df.loc[0, "chamber_id"] = 40 if df.loc[0, "chamber_id"] != 40 else 1
    t["tool_sensor_readings"] = df


def _map_wrong_size(t: Tables) -> None:
    _replace_map(t, 0, [[1, 1], [1, 1]])


def _map_unknown_bin(t: Tables) -> None:
    maps = t["wafer_maps"]
    assert isinstance(maps, pa.Table)
    grid = np.array(maps.column("bin_map")[0].as_py())
    grid[grid == 1] = 7
    _replace_map(t, 0, grid.tolist())


def _map_for_unfinished_wafer(t: Tables) -> None:
    maps = t["wafer_maps"]
    assert isinstance(maps, pa.Table)
    first = maps.column("wafer_id")[0].as_py()
    df = frame_of(t, "wafers").copy()
    df.loc[df["wafer_id"] == first, "status"] = "active"
    t["wafers"] = df


def frame_of(t: Tables, name: str) -> pd.DataFrame:
    df = t[name]
    assert isinstance(df, pd.DataFrame)
    return df


BREAKAGES: dict[str, tuple[Callable[[Tables], None], str]] = {
    "missing table": (_drop_table, "missing tables"),
    "extra column": (_extra_column, "lots"),
    "null in required column": (_null_in_required, "wafers.wafer_code"),
    "duplicate primary key": (_duplicate_key, "chambers"),
    "text in integer column": (_text_in_integer, "wafers.slot"),
    "timestamps without timezone": (_naive_timestamps, "lots.start_time"),
    "metrology before the step finished": (_metrology_before_step, "measured before"),
    "sensor on the wrong chamber": (_sensor_on_wrong_chamber, "chamber differs"),
    "wafer map of the wrong size": (_map_wrong_size, "grid size"),
    "unknown bin code in a map": (_map_unknown_bin, "bin code not in sort_bins"),
    "map for an unfinished wafer": (_map_for_unfinished_wafer, "isn't complete"),
}


@pytest.mark.parametrize("case", BREAKAGES)
def test_broken_input_is_rejected(tables: Tables, case: str) -> None:
    breakage, message = BREAKAGES[case]
    breakage(tables)
    with pytest.raises(ContractError, match=message):
        check_tables(tables)


def test_original_tables_are_not_modified_by_breakage_tests(dev: SimulationResult) -> None:
    assert frame(dev, "wafers")["status"].isin(["active", "complete", "scrapped"]).all()
    check_tables(dict(dev.tables))


# --------------------------------------------------------------------------- array literals


def test_array_literals_match_postgres_syntax() -> None:
    grids = pa.array([[[0, 1], [2, 0]], [[1, 1, 1], [0, 3, 0], [1, 1, 1]]],
                     type=pa.list_(pa.list_(pa.int16())))  # fmt: skip
    assert list(array_literals(grids)) == [b"{{0,1},{2,0}}", b"{{1,1,1},{0,3,0},{1,1,1}}"]


def test_array_literals_reject_multi_digit_bins() -> None:
    grids = pa.array([[[0, 10]]], type=pa.list_(pa.list_(pa.int16())))
    with pytest.raises(ValueError, match="single-digit"):
        list(array_literals(grids))
