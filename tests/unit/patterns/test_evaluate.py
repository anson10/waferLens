"""Scoring FabEye's predictions against ground truth, and the report built from it."""

from __future__ import annotations

import pandas as pd
import pytest

from waferlens.patterns.evaluate import Evaluation, magnitude_table, per_class_table
from waferlens.patterns.report import render

REFERENCE = {
    "coverage": 0.893,
    "worst_class_coverage": 0.862,
    "accept": {"target_error": 0.02, "unseen_lot_accept_rate": 0.962,
               "unseen_lot_error_among_accepted": 0.019},
}  # fmt: skip


def _frame() -> pd.DataFrame:
    """10 clean wafers (one false alarm), 4 Center wafers (one missed, one weak)."""
    rows = [("none", "none", ["none"], None)] * 9 + [("none", "Edge-Ring", ["Edge-Ring"], None)]
    rows += [
        ("Center", "Center", ["Center"], 2.6),
        ("Center", "Center", ["Center", "none"], 2.1),
        ("Center", "none", ["none", "Center"], 1.6),
        ("Center", "none", ["none"], 1.2),
    ]
    df = pd.DataFrame(rows, columns=["truth", "predicted", "prediction_set", "magnitude_sigma"])
    df["wafer_id"] = range(1, len(df) + 1)
    df["confidence"] = 0.9
    df["auto_accept"] = [True] * len(df)
    df["correct"] = df["truth"] == df["predicted"]
    df["covered"] = [t in s for t, s in zip(df["truth"], df["prediction_set"], strict=True)]
    return df


def test_per_class_recall_precision_and_coverage() -> None:
    table = per_class_table(_frame()).set_index("class")
    assert table.loc["Center", "recall"] == pytest.approx(0.5)
    assert table.loc["Center", "precision"] == pytest.approx(1.0)
    assert table.loc["Center", "coverage"] == pytest.approx(0.75)
    assert table.loc["none", "precision"] == pytest.approx(9 / 11)
    assert pd.isna(table.loc["Edge-Ring", "recall"])  # predicted but never true
    assert "Donut" not in table.index


def test_weak_patterns_are_missed_more() -> None:
    table = magnitude_table(_frame()).set_index("magnitude")
    assert table.loc["≥ 2.5σ", "recall"] == 1.0
    assert table.loc["< 1.5σ", "recall"] == 0.0
    assert table["wafers"].sum() == 4


def test_report_renders() -> None:
    df = _frame()
    per_class = per_class_table(df)
    ev = Evaluation(
        frame=df, per_class=per_class, confusion=pd.crosstab(df["truth"], df["predicted"]),
        by_magnitude=magnitude_table(df), accuracy=float(df["correct"].mean()),
        majority_accuracy=10 / 14, macro_f1=0.7, coverage=float(df["covered"].mean()),
        accept_rate=1.0, accepted_error=float((~df["correct"]).mean()), pattern_detected=0.5,
        reference=REFERENCE,
    )  # fmt: skip
    md = render(ev, "wafer_cnn.onnx · api 2.0")
    assert "# FabEye on simulated wafer maps" in md
    assert "1 (10.0%) a pattern: Edge-Ring 1" in md
    assert "nan" not in md.lower()
