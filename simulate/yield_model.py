"""Yield and defect density simulation.

Poisson yield model: ``Y = exp(-A · D₀)`` where ``A`` is die area and ``D₀`` is
defect density. Wafers that experienced measurements beyond 3σ get a small
defect-density penalty per outlier, so SPC health and final yield are
correlated — which is exactly what Step 6's yield analysis should surface.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
DEFAULT_SEED = 42

# (die_count, die_area_cm2, base_defect_density_per_cm2)
TECH_NODE_PARAMS = {
    "28nm": (1000, 0.25, 0.60),
    "65nm": (500, 0.50, 0.40),
    "130nm": (250, 1.00, 0.25),
    "180nm": (150, 1.50, 0.18),
}

YIELD_MIN = 70.0
YIELD_MAX = 98.0
YIELD_NOISE_SIGMA = 1.5
OUTLIER_PENALTY = 0.15  # 15% D₀ bump per out-of-spec measurement on that wafer


def generate_yield(
    wafers: pd.DataFrame,
    lots: pd.DataFrame,
    measurements: pd.DataFrame,
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 3)

    lot_node = lots.set_index("lot_id")["technology_node"].to_dict()

    # Count measurements whose z-score vs their parameter's global mean/std
    # exceeds 3 — the same wafers that Rule 1 will flag in Step 5.
    m = measurements.copy()
    stats = m.groupby("parameter")["value"].agg(["mean", "std"]).reset_index()
    m = m.merge(stats, on="parameter")
    m["z"] = (m["value"] - m["mean"]) / m["std"].replace(0, 1)
    outlier_counts = m.loc[m["z"].abs() > 3].groupby("wafer_id").size().to_dict()

    rows = []
    for record_id, (_, wafer) in enumerate(wafers.iterrows(), start=1):
        node = lot_node[wafer["lot_id"]]
        die_count, die_area, base_d0 = TECH_NODE_PARAMS[node]

        d0 = base_d0 * rng.lognormal(mean=0.0, sigma=0.25)
        n_outliers = outlier_counts.get(wafer["wafer_id"], 0)
        d0 *= 1.0 + OUTLIER_PENALTY * n_outliers

        raw_yield_pct = np.exp(-die_area * d0) * 100.0 + rng.normal(0, YIELD_NOISE_SIGMA)

        if wafer["status"] == "scrap":
            yield_pct = 0.0
            pass_count = 0
        else:
            yield_pct = float(np.clip(raw_yield_pct, YIELD_MIN, YIELD_MAX))
            pass_count = int(round(die_count * yield_pct / 100.0))

        rows.append(
            {
                "record_id": record_id,
                "wafer_id": int(wafer["wafer_id"]),
                "die_count": die_count,
                "pass_count": pass_count,
                "yield_pct": round(yield_pct, 2),
                "defect_density": round(float(d0), 4),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    lots = pd.read_csv(DATA_DIR / "lots.csv")
    wafers = pd.read_csv(DATA_DIR / "wafers.csv")
    measurements = pd.read_csv(DATA_DIR / "measurements.csv")
    yield_records = generate_yield(wafers, lots, measurements)
    yield_records.to_csv(DATA_DIR / "yield_records.csv", index=False)
    print(f"[yield] wrote {len(yield_records)} yield records to {DATA_DIR}/")


if __name__ == "__main__":
    main()
