"""Tests for ingest/validate.py — the pandera data-quality gate."""

import pandas as pd
import pandera.pandas as pa
import pytest

from ingest.validate import check_referential_integrity, validate_all, yield_records_schema


@pytest.fixture
def good_dfs():
    lots_df = pd.DataFrame([
        {"lot_id": 1, "product": "AA100", "technology_node": "28nm",
         "start_date": "2025-10-01", "status": "active"},
    ])
    wafers_df = pd.DataFrame([
        {"wafer_id": 1, "lot_id": 1, "wafer_number": 1, "status": "active"},
    ])
    steps_df = pd.DataFrame([
        {"step_id": 1, "step_name": "etch", "tool_id": "ETCH-01",
         "layer": "M1", "sequence_order": 1},
    ])
    measurements_df = pd.DataFrame([
        {"measurement_id": 1, "wafer_id": 1, "step_id": 1, "parameter": "cd_nm",
         "value": 100.0, "unit": "nm", "timestamp": "2025-10-01 08:00:00"},
    ])
    yield_df = pd.DataFrame([
        {"record_id": 1, "wafer_id": 1, "die_count": 250,
         "pass_count": 200, "yield_pct": 80.0, "defect_density": 0.2},
    ])
    return lots_df, wafers_df, steps_df, measurements_df, yield_df


def test_validate_all_passes_on_clean_data(good_dfs):
    validate_all(*good_dfs)


def test_yield_pct_out_of_range_fails():
    bad = pd.DataFrame([
        {"record_id": 1, "wafer_id": 1, "die_count": 250,
         "pass_count": 200, "yield_pct": 145.0, "defect_density": 0.2},
    ])
    with pytest.raises(pa.errors.SchemaError):
        yield_records_schema.validate(bad)


def test_negative_defect_density_fails():
    bad = pd.DataFrame([
        {"record_id": 1, "wafer_id": 1, "die_count": 250,
         "pass_count": 200, "yield_pct": 80.0, "defect_density": -0.1},
    ])
    with pytest.raises(pa.errors.SchemaError):
        yield_records_schema.validate(bad)


def test_orphaned_wafer_lot_fk_fails(good_dfs):
    lots_df, wafers_df, steps_df, measurements_df, yield_df = good_dfs
    wafers_df = wafers_df.copy()
    wafers_df.loc[0, "lot_id"] = 999
    with pytest.raises(ValueError, match="missing lot_id"):
        check_referential_integrity(wafers_df, lots_df, measurements_df, yield_df, steps_df)


def test_pass_count_exceeds_die_count_fails(good_dfs):
    lots_df, wafers_df, steps_df, measurements_df, yield_df = good_dfs
    yield_df = yield_df.copy()
    yield_df.loc[0, "pass_count"] = 999
    with pytest.raises(ValueError, match="pass_count > die_count"):
        check_referential_integrity(wafers_df, lots_df, measurements_df, yield_df, steps_df)


def test_orphaned_measurement_wafer_fk_fails(good_dfs):
    lots_df, wafers_df, steps_df, measurements_df, yield_df = good_dfs
    measurements_df = measurements_df.copy()
    measurements_df.loc[0, "wafer_id"] = 999
    with pytest.raises(ValueError, match="measurements reference missing wafer_id"):
        check_referential_integrity(wafers_df, lots_df, measurements_df, yield_df, steps_df)
