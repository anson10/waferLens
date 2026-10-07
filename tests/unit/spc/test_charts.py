"""Control charts on hand-made sequences, and calibration against theory."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from waferlens.spc.charts import (
    cusum,
    ewma,
    hotelling_t2,
    phase1_limits,
    t2_limits,
    western_electric,
)


def _flags(z: list[float], rule: str) -> list[int]:
    return np.flatnonzero(western_electric(np.array(z, dtype=float))[rule]).tolist()


def test_we1_flags_one_point_beyond_3_sigma() -> None:
    assert _flags([0, 0.5, 4.0, 0, -3.5], "we1") == [2, 4]


def test_we2_flags_the_second_of_two_in_three_beyond_2_sigma() -> None:
    assert _flags([0, 2.5, 0.1, 2.2, 0], "we2") == [3]
    assert _flags([2.5, 0, -2.5], "we2") == []  # opposite sides don't count


def test_we3_flags_four_of_five_beyond_1_sigma() -> None:
    assert _flags([1.5, 1.2, 0.3, 1.1, 1.4, 0], "we3") == [4]


def test_we4_flags_eight_in_a_row_on_one_side() -> None:
    z = [0.2] * 10
    assert _flags(z, "we4") == [7, 8, 9]
    assert _flags([0.5, -0.5] * 10, "we4") == []


def test_no_rule_fires_on_a_quiet_alternating_series() -> None:
    rules = western_electric(np.tile([0.5, -0.5], 50))
    assert not any(hit.any() for hit in rules.values())


def test_ewma_catches_a_small_shift_that_we1_misses() -> None:
    rng = np.random.default_rng(1)
    z = np.r_[rng.normal(0, 1, 100), rng.normal(1.0, 1, 100)]  # +1 sigma shift at 100
    _, signal = ewma(z)
    first = np.flatnonzero(signal[100:])
    assert first.size > 0
    assert first[0] < 30
    assert western_electric(z)["we1"][100:].sum() < 5


def test_cusum_detects_a_sustained_shift_and_resets_after_each_signal() -> None:
    z = np.r_[np.zeros(20), np.full(30, 1.5)]
    upper, _, up, down = cusum(z)
    signals = np.flatnonzero(up)
    assert signals[0] == 20 + 5  # 1.5 - 0.5 = 1 per point, exceeds h = 5 on the sixth
    assert np.all(np.diff(signals) == 6)  # restarts from 0, signals again 6 points later
    assert upper[signals[0] + 1] == pytest.approx(1.0)
    assert not down.any()


def test_hotelling_t2_catches_a_broken_correlation_univariate_charts_miss() -> None:
    rng = np.random.default_rng(2)
    cov = np.array([[1.0, 0.9], [0.9, 1.0]])
    baseline = rng.multivariate_normal([0, 0], cov, 500)
    limits = t2_limits(baseline)
    assert limits is not None
    odd = np.array([[1.8, -1.8]])  # each within 2 sigma, but against the 0.9 correlation
    stat, hit = hotelling_t2(odd, limits)
    assert hit.all()
    assert not western_electric(odd[0])["we1"].any()
    assert stat[0] > limits.limit


def test_t2_limits_need_enough_rows() -> None:
    assert t2_limits(np.zeros((5, 2))) is None


def test_phase1_limits_resist_outliers_and_slow_drift() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(100, 2, 300) + np.linspace(0, 6, 300)  # 3-sigma drift over the baseline
    x[[10, 50, 90]] = [160, 40, 170]
    limits = phase1_limits(x)
    assert limits is not None
    assert limits.sigma == pytest.approx(2, rel=0.15)  # sample std would be ~2.9 here
    assert limits.n == 297  # the three outliers trimmed


def test_phase1_limits_need_ten_points() -> None:
    assert phase1_limits(np.arange(9.0)) is None


@settings(max_examples=6, deadline=None)
@given(seed=st.integers(0, 2**32 - 1))
@example(seed=26)  # found by hypothesis: WE4 at 0.66%, the lowest of 300 measured seeds
def test_in_control_false_alarm_rates_match_theory(seed: int) -> None:
    """Per-point alarm rates on 200k in-control points: WE1 2 x P(Z > 3) = 0.27%;
    WE4 2 x 0.5^8 = 0.78%; CUSUM k=0.5, h=5 two-sided ARL ~465 → ~0.21%.

    Tolerances are 5 standard deviations of each rate, measured over 300 seeds
    (WE1 sd 0.012%, WE4 0.033%, CUSUM 0.010%). WE4 spreads most because its alarms
    cluster: one long run on one side flags every point after the eighth.
    """
    z = np.random.default_rng(seed).normal(0, 1, 200_000)
    rules = western_electric(z)
    assert rules["we1"].mean() == pytest.approx(0.0027, abs=0.0006)
    assert rules["we4"].mean() == pytest.approx(0.0078, abs=0.0016)
    _, _, up, down = cusum(z)
    assert (up | down).mean() == pytest.approx(0.00214, abs=0.0005)
