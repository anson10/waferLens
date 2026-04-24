"""Tests for analysis/queries.py and analysis/yield_analysis.py."""

from datetime import date, datetime

import pytest

from db.models import Lot, Measurement, ProcessStep, SpcFlag, Wafer, YieldRecord
from analysis.queries import (
    low_yield_wafers,
    measurements_for_step,
    spc_flag_counts,
    yield_by_lot,
    yield_by_node,
    yield_by_product,
)
from analysis.yield_analysis import defect_density_trend, low_yield_summary


@pytest.fixture
def populated(db_session):
    """Two lots, four wafers, one process step, four yield records, two spc flags."""
    db_session.add_all([
        Lot(lot_id=1, product="AA100", technology_node="28nm",
            start_date=date(2025, 10, 1), status="complete"),
        Lot(lot_id=2, product="BB200", technology_node="65nm",
            start_date=date(2025, 11, 1), status="active"),
    ])
    db_session.add_all([
        Wafer(wafer_id=1, lot_id=1, wafer_number=1, status="complete"),
        Wafer(wafer_id=2, lot_id=1, wafer_number=2, status="complete"),
        Wafer(wafer_id=3, lot_id=1, wafer_number=3, status="complete"),
        Wafer(wafer_id=4, lot_id=2, wafer_number=1, status="active"),
    ])
    db_session.add(
        ProcessStep(step_id=1, step_name="lithography", tool_id="LITHO-01",
                    layer="M1", sequence_order=1)
    )
    # Lot 1 yields: 80, 90, 100 → avg 90.0
    # Lot 2 yield:  60           → avg 60.0
    db_session.add_all([
        YieldRecord(record_id=1, wafer_id=1, die_count=250, pass_count=200, yield_pct=80.0, defect_density=0.20),
        YieldRecord(record_id=2, wafer_id=2, die_count=250, pass_count=225, yield_pct=90.0, defect_density=0.15),
        YieldRecord(record_id=3, wafer_id=3, die_count=250, pass_count=250, yield_pct=100.0, defect_density=0.05),
        YieldRecord(record_id=4, wafer_id=4, die_count=250, pass_count=150, yield_pct=60.0, defect_density=0.40),
    ])
    # Measurements for step filter test
    db_session.add_all([
        Measurement(measurement_id=1, wafer_id=1, step_id=1, parameter="cd_nm",
                    value=100.0, unit="nm", timestamp=datetime(2025, 10, 1, 8, 0)),
        Measurement(measurement_id=2, wafer_id=2, step_id=1, parameter="cd_nm",
                    value=101.0, unit="nm", timestamp=datetime(2025, 10, 1, 9, 0)),
        Measurement(measurement_id=3, wafer_id=1, step_id=1, parameter="thickness_nm",
                    value=50.0, unit="nm", timestamp=datetime(2025, 10, 1, 8, 0)),
    ])
    db_session.add_all([
        SpcFlag(flag_id=1, measurement_id=1, rule_violated="rule1_3sigma",
                flagged_at=datetime(2025, 10, 1)),
        SpcFlag(flag_id=2, measurement_id=2, rule_violated="rule1_3sigma",
                flagged_at=datetime(2025, 10, 1)),
        SpcFlag(flag_id=3, measurement_id=3, rule_violated="rule2_8consec",
                flagged_at=datetime(2025, 10, 1)),
    ])
    db_session.commit()
    return db_session


# --- yield_by_lot ---

def test_yield_by_lot_row_count(populated):
    rows = yield_by_lot(populated)
    assert len(rows) == 2


def test_yield_by_lot_values(populated):
    rows = yield_by_lot(populated)
    lot1 = next(r for r in rows if r["lot_id"] == 1)
    assert lot1["avg_yield_pct"] == pytest.approx(90.0)
    assert lot1["wafer_count"] == 3


def test_yield_by_lot_ordering(populated):
    rows = yield_by_lot(populated)
    assert rows[0]["lot_id"] == 1
    assert rows[1]["lot_id"] == 2


# --- yield_by_product ---

def test_yield_by_product_keys(populated):
    rows = yield_by_product(populated)
    products = {r["product"] for r in rows}
    assert products == {"AA100", "BB200"}


def test_yield_by_product_descending(populated):
    rows = yield_by_product(populated)
    # AA100 avg=90 > BB200 avg=60
    assert rows[0]["product"] == "AA100"
    assert rows[0]["avg_yield_pct"] == pytest.approx(90.0)


# --- yield_by_node ---

def test_yield_by_node_values(populated):
    rows = yield_by_node(populated)
    node_map = {r["technology_node"]: r["avg_yield_pct"] for r in rows}
    assert node_map["28nm"] == pytest.approx(90.0)
    assert node_map["65nm"] == pytest.approx(60.0)


# --- spc_flag_counts ---

def test_spc_flag_counts_total(populated):
    rows = spc_flag_counts(populated)
    total = sum(r["flag_count"] for r in rows)
    assert total == 3


def test_spc_flag_counts_ordering(populated):
    rows = spc_flag_counts(populated)
    # rule1_3sigma has 2 flags, rule2_8consec has 1 — descending order
    assert rows[0]["rule_violated"] == "rule1_3sigma"
    assert rows[0]["flag_count"] == 2


# --- measurements_for_step ---

def test_measurements_for_step_filter(populated):
    rows = measurements_for_step(populated, step_id=1, parameter="cd_nm")
    assert len(rows) == 2
    assert all(r["value"] in (100.0, 101.0) for r in rows)


def test_measurements_for_step_wrong_param(populated):
    rows = measurements_for_step(populated, step_id=1, parameter="nonexistent")
    assert rows == []


# --- low_yield_wafers ---

def test_low_yield_wafers_below_threshold(populated):
    rows = low_yield_wafers(populated, threshold=85.0)
    yields = [r["yield_pct"] for r in rows]
    assert all(y < 85.0 for y in yields)
    assert len(rows) == 2  # wafer 1 (80) and wafer 4 (60)


def test_low_yield_wafers_ordered_ascending(populated):
    rows = low_yield_wafers(populated, threshold=100.0)
    yields = [r["yield_pct"] for r in rows]
    assert yields == sorted(yields)


def test_low_yield_wafers_none_below(populated):
    rows = low_yield_wafers(populated, threshold=50.0)
    assert rows == []


# --- yield_analysis helpers ---

def test_defect_density_trend_sorted(populated):
    df = defect_density_trend(populated)
    assert list(df.columns) >= ["lot_id", "start_date", "avg_defect_density"]
    assert df["start_date"].is_monotonic_increasing


def test_low_yield_summary_returns_dataframe(populated):
    df = low_yield_summary(populated, threshold=85.0)
    assert len(df) == 2
    assert "yield_pct" in df.columns
