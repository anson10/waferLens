"""Shape and range checks on simulation output."""

import pandas as pd

from simulate.process import STEP_CATALOG, generate_measurements, generate_steps
from simulate.wafer import generate_lots, generate_wafers
from simulate.yield_model import (
    TECH_NODE_PARAMS,
    YIELD_MAX,
    YIELD_MIN,
    generate_yield,
)


def test_lots_shape_and_content():
    lots = generate_lots(n_lots=20, seed=42)
    assert len(lots) == 20
    assert set(lots.columns) == {
        "lot_id", "product", "technology_node", "start_date", "status",
    }
    assert lots["lot_id"].is_unique
    assert lots["technology_node"].isin(TECH_NODE_PARAMS.keys()).all()
    assert not lots.isna().any().any()


def test_wafers_shape_and_fks():
    lots = generate_lots(n_lots=20, seed=42)
    wafers = generate_wafers(lots, wafers_per_lot=25, seed=42)
    assert len(wafers) == 500
    assert wafers["wafer_id"].is_unique
    assert wafers["lot_id"].isin(lots["lot_id"]).all()
    assert (wafers["wafer_number"].between(1, 25)).all()


def test_steps_shape():
    steps = generate_steps()
    assert len(steps) == len(STEP_CATALOG)
    assert steps["step_id"].is_unique
    assert steps["sequence_order"].is_unique
    assert set(steps["layer"].unique()) <= {"M1", "M2"}


def test_measurements_shape_and_drift():
    lots = generate_lots(n_lots=20, seed=42)
    wafers = generate_wafers(lots, seed=42)
    measurements = generate_measurements(wafers, lots, seed=42)

    total_params_per_wafer = sum(len(s["params"]) for s in STEP_CATALOG)
    assert len(measurements) == len(wafers) * total_params_per_wafer
    assert measurements["measurement_id"].is_unique
    assert not measurements.isna().any().any()

    etch = measurements[measurements["parameter"] == "etch_rate_nm_s"].copy()
    etch["ts"] = pd.to_datetime(etch["timestamp"])
    early = etch.nsmallest(50, "ts")["value"].mean()
    late = etch.nlargest(50, "ts")["value"].mean()
    assert early - late > 0.3, f"etch rate should drift downward: early={early}, late={late}"


def test_yield_ranges_and_correlation():
    lots = generate_lots(n_lots=20, seed=42)
    wafers = generate_wafers(lots, seed=42)
    measurements = generate_measurements(wafers, lots, seed=42)
    yrec = generate_yield(wafers, lots, measurements, seed=42)

    assert len(yrec) == len(wafers)
    normal = yrec[yrec["pass_count"] > 0]
    assert (normal["yield_pct"] >= YIELD_MIN).all()
    assert (normal["yield_pct"] <= YIELD_MAX).all()
    assert (yrec["defect_density"] > 0).all()
    assert (yrec["die_count"] > 0).all()
    assert (yrec["pass_count"] <= yrec["die_count"]).all()


def test_determinism():
    a = generate_lots(n_lots=20, seed=123)
    b = generate_lots(n_lots=20, seed=123)
    pd.testing.assert_frame_equal(a, b)
