"""Tests for analysis/spc.py — each Western Electric rule, pass and no-flag cases."""

from datetime import datetime

import numpy as np
import pytest

from analysis.spc import rule1, rule2, rule3, rule4, check_series, run_spc
from db.models import Lot, Measurement, ProcessStep, SpcFlag, Wafer


MEAN = 100.0
STD = 5.0


# --- Rule 1: 1 point beyond 3σ ---

def test_rule1_flags_outlier():
    values = np.array([MEAN] * 9 + [MEAN + 4 * STD])
    flags = rule1(values, MEAN, STD)
    assert flags[-1] is np.bool_(True)
    assert flags[:-1].sum() == 0


def test_rule1_no_flag_within_bounds():
    values = np.array([MEAN + 2 * STD] * 10)
    flags = rule1(values, MEAN, STD)
    assert flags.sum() == 0


# --- Rule 2: 8 consecutive on same side ---

def test_rule2_flags_8_above():
    values = np.array([MEAN + 1] * 8 + [MEAN - 1, MEAN - 1])
    flags = rule2(values, MEAN)
    assert flags[:8].all()


def test_rule2_no_flag_alternating():
    values = np.array([MEAN + 1, MEAN - 1] * 5)
    flags = rule2(values, MEAN)
    assert flags.sum() == 0


def test_rule2_exactly_8_flags():
    values = np.array([MEAN - 1] * 8)
    flags = rule2(values, MEAN)
    assert flags.sum() == 8


# --- Rule 3: 6 points continuously increasing or decreasing ---

def test_rule3_flags_increasing():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 3.0, 3.0])
    flags = rule3(values)
    assert flags[:6].all()
    assert not flags[6]


def test_rule3_flags_decreasing():
    values = np.array([6.0, 5.0, 4.0, 3.0, 2.0, 1.0])
    flags = rule3(values)
    assert flags.all()


def test_rule3_no_flag_flat():
    values = np.array([MEAN] * 8)
    flags = rule3(values)
    assert flags.sum() == 0


def test_rule3_no_flag_short_trend():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 4.0])
    flags = rule3(values)
    assert flags.sum() == 0


# --- Rule 4: 2 of 3 beyond 2σ same side ---

def test_rule4_flags_2of3_above():
    values = np.array([MEAN + 3 * STD, MEAN + 3 * STD, MEAN, MEAN, MEAN])
    flags = rule4(values, MEAN, STD)
    assert flags[0] and flags[1]


def test_rule4_no_flag_opposite_sides():
    # zeros between each extreme ensure no window has 2 on the same side
    values = np.array([MEAN + 3 * STD, MEAN, MEAN - 3 * STD, MEAN, MEAN + 3 * STD, MEAN, MEAN - 3 * STD])
    flags = rule4(values, MEAN, STD)
    assert flags.sum() == 0


def test_rule4_no_flag_within_2sigma():
    values = np.array([MEAN + 1.5 * STD] * 5)
    flags = rule4(values, MEAN, STD)
    assert flags.sum() == 0


# --- check_series integration ---

def test_check_series_returns_violations():
    # 9 identical points above mean triggers rule2; verifies check_series returns violations
    ids = list(range(10))
    values = [MEAN + STD] * 9 + [MEAN - STD]
    violations = check_series(ids, values)
    assert len(violations) > 0


def test_check_series_zero_std_returns_empty():
    ids = list(range(5))
    values = [MEAN] * 5
    assert check_series(ids, values) == []


# --- run_spc integration ---

def test_spc_main_runs(db_session):
    """main() clears spc_flags then re-runs SPC — smoke test via mock session."""
    from unittest.mock import patch
    from contextlib import contextmanager
    from analysis.spc import main

    @contextmanager
    def mock_session():
        yield db_session

    with patch("db.session.get_session", mock_session):
        main()  # should not raise; DB is empty so 0 flags written

    assert db_session.query(SpcFlag).count() == 0


def test_run_spc_writes_flags(db_session):
    """run_spc groups measurements by (step, parameter) and persists SpcFlag rows."""
    db_session.add(Lot(lot_id=1, product="X1", technology_node="28nm",
                       start_date=datetime(2025, 1, 1).date(), status="complete"))
    db_session.add(Wafer(wafer_id=1, lot_id=1, wafer_number=1, status="complete"))
    db_session.add(ProcessStep(step_id=1, step_name="etch", tool_id="ETCH-01",
                               layer="M1", sequence_order=1))
    # 9 values above mean + 1 below → triggers rule2 (8 consecutive same side)
    base = datetime(2025, 1, 1, 8, 0)
    for i in range(9):
        db_session.add(Measurement(
            measurement_id=i + 1, wafer_id=1, step_id=1,
            parameter="cd_nm", value=105.0,
            unit="nm", timestamp=base.replace(hour=8 + i),
        ))
    db_session.add(Measurement(
        measurement_id=10, wafer_id=1, step_id=1,
        parameter="cd_nm", value=95.0,
        unit="nm", timestamp=base.replace(hour=18),
    ))
    db_session.commit()

    n = run_spc(db_session)
    assert n > 0
    assert db_session.query(SpcFlag).count() == n
