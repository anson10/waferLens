"""End-to-end demo: a tool drifts out of control mid-lot and the SPC engine catches it.

Builds an isolated in-memory database, seeds one wafer's worth of etch
measurements that are in control, then injects a step drift (as if a tool's
RF power supply started degrading) and reruns SPC to show flags appear
exactly where the drift starts. Run with:

    python -m analysis.anomaly_demo
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analysis.spc import run_spc
from db.models import Base, Lot, Measurement, ProcessStep, SpcFlag, Wafer

SEED = 7
N_POINTS = 40
DRIFT_START = 25
IN_CONTROL_MEAN = 100.0
IN_CONTROL_STD = 1.5


def _build_measurements(drifted: bool) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    values = rng.normal(IN_CONTROL_MEAN, IN_CONTROL_STD, N_POINTS)
    if drifted:
        # Simulate a tool degrading: etch rate creeps upward point by point.
        drift = np.linspace(0, 12, N_POINTS - DRIFT_START)
        values[DRIFT_START:] += drift
    return values


def _seed_db(values: np.ndarray):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()

    session.add(Lot(lot_id=1, product="DEMO1", technology_node="28nm",
                     start_date=datetime(2026, 1, 1).date(), status="active"))
    session.add(Wafer(wafer_id=1, lot_id=1, wafer_number=1, status="active"))
    session.add(ProcessStep(step_id=1, step_name="etch", tool_id="ETCH-07",
                             layer="M1", sequence_order=1))
    session.flush()

    base_time = datetime(2026, 1, 1, 6, 0)
    for i, value in enumerate(values):
        session.add(Measurement(
            measurement_id=i + 1,
            wafer_id=1,
            step_id=1,
            parameter="etch_rate_nm_min",
            value=float(value),
            unit="nm/min",
            timestamp=base_time + timedelta(minutes=10 * i),
        ))
    session.commit()
    return session


def demo() -> None:
    print(f"=== Baseline: {N_POINTS} in-control etch_rate readings ===")
    baseline_session = _seed_db(_build_measurements(drifted=False))
    baseline_flags = run_spc(baseline_session)
    print(f"SPC flags raised: {baseline_flags} (expected 0)\n")

    print(f"=== Injected drift starting at point {DRIFT_START} (tool degrading) ===")
    drifted_session = _seed_db(_build_measurements(drifted=True))
    drifted_flags = run_spc(drifted_session)

    flagged = (
        drifted_session.query(Measurement.measurement_id, SpcFlag.rule_violated)
        .join(SpcFlag, SpcFlag.measurement_id == Measurement.measurement_id)
        .order_by(Measurement.measurement_id)
        .all()
    )
    print(f"SPC flags raised: {drifted_flags} (expected > 0)")
    for measurement_id, rule in flagged:
        print(f"  point {measurement_id:>2} (index {measurement_id - 1:>2}) -> {rule}")

    in_drift_region = sum(1 for m, _ in flagged if m - 1 >= DRIFT_START)
    before_drift = drifted_flags - in_drift_region
    print(
        f"\n{in_drift_region} flags fall at/after drift onset (index {DRIFT_START}); "
        f"{before_drift} fall before it."
    )
    print(
        "Note: this run computes control limits over the whole window (Phase-I style), "
        "so the drift pulls the mean and can retroactively flag pre-drift points too — "
        "in production you'd freeze control limits from a historical in-control baseline "
        "instead of recomputing them from a window that includes the excursion."
    )


if __name__ == "__main__":
    demo()
