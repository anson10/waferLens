"""Tests for ingest/loader.py — verifies CSV rows land in correct tables."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ingest.loader import (
    load_lots,
    load_measurements,
    load_process_steps,
    load_wafers,
    load_yield_records,
)
from db.models import Lot, Measurement, ProcessStep, Wafer, YieldRecord


@pytest.fixture
def lots_df():
    return pd.DataFrame([
        {"lot_id": 1, "product": "AA100", "technology_node": "28nm",
         "start_date": "2025-10-01", "status": "complete"},
        {"lot_id": 2, "product": "BB200", "technology_node": "65nm",
         "start_date": "2025-11-01", "status": "active"},
    ])


@pytest.fixture
def wafers_df():
    return pd.DataFrame([
        {"wafer_id": 1, "lot_id": 1, "wafer_number": 1, "status": "complete"},
        {"wafer_id": 2, "lot_id": 1, "wafer_number": 2, "status": "complete"},
        {"wafer_id": 3, "lot_id": 2, "wafer_number": 1, "status": "active"},
    ])


@pytest.fixture
def steps_df():
    return pd.DataFrame([
        {"step_id": 1, "step_name": "lithography", "tool_id": "LITHO-01",
         "layer": "M1", "sequence_order": 1},
    ])


@pytest.fixture
def measurements_df():
    return pd.DataFrame([
        {"measurement_id": 1, "wafer_id": 1, "step_id": 1,
         "parameter": "cd_nm", "value": 100.5, "unit": "nm",
         "timestamp": "2025-10-01 08:00:00"},
        {"measurement_id": 2, "wafer_id": 2, "step_id": 1,
         "parameter": "cd_nm", "value": 101.2, "unit": "nm",
         "timestamp": "2025-10-01 09:00:00"},
    ])


@pytest.fixture
def yield_df():
    return pd.DataFrame([
        {"record_id": 1, "wafer_id": 1, "die_count": 250,
         "pass_count": 220, "yield_pct": 88.0, "defect_density": 0.15},
        {"record_id": 2, "wafer_id": 2, "die_count": 250,
         "pass_count": 210, "yield_pct": 84.0, "defect_density": 0.20},
    ])


def test_load_lots_row_count(db_session, lots_df):
    load_lots(db_session, lots_df)
    db_session.commit()
    assert db_session.query(Lot).count() == 2


def test_load_lots_types(db_session, lots_df):
    load_lots(db_session, lots_df)
    db_session.commit()
    lot = db_session.query(Lot).filter_by(lot_id=1).one()
    assert lot.product == "AA100"
    assert lot.technology_node == "28nm"
    assert isinstance(lot.start_date, date)
    assert lot.status == "complete"


def test_load_wafers_fk(db_session, lots_df, wafers_df):
    load_lots(db_session, lots_df)
    load_wafers(db_session, wafers_df)
    db_session.commit()
    assert db_session.query(Wafer).count() == 3
    wafer = db_session.query(Wafer).filter_by(wafer_id=1).one()
    assert wafer.lot_id == 1


def test_load_process_steps(db_session, steps_df):
    load_process_steps(db_session, steps_df)
    db_session.commit()
    step = db_session.query(ProcessStep).filter_by(step_id=1).one()
    assert step.tool_id == "LITHO-01"
    assert step.sequence_order == 1


def test_load_measurements_types(db_session, lots_df, wafers_df, steps_df, measurements_df):
    load_lots(db_session, lots_df)
    load_wafers(db_session, wafers_df)
    load_process_steps(db_session, steps_df)
    load_measurements(db_session, measurements_df)
    db_session.commit()
    assert db_session.query(Measurement).count() == 2
    m = db_session.query(Measurement).filter_by(measurement_id=1).one()
    assert m.parameter == "cd_nm"
    assert isinstance(m.value, float)


def test_load_yield_records(db_session, lots_df, wafers_df, yield_df):
    load_lots(db_session, lots_df)
    load_wafers(db_session, wafers_df)
    load_yield_records(db_session, yield_df)
    db_session.commit()
    assert db_session.query(YieldRecord).count() == 2
    yr = db_session.query(YieldRecord).filter_by(wafer_id=1).one()
    assert yr.yield_pct == pytest.approx(88.0)


def test_real_csvs_load(db_session):
    """Smoke test: real CSVs load without error and row counts match."""
    from ingest.loader import run
    from unittest.mock import patch
    from db.session import get_session
    from contextlib import contextmanager

    @contextmanager
    def mock_session():
        yield db_session

    with patch("ingest.loader.get_session", mock_session):
        counts = run(data_dir=Path("data"), clear=False)

    assert counts["lots"] == 20
    assert counts["wafers"] == 500
    assert counts["measurements"] == 6000
