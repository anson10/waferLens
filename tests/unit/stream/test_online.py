"""Real-time SPC raises exactly the batch engine's EWMA and CUSUM alarms, survives restarts
and ignores replays."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from waferlens.spc import charts
from waferlens.stream.events import SensorReading
from waferlens.stream.online import Limits, SeriesState, is_new, update

T0 = datetime(2026, 3, 1, tzinfo=UTC)
LIMITS = Limits(limit_id=7, center=100.0, sigma=2.0, baseline_end=T0)


def _run(values: np.ndarray, state: SeriesState | None = None, start: int = 0):
    state = state or SeriesState(limit_id=7)
    ewma_hits, cusum_hits = [], []
    for i, v in enumerate(values, start=start):
        state, alarms = update(state, LIMITS, float(v), T0 + timedelta(minutes=i), f"e{i:06d}")
        for a in alarms:
            (ewma_hits if a.chart == "ewma" else cusum_hits).append(i)
    return state, ewma_hits, cusum_hits


@settings(max_examples=60, deadline=None)
@given(seed=st.integers(0, 10_000), shift=st.floats(-3, 3), at=st.integers(0, 300))
def test_online_alarms_equal_the_batch_charts(seed: int, shift: float, at: int) -> None:
    rng = np.random.default_rng(seed)
    z = rng.normal(size=400)
    z[at:] += shift
    values = LIMITS.center + LIMITS.sigma * z
    _, ewma_hits, cusum_hits = _run(values)
    _, ewma_signal = charts.ewma(z)
    _, _, up, down = charts.cusum(z)
    assert ewma_hits == np.flatnonzero(ewma_signal).tolist()
    assert cusum_hits == np.flatnonzero(up | down).tolist()


def test_a_restart_from_saved_state_changes_nothing() -> None:
    values = LIMITS.center + LIMITS.sigma * np.random.default_rng(3).normal(1.0, 1, 300)
    _, ewma_all, cusum_all = _run(values)
    state, ewma_a, cusum_a = _run(values[:137])
    _, ewma_b, cusum_b = _run(values[137:], state=state, start=137)  # state as reloaded from DB
    assert ewma_a + ewma_b == ewma_all
    assert cusum_a + cusum_b == cusum_all


def test_baseline_points_are_not_charted() -> None:
    state = SeriesState(limit_id=7)
    state, alarms = update(state, LIMITS, 1e6, T0 - timedelta(days=1), "early")
    assert alarms == []
    assert state.n == 0
    assert state.last_event_id == "early"


def test_relearned_limits_restart_the_charts() -> None:
    state = SeriesState(limit_id=6, n=50, ewma=2.5, cusum_up=4.0)
    state, _ = update(state, LIMITS, LIMITS.center, T0, "x")
    assert (state.limit_id, state.n, state.cusum_up) == (7, 1, 0.0)


def test_replays_are_recognised() -> None:
    state = SeriesState(limit_id=7, last_measured_at=T0, last_event_id="w5")
    assert not is_new(state, T0 - timedelta(seconds=1), "w9")
    assert not is_new(state, T0, "w5")
    assert is_new(state, T0, "w6")  # same timestamp, later in the stable order
    assert is_new(state, T0 + timedelta(seconds=1), "w1")


def test_event_round_trip_and_unknown_versions_are_rejected() -> None:
    import pytest
    from pydantic import ValidationError

    e = SensorReading(measured_at=T0, wafer_id=1, route_step_id=2, parameter_id=3,
                      chamber_id=4, value=1.5, produced_at=T0)  # fmt: skip
    raw = e.to_bytes()
    assert b'"schema":"waferlens.sensor_reading/v1"' in raw
    assert SensorReading.from_bytes(raw) == e
    assert e.key == b"4"
    with pytest.raises(ValidationError):
        SensorReading.from_bytes(raw.replace(b"/v1", b"/v2"))
