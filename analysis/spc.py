"""Statistical process control rule implementations (Western Electric / Nelson)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from db.models import SpcFlag


def _stats(values: np.ndarray) -> tuple[float, float]:
    return float(np.mean(values)), float(np.std(values, ddof=1))


def rule1(values: np.ndarray, mean: float, std: float) -> np.ndarray:
    """1 point beyond 3σ."""
    return np.abs(values - mean) > 3 * std


def rule2(values: np.ndarray, mean: float, **_) -> np.ndarray:
    """8 consecutive points on the same side of the mean."""
    above = (values > mean).astype(int)
    below = (values < mean).astype(int)
    flags = np.zeros(len(values), dtype=bool)
    for arr in (above, below):
        cumsum = np.cumsum(arr)
        windowed = cumsum[7:] - np.concatenate([[0], cumsum[:-8]])
        hit = np.where(windowed == 8)[0]
        for i in hit:
            flags[i : i + 8] = True
    return flags


def rule3(values: np.ndarray, **_) -> np.ndarray:
    """6 points continuously increasing or decreasing."""
    flags = np.zeros(len(values), dtype=bool)
    n = len(values)
    for i in range(n - 5):
        window = values[i : i + 6]
        if np.all(np.diff(window) > 0) or np.all(np.diff(window) < 0):
            flags[i : i + 6] = True
    return flags


def rule4(values: np.ndarray, mean: float, std: float) -> np.ndarray:
    """2 of 3 consecutive points beyond 2σ on the same side."""
    flags = np.zeros(len(values), dtype=bool)
    beyond_pos = values > mean + 2 * std
    beyond_neg = values < mean - 2 * std
    for arr in (beyond_pos, beyond_neg):
        for i in range(len(values) - 2):
            if arr[i : i + 3].sum() >= 2:
                flags[i : i + 3] = True
    return flags


RULES: dict[str, callable] = {
    "rule1_3sigma": rule1,
    "rule2_8consec": rule2,
    "rule3_6trend": rule3,
    "rule4_2of3_2sigma": rule4,
}


def check_series(
    measurement_ids: list[int],
    values: list[float],
) -> list[dict]:
    """Return list of {measurement_id, rule_violated} for every violation found."""
    arr = np.array(values, dtype=float)
    mean, std = _stats(arr)
    if std == 0:
        return []

    violations = []
    for rule_name, fn in RULES.items():
        flags = fn(arr, mean=mean, std=std)
        for idx in np.where(flags)[0]:
            violations.append(
                {"measurement_id": measurement_ids[idx], "rule_violated": rule_name}
            )
    return violations


def run_spc(session: Session) -> int:
    """Evaluate all measurements grouped by (step_id, parameter), write spc_flags."""
    from sqlalchemy import text

    rows = session.execute(
        text(
            """
            SELECT measurement_id, step_id, parameter, value
            FROM measurements
            ORDER BY step_id, parameter, timestamp
            """
        )
    ).fetchall()

    df = pd.DataFrame(rows, columns=["measurement_id", "step_id", "parameter", "value"])

    now = datetime.utcnow()
    flags_to_insert = []

    for (step_id, parameter), group in df.groupby(["step_id", "parameter"]):
        violations = check_series(
            group["measurement_id"].tolist(),
            group["value"].tolist(),
        )
        for v in violations:
            flags_to_insert.append(
                SpcFlag(
                    measurement_id=v["measurement_id"],
                    rule_violated=v["rule_violated"],
                    flagged_at=now,
                )
            )

    session.bulk_save_objects(flags_to_insert)
    session.commit()
    return len(flags_to_insert)


def main() -> None:
    from db.session import get_session
    from sqlalchemy import text

    with get_session() as session:
        session.execute(text("DELETE FROM spc_flags"))
        session.commit()
        n = run_spc(session)
    print(f"[spc] {n} flags written")


if __name__ == "__main__":
    main()
