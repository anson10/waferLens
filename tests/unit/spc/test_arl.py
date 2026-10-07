"""ARL harness: the batch charts match the ones SPC runs, and the results match the books."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from waferlens.spc import arl, charts
from waferlens.spc.report import arl_table, detection_markdown, published_check, render


def _first_1d(hit: np.ndarray) -> int:
    idx = np.flatnonzero(hit)
    return int(idx[0]) if idx.size else -1


@pytest.fixture(scope="module")
def series() -> np.ndarray:
    rng = np.random.default_rng(5)
    return rng.standard_normal((60, 400)) + rng.uniform(0, 1.5, (60, 1))


def test_batch_charts_match_the_charts_spc_runs(series: np.ndarray) -> None:
    for row, z in enumerate(series):
        rules = charts.western_electric(z)
        assert arl.shewhart(series)[row] == _first_1d(rules["we1"])
        any_rule = rules["we1"] | rules["we2"] | rules["we3"] | rules["we4"]
        assert arl.western_electric_any(series)[row] == _first_1d(any_rule)
        assert arl.ewma(series)[row] == _first_1d(charts.ewma(z)[1])
        _, _, up, down = charts.cusum(z)
        assert arl.cusum(series)[row] == _first_1d(up | down)  # first signal precedes any reset


@pytest.mark.parametrize(
    ("detector", "shift", "published", "rel"),
    [
        (arl.shewhart, 0.0, 370.4, 0.12),
        (arl.shewhart, 1.0, 43.9, 0.08),
        (arl.cusum, 0.0, 465.0, 0.12),
        (arl.cusum, 1.0, 10.4, 0.05),
    ],
)
def test_simulated_arl_matches_published_tables(
    detector: arl.Detector, shift: float, published: float, rel: float
) -> None:
    z = np.random.default_rng(9).standard_normal((1500, 4000)) + shift
    lengths, censored = arl.run_lengths(detector, z)
    assert censored < 5
    assert lengths.mean() == pytest.approx(published, rel=rel)


def test_t2_with_known_parameters_false_alarms_like_a_3_sigma_chart() -> None:
    rows = arl.multivariate_arl([0.0], runs=1500, horizon=4000)
    t2 = next(r for r in rows if r.chart.startswith("Hotelling"))
    each = next(r for r in rows if r.chart.startswith("Shewhart on each"))
    assert t2.arl == pytest.approx(370, rel=0.12)
    assert each.arl < 0.7 * t2.arl  # two separate charts false-alarm about twice as often


def test_report_renders_tables_and_detection() -> None:
    rows = [arl.Arl("Shewhart (WE rule 1)", s, a, 1.0, 0) for s, a in ((0.0, 368.0), (1.0, 44.0))]
    assert "| Shewhart (WE rule 1) | 368.0 | 44.0 |" in arl_table(rows)
    assert "| Shewhart (WE rule 1) | 1σ | 44.0 | 43.9 | +0.2% |" in published_check(rows)
    detection = pd.DataFrame([{"scope": "chamber", "chart": "ewma", "excursions": 20,
                               "delay_points": 8.0, "delay_hours": 6.6, "placebo_points": 193.5,
                               "faster_than_chance": 0.95}])  # fmt: skip
    coverage = pd.DataFrame([{"excursion_type": "drift", "excursions": 5, "monitored": 5,
                              "in_baseline": 1}])  # fmt: skip
    markdown = detection_markdown(detection, coverage)
    assert "| chamber | `ewma` | 20 | 8 | 6.6 | 193.5 | 95% |" in markdown
    assert "| drift | 5 | 5 | 1 |" in markdown
    assert "## 2. Detection on the demo fab" in render(rows, markdown)
