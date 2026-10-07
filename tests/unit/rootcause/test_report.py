"""docs/root_cause.md rendering from evaluation rows."""

from __future__ import annotations

import pandas as pd

from waferlens.rootcause.report import accuracy_table, coverage_table, render


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # id, type, |mag|, pattern, rank, candidates, top1, top3, wafers, delta, dies, cost, spc
            (1, "spatial_pattern", 2.0, "edge_ring", 1, 100, True, True, 50, -20.0, 900, True,
             False),
            (2, "step_shift", 1.5, None, 2, 100, False, True, 40, -5.0, 300, True, True),
            (3, "chamber_offset", 0.6, None, 40, 100, False, False, 400, -0.2, 10, False, True),
            (4, "recipe_change", 1.2, None, None, 0, False, False, None, None, None, False, False),
        ],
        columns=["excursion_id", "excursion_type", "abs_magnitude_sigma", "spatial_pattern",
                 "true_rank", "candidates", "top1", "top3", "affected_wafers", "yield_delta_pct",
                 "dies_lost", "cost_yield", "spc_caught"],
    )  # fmt: skip


def test_accuracy_separates_excursions_that_cost_yield() -> None:
    table = accuracy_table(_frame())
    assert "| All injected | 4 | 1 (25%) | 2 (50%) |" in table
    assert "| Measurably cost yield (≥ 1 point vs controls) | 2 | 1 (50%) | 2 (100%) |" in table


def test_coverage_counts_each_excursion_once() -> None:
    table = coverage_table(_frame())
    assert "| SPC and commonality | 1 | 0 |" in table
    assert "| SPC only | 1 | 0 |" in table
    assert "| Commonality only (top-3) | 1 | 1 |" in table
    assert "| Neither | 1 | 0 |" in table


def test_render_handles_an_excursion_without_a_ranking() -> None:
    doc = render(_frame())
    assert "| 4 | recipe_change | 1.2 |  | – | – | 0 |  |" in doc
    assert "first for 1 of\n2 injected excursions that measurably cost yield (50%)" in doc
