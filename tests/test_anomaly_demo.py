"""Confirms the anomaly-injection demo actually demonstrates SPC catching a drift."""

from analysis.anomaly_demo import _build_measurements, _seed_db
from analysis.spc import run_spc


def test_in_control_series_raises_no_flags():
    session = _seed_db(_build_measurements(drifted=False))
    assert run_spc(session) == 0


def test_drifted_series_raises_flags():
    session = _seed_db(_build_measurements(drifted=True))
    assert run_spc(session) > 0
