"""Simulator output: matches the database schema, is internally consistent, carries the
injected signals, and is deterministic."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from tests.unit.simulate.conftest import frame
from waferlens.db import models as m
from waferlens.simulate.config import FabConfig, ProfileSpec
from waferlens.simulate.excursions import MINUTES_PER_DAY
from waferlens.simulate.master import SITES_MM
from waferlens.simulate.run import SimulationResult, simulate, write_parquet
from waferlens.simulate.wafer_maps import pattern_field

LOADER_DERIVED = {"wafer_bin_summary"}  # built from wafer_maps at load time (ADR-0003)


# --------------------------------------------------------------------------- schema contract


def assert_keys_hold(result: SimulationResult) -> None:
    """Every primary key is unique and every foreign key points at an existing row."""
    for name, table in m.Base.metadata.tables.items():
        if name in LOADER_DERIVED:
            continue
        df = frame(result, name)
        pk = [c.name for c in table.primary_key.columns]
        assert not df.duplicated(pk).any(), f"{name}: duplicate primary key {pk}"
        for fk in table.foreign_keys:
            child = df[fk.parent.name].dropna()
            parent = frame(result, fk.column.table.name)[fk.column.name]
            missing = set(child) - set(parent)
            assert not missing, f"{name}.{fk.parent.name}: {len(missing)} orphan values"


def test_outputs_every_table_the_loader_needs(dev: SimulationResult) -> None:
    assert set(dev.tables) == set(m.Base.metadata.tables) - LOADER_DERIVED


def test_columns_match_database_tables(dev: SimulationResult) -> None:
    for name in dev.tables:
        columns = [str(c) for c in frame(dev, name).columns]
        expected = [c.name for c in m.Base.metadata.tables[name].columns]
        assert sorted(columns) == sorted(expected), name


def test_keys_hold(dev: SimulationResult) -> None:
    assert_keys_hold(dev)


def test_check_constraints_hold(dev: SimulationResult) -> None:
    wafers = frame(dev, "wafers")
    assert wafers["slot"].between(1, 25).all()
    assert wafers["status"].isin(m.WAFER_STATUSES).all()
    assert frame(dev, "lots")["status"].isin(m.LOT_STATUSES).all()

    history = frame(dev, "wafer_step_history")
    assert (history["track_out"] >= history["track_in"]).all()

    events = frame(dev, "lot_events")
    assert events["event_type"].isin(m.LOT_EVENT_TYPES).all()
    splits = events[events["event_type"].isin(["split", "merge"])]
    assert splits["related_lot_id"].notna().all()

    plans = frame(dev, "metrology_plans")
    assert ((plans["lsl"] < plans["target"]) & (plans["target"] < plans["usl"])).all()

    metrology = frame(dev, "metrology_measurements")
    assert (np.hypot(metrology["site_x_mm"], metrology["site_y_mm"]) <= 150).all()

    truth = frame(dev, "excursions_ground_truth")
    assert (truth["end_time"] > truth["start_time"]).all()
    assert (truth["chamber_id"].notna() | truth["recipe_id"].notna()).all()


# --------------------------------------------------------------------------- consistency


def test_wafers_run_the_route_in_order(dev: SimulationResult) -> None:
    history = frame(dev, "wafer_step_history").merge(
        frame(dev, "route_steps")[["route_step_id", "sequence_no"]], on="route_step_id"
    )
    history = history.sort_values(["wafer_id", "sequence_no", "pass_no"])
    nxt = history.groupby("wafer_id")["track_in"].shift(-1)
    assert (nxt.dropna() >= history.loc[nxt.notna(), "track_out"]).all()


def test_split_lots_keep_genealogy(signal_run: SimulationResult) -> None:
    lots = frame(signal_run, "lots")
    children = lots[lots["parent_lot_id"].notna()]
    assert len(children) > 0
    history = frame(signal_run, "wafer_step_history")
    for child in children.to_dict("records"):
        wafers = frame(signal_run, "wafers")
        moved = wafers.loc[wafers["lot_id"] == child["lot_id"], "wafer_id"]
        seen = set(history.loc[history["wafer_id"].isin(moved), "lot_id"])
        assert seen <= {child["lot_id"], child["parent_lot_id"]}
        assert child["parent_lot_id"] in seen  # processed in the parent before the split


def test_metrology_follows_the_sampling_plan(dev: SimulationResult, cfg: FabConfig) -> None:
    metrology = frame(dev, "metrology_measurements")
    history = frame(dev, "wafer_step_history").drop_duplicates(
        ["wafer_id", "route_step_id"], keep="last"
    )
    measured = metrology.merge(history[["wafer_id", "route_step_id", "lot_id"]],
                               on=["wafer_id", "route_step_id"])  # fmt: skip
    per_lot = measured.groupby(["lot_id", "route_step_id"])["wafer_id"].nunique()
    assert per_lot.max() <= cfg.measurement.metrology_wafers_per_lot
    sites = metrology.groupby(["wafer_id", "route_step_id", "parameter_id"]).size()
    assert (sites == len(SITES_MM)).all()
    after = metrology.merge(history[["wafer_id", "route_step_id", "track_out"]],
                            on=["wafer_id", "route_step_id"])  # fmt: skip
    assert (after["time"] > after["track_out"]).all()


def test_wafer_maps_match_product_geometry(dev: SimulationResult) -> None:
    maps = frame(dev, "wafer_maps").merge(frame(dev, "wafers"), on="wafer_id")
    lots = frame(dev, "lots")[["lot_id", "product_id"]]
    maps = maps.merge(lots, on="lot_id").merge(frame(dev, "products"), on="product_id")
    for row in maps.to_dict("records"):
        grid = np.array([np.asarray(r) for r in row["bin_map"]])
        assert grid.shape == (row["map_rows"], row["map_cols"])
        assert (grid > 0).sum() == row["gross_dies"]
        assert set(np.unique(grid)) <= {0, 1, 2, 3, 4, 5}
    assert (frame(dev, "wafers").set_index("wafer_id").loc[maps["wafer_id"], "status"]
            == "complete").all()  # fmt: skip


def test_yield_is_realistic(dev: SimulationResult, signal_run: SimulationResult) -> None:
    for run in (dev, signal_run):
        y = run.summary["yield_pct"]
        assert isinstance(y, dict)
        assert 80 <= y["median"] <= 95, y


# --------------------------------------------------------------------------- injected signals


def _sensor_z(run: SimulationResult, cfg: FabConfig) -> pd.DataFrame:
    readings = frame(run, "tool_sensor_readings").merge(
        frame(run, "parameters")[["parameter_id", "name"]], on="parameter_id"
    )
    specs = {s: spec for tt in cfg.tool_types.values() for s, spec in tt.sensors.items()}
    nominal = readings["name"].map({k: v.nominal for k, v in specs.items()})
    sigma = readings["name"].map({k: v.sigma for k, v in specs.items()})
    return readings.assign(z=(readings["value"] - nominal) / sigma)


def test_step_shifts_and_drifts_move_their_sensor(
    signal_run: SimulationResult, cfg: FabConfig
) -> None:
    z = _sensor_z(signal_run, cfg)
    truth = frame(signal_run, "excursions_ground_truth")
    checked = 0
    for ex in truth[truth["excursion_type"].isin(["step_shift", "drift"])].to_dict("records"):
        mine = z[(z["chamber_id"] == ex["chamber_id"]) & (z["parameter_id"] == ex["parameter_id"])]
        inside = mine["time"].between(ex["start_time"], ex["end_time"], inclusive="left")
        if inside.sum() < 30:
            continue
        expected = ex["magnitude_sigma"] * (0.5 if ex["excursion_type"] == "drift" else 1.0)
        shift = mine.loc[inside, "z"].mean() - mine.loc[~inside, "z"].mean()
        assert shift == pytest.approx(expected, abs=0.35), ex["description"]
        checked += 1
    assert checked >= 2


def test_recipe_change_is_used_during_its_window(signal_run: SimulationResult) -> None:
    truth = frame(signal_run, "excursions_ground_truth")
    changes = truth[truth["excursion_type"] == "recipe_change"]
    assert len(changes) > 0
    recipes = frame(signal_run, "recipes").set_index("recipe_id")
    history = frame(signal_run, "wafer_step_history")
    for ex in changes.to_dict("records"):
        step = recipes.loc[ex["recipe_id"], "route_step_id"]
        rows = history[history["route_step_id"] == step]
        inside = rows["track_in"].between(ex["start_time"], ex["end_time"], inclusive="left")
        assert (rows.loc[inside, "recipe_id"] == ex["recipe_id"]).all()
        assert (rows.loc[~inside, "recipe_id"] != ex["recipe_id"]).all()


def _fail_rate(bin_map: object) -> float:
    grid = np.array([np.asarray(row) for row in bin_map])  # type: ignore[attr-defined]
    return float((grid > 1).sum() / (grid > 0).sum())


def test_spatial_excursions_cost_yield_on_touched_wafers(signal_run: SimulationResult) -> None:
    truth = frame(signal_run, "excursions_ground_truth")
    history = frame(signal_run, "wafer_step_history")
    touched: set[int] = set()
    for ex in truth[truth["excursion_type"] == "spatial_pattern"].to_dict("records"):
        hit = (history["chamber_id"] == ex["chamber_id"]) & history["track_in"].between(
            ex["start_time"], ex["end_time"], inclusive="left"
        )
        touched |= set(history.loc[hit, "wafer_id"])
    maps = frame(signal_run, "wafer_maps")
    fail_rate = pd.Series([_fail_rate(g) for g in maps["bin_map"]], index=maps.index)
    is_touched = maps["wafer_id"].isin(touched)
    assert is_touched.sum() > 20
    assert fail_rate[is_touched].mean() > fail_rate[~is_touched].mean() + 0.03


@pytest.mark.parametrize(
    ("pattern", "inside", "outside"),
    [
        ("center", (0.0, 0.0), (0.9, 0.0)),
        ("edge_ring", (0.0, 0.93), (0.0, 0.0)),
        ("donut", (0.55, 0.0), (0.0, 0.0)),
    ],
)
def test_pattern_fields_peak_where_expected(
    pattern: str, inside: tuple[float, float], outside: tuple[float, float]
) -> None:
    x = np.array([inside[0], outside[0]])
    y = np.array([inside[1], outside[1]])
    field = pattern_field(pattern, x, y, np.random.default_rng(0))
    assert field[0] > 0.9
    assert field[1] < 0.1


def test_pattern_geometry_is_fixed_per_excursion() -> None:
    x, y = np.meshgrid(np.linspace(-1, 1, 30), np.linspace(-1, 1, 30))
    a = pattern_field("scratch", x.ravel(), y.ravel(), np.random.default_rng(5))
    b = pattern_field("scratch", x.ravel(), y.ravel(), np.random.default_rng(5))
    c = pattern_field("scratch", x.ravel(), y.ravel(), np.random.default_rng(6))
    np.testing.assert_array_equal(a, b)
    assert not np.allclose(a, c)


# --------------------------------------------------------------------------- determinism + IO


def _comparable(result: SimulationResult) -> dict[str, pd.DataFrame]:
    return {n: frame(result, n) for n in result.tables if n != "simulation_runs"}


def test_same_seed_gives_identical_output(cfg: FabConfig, dev: SimulationResult) -> None:
    again = _comparable(simulate(cfg, "dev", seed=42))
    for name, df in _comparable(dev).items():
        pd.testing.assert_frame_equal(df, again[name], obj=name)


def test_different_seed_gives_different_output(cfg: FabConfig, dev: SimulationResult) -> None:
    other = simulate(cfg, "dev", seed=43)
    assert not frame(dev, "lots")["start_time"].equals(frame(other, "lots")["start_time"])


def test_parquet_round_trip(dev: SimulationResult, tmp_path: Path) -> None:
    write_parquet(dev, tmp_path)
    assert (tmp_path / "manifest.json").exists()
    for name in dev.tables:
        back = pq.read_table(tmp_path / f"{name}.parquet").to_pandas()
        assert len(back) == len(frame(dev, name)), name
    maps = pq.read_table(tmp_path / "wafer_maps.parquet")
    assert maps.equals(dev.tables["wafer_maps"])


def test_everything_happens_inside_the_period(dev: SimulationResult, cfg: FabConfig) -> None:
    end = pd.Timestamp(cfg.start_date, tz="UTC") + pd.Timedelta(
        minutes=cfg.profiles["dev"].days * MINUTES_PER_DAY
    )
    for table, column in [("wafer_step_history", "track_out"), ("tool_sensor_readings", "time"),
                          ("metrology_measurements", "time"), ("lot_events", "event_time"),
                          ("wafer_maps", "tested_at")]:  # fmt: skip
        assert (frame(dev, table)[column] <= end).all(), table


@settings(
    max_examples=8, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(seed=st.integers(0, 2**32 - 1), lots=st.integers(1, 12), days=st.integers(3, 20))
def test_keys_hold_for_any_seed_and_size(cfg: FabConfig, seed: int, lots: int, days: int) -> None:
    profile = ProfileSpec(lots=lots, days=days, excursions=4, benign_recipe_changes=1)
    assert_keys_hold(simulate(cfg, profile, seed))


# --------------------------------------------------------------------------- config


def test_config_rejects_unknown_tool_type(cfg: FabConfig) -> None:
    data = cfg.model_dump()
    data["route"][0]["tool_type"] = "teleporter"
    with pytest.raises(ValidationError, match="unknown tool type teleporter"):
        FabConfig.model_validate(data)


def test_config_rejects_product_mix_not_summing_to_one(cfg: FabConfig) -> None:
    data = cfg.model_dump()
    data["products"][0]["mix"] = 0.9
    with pytest.raises(ValidationError, match="mix must sum to 1"):
        FabConfig.model_validate(data)


def test_cli_writes_profile_to_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from waferlens.simulate.__main__ import main

    monkeypatch.setattr("sys.argv", ["simulate", "--profile", "dev", "--out", str(tmp_path)])
    main()
    assert (tmp_path / "wafer_maps.parquet").exists()
    assert '"profile": "dev"' in capsys.readouterr().out
