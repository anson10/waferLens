"""FabEye on simulated wafer maps, scored against the simulator's per-wafer ground truth.

FabEye was trained and calibrated on real WM-811K lots. The simulated maps differ in grid
size, defect density and pattern shapes, so this measures domain shift: do its accuracy,
its 90% prediction sets and its auto-accept rule still hold on maps it was never built for?
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from waferlens.patterns.fabeye import CLASSES, FROM_SIMULATOR

EVAL_SQL = """
    -- Every scored wafer with its true pattern: the excursion that put a pattern on its map,
    -- or none. Wafers an excursion touched but whose map doesn't show it are 'none' too.
    SELECT p.wafer_id, p.pattern AS predicted, p.confidence, p.auto_accept, p.prediction_set,
           e.excursion_id, e.spatial_pattern, e.magnitude_sigma, m.tested_at
    FROM wafer_patterns AS p
    JOIN wafer_maps AS m USING (wafer_id)
    LEFT JOIN wafer_pattern_truth AS t USING (wafer_id)
    LEFT JOIN excursions_ground_truth AS e ON e.excursion_id = t.excursion_id
"""


@dataclass
class Evaluation:
    frame: pd.DataFrame  # one row per wafer: truth, predicted, confidence, ...
    per_class: pd.DataFrame
    confusion: pd.DataFrame
    by_magnitude: pd.DataFrame
    accuracy: float
    majority_accuracy: float  # always predicting "none"
    macro_f1: float  # over the classes present in the truth
    coverage: float  # truth inside the prediction set
    accept_rate: float
    accepted_error: float
    pattern_detected: float  # share of pattern wafers predicted as *some* pattern
    reference: dict[str, Any]  # FabEye's own numbers on unseen real lots


def load_frame(engine: Engine) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.DataFrame(conn.execute(text(EVAL_SQL)).mappings().all())
    if df.empty:
        return df
    df["truth"] = df["spatial_pattern"].map(FROM_SIMULATOR).fillna("none")
    df["correct"] = df["truth"] == df["predicted"]
    df["covered"] = [t in s for t, s in zip(df["truth"], df["prediction_set"], strict=True)]
    return df


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def per_class_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cls in CLASSES:
        true = df["truth"] == cls
        pred = df["predicted"] == cls
        if not true.any() and not pred.any():
            continue
        recall = float((true & pred).sum() / true.sum()) if true.any() else np.nan
        precision = float((true & pred).sum() / pred.sum()) if pred.any() else np.nan
        rows.append({
            "class": cls, "true": int(true.sum()), "predicted": int(pred.sum()),
            "recall": recall, "precision": precision,
            "f1": _f1(np.nan_to_num(precision), np.nan_to_num(recall)) if true.any() else np.nan,
            "coverage": float(df.loc[true, "covered"].mean()) if true.any() else np.nan,
        })  # fmt: skip
    return pd.DataFrame(rows)


def magnitude_table(df: pd.DataFrame) -> pd.DataFrame:
    """Pattern wafers only: recall by how strong the injected pattern was."""
    pat = df[df["truth"] != "none"].copy()
    if pat.empty:
        return pd.DataFrame(columns=["magnitude", "wafers", "recall", "detected"])
    bins = [0, 1.5, 2.0, 2.5, np.inf]
    labels = ["< 1.5σ", "1.5–2σ", "2–2.5σ", "≥ 2.5σ"]
    pat["magnitude"] = pd.cut(pat["magnitude_sigma"].abs(), bins, labels=labels, right=False)
    out = pat.groupby("magnitude", observed=True).agg(
        wafers=("wafer_id", "size"), recall=("correct", "mean"),
        detected=("predicted", lambda s: float((s != "none").mean())),
    )  # fmt: skip
    return out.reset_index()


def evaluate(engine: Engine, reference: dict[str, Any]) -> Evaluation:
    df = load_frame(engine)
    if df.empty:
        raise ValueError("no scored wafers: run the FabEye scoring first")
    per_class = per_class_table(df)
    present = per_class[per_class["true"] > 0]
    accepted = df["auto_accept"]
    pattern = df["truth"] != "none"
    return Evaluation(
        frame=df,
        per_class=per_class,
        confusion=pd.crosstab(df["truth"], df["predicted"]),
        by_magnitude=magnitude_table(df),
        accuracy=float(df["correct"].mean()),
        majority_accuracy=float((df["truth"] == "none").mean()),
        macro_f1=float(present["f1"].mean()),
        coverage=float(df["covered"].mean()),
        accept_rate=float(accepted.mean()),
        accepted_error=float((~df.loc[accepted, "correct"]).mean()) if accepted.any() else np.nan,
        pattern_detected=float((df.loc[pattern, "predicted"] != "none").mean())
        if pattern.any()
        else np.nan,
        reference=reference,
    )


def reference_numbers(calibration: dict[str, Any], alpha: float = 0.1) -> dict[str, Any]:
    """FabEye's own claims on unseen real lots, from its /calibration endpoint."""
    sets = calibration["prediction_set"][str(alpha)]
    accept = calibration["auto_accept"]
    return {
        "coverage": sets["coverage_on_unseen_lots"],
        "worst_class_coverage": sets["worst_class_coverage_on_unseen_lots"],
        "accept": accept,
    }
