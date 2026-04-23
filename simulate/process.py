"""Process step catalog and measurement generator.

Measurements carry realistic gaussian noise around a per-parameter baseline.
Two tools drift over time to make SPC rule detection non-trivial:

* ETCH-02 loses etch rate as polymer accumulates in the chamber.
* CMP-02 leaves slightly more material behind as the pad wears.

A small fraction of measurements are pushed beyond 3σ to generate the
Western Electric / Nelson Rule 1 hits that the SPC engine (Step 5) will
detect.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
DEFAULT_SEED = 42
OUTLIER_PROB = 0.005


class ParamSpec(NamedTuple):
    name: str
    unit: str
    mean: float
    sigma: float
    drift_per_wafer: float = 0.0


STEP_CATALOG: list[dict] = [
    {
        "step_name": "pre_clean",
        "tool_id": "CLEAN-01",
        "layer": "M1",
        "sequence_order": 1,
        "params": [ParamSpec("particle_count", "ct", 10.0, 2.0)],
    },
    {
        "step_name": "coat",
        "tool_id": "COAT-01",
        "layer": "M1",
        "sequence_order": 2,
        "params": [ParamSpec("resist_thickness_nm", "nm", 500.0, 6.0)],
    },
    {
        "step_name": "lithography",
        "tool_id": "LITHO-01",
        "layer": "M1",
        "sequence_order": 3,
        "params": [
            ParamSpec("cd_nm", "nm", 100.0, 1.2),
            ParamSpec("overlay_nm", "nm", 0.0, 1.5),
        ],
    },
    {
        "step_name": "develop",
        "tool_id": "DEV-01",
        "layer": "M1",
        "sequence_order": 4,
        "params": [ParamSpec("cd_nm_post_dev", "nm", 98.0, 1.0)],
    },
    {
        "step_name": "etch",
        "tool_id": "ETCH-02",
        "layer": "M1",
        "sequence_order": 5,
        "params": [
            # ETCH-02 polymer buildup: rate falls ~1 nm/s over a 500-wafer campaign
            ParamSpec("etch_rate_nm_s", "nm/s", 15.0, 0.4, drift_per_wafer=-0.002),
            ParamSpec("cd_nm_post_etch", "nm", 95.0, 1.1),
        ],
    },
    {
        "step_name": "strip",
        "tool_id": "STRIP-01",
        "layer": "M1",
        "sequence_order": 6,
        "params": [ParamSpec("residue_ppm", "ppm", 5.0, 1.0)],
    },
    {
        "step_name": "cvd",
        "tool_id": "CVD-03",
        "layer": "M2",
        "sequence_order": 7,
        "params": [ParamSpec("thickness_nm", "nm", 300.0, 4.0)],
    },
    {
        "step_name": "cmp",
        "tool_id": "CMP-02",
        "layer": "M2",
        "sequence_order": 8,
        # CMP-02 pad wear: removes less material over time → post-CMP thickness grows
        "params": [
            ParamSpec(
                "thickness_post_cmp_nm", "nm", 280.0, 3.5, drift_per_wafer=0.01
            )
        ],
    },
    {
        "step_name": "metrology",
        "tool_id": "METR-01",
        "layer": "M2",
        "sequence_order": 9,
        "params": [ParamSpec("cd_nm", "nm", 100.0, 1.3)],
    },
    {
        "step_name": "anneal",
        "tool_id": "ANNEAL-01",
        "layer": "M2",
        "sequence_order": 10,
        "params": [ParamSpec("sheet_resistance_ohm_sq", "ohm/sq", 25.0, 1.0)],
    },
]


def generate_steps() -> pd.DataFrame:
    rows = []
    for i, step in enumerate(STEP_CATALOG, start=1):
        rows.append(
            {
                "step_id": i,
                "step_name": step["step_name"],
                "tool_id": step["tool_id"],
                "layer": step["layer"],
                "sequence_order": step["sequence_order"],
            }
        )
    return pd.DataFrame(rows)


def generate_measurements(
    wafers: pd.DataFrame, lots: pd.DataFrame, seed: int = DEFAULT_SEED
) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 2)

    # Order wafers chronologically so drift accumulates in the right direction.
    lot_start = lots.set_index("lot_id")["start_date"]
    wafers_sorted = (
        wafers.assign(start_date=wafers["lot_id"].map(lot_start))
        .sort_values(["start_date", "lot_id", "wafer_number"])
        .reset_index(drop=True)
    )

    rows = []
    measurement_id = 1

    for wafer_idx, wafer in wafers_sorted.iterrows():
        lot_start_ts = pd.to_datetime(wafer["start_date"])
        wafer_start = lot_start_ts + timedelta(
            hours=int(wafer["wafer_number"]) * 4,
            minutes=int(rng.integers(0, 60)),
        )
        for step_idx, step in enumerate(STEP_CATALOG, start=1):
            step_ts = wafer_start + timedelta(minutes=step_idx * 30)
            for param in step["params"]:
                base = param.mean + param.drift_per_wafer * wafer_idx
                value = rng.normal(base, param.sigma)
                if rng.random() < OUTLIER_PROB:
                    sign = 1.0 if rng.random() < 0.5 else -1.0
                    value = base + sign * (3.5 + rng.exponential(0.5)) * param.sigma
                rows.append(
                    {
                        "measurement_id": measurement_id,
                        "wafer_id": int(wafer["wafer_id"]),
                        "step_id": step_idx,
                        "parameter": param.name,
                        "value": round(float(value), 4),
                        "unit": param.unit,
                        "timestamp": step_ts.isoformat(sep=" "),
                    }
                )
                measurement_id += 1
    return pd.DataFrame(rows)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    lots = pd.read_csv(DATA_DIR / "lots.csv", parse_dates=["start_date"])
    wafers = pd.read_csv(DATA_DIR / "wafers.csv")
    steps = generate_steps()
    measurements = generate_measurements(wafers, lots)
    steps.to_csv(DATA_DIR / "process_steps.csv", index=False)
    measurements.to_csv(DATA_DIR / "measurements.csv", index=False)
    print(
        f"[process] wrote {len(steps)} steps and {len(measurements)} measurements to {DATA_DIR}/"
    )


if __name__ == "__main__":
    main()
