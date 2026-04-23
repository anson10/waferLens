"""Lot and wafer data generator. Writes lots.csv and wafers.csv."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

DATA_DIR = Path("data")
DEFAULT_SEED = 42

TECH_NODES = ["28nm", "65nm", "130nm", "180nm"]
TECH_NODE_WEIGHTS = [0.30, 0.30, 0.25, 0.15]
LOT_STATUSES = ["complete", "active", "hold"]
LOT_STATUS_WEIGHTS = [0.70, 0.25, 0.05]

LOT_START_WINDOW_DAYS = 180
WAFERS_PER_LOT = 25
WAFER_SCRAP_PROB = 0.02


def generate_lots(n_lots: int = 20, seed: int = DEFAULT_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fake = Faker()
    Faker.seed(seed)

    start_base = date(2025, 10, 1)
    rows = []
    for i in range(1, n_lots + 1):
        rows.append(
            {
                "lot_id": i,
                "product": fake.bothify(text="??###").upper(),
                "technology_node": str(rng.choice(TECH_NODES, p=TECH_NODE_WEIGHTS)),
                "start_date": start_base
                + timedelta(days=int(rng.integers(0, LOT_START_WINDOW_DAYS))),
                "status": str(rng.choice(LOT_STATUSES, p=LOT_STATUS_WEIGHTS)),
            }
        )
    return pd.DataFrame(rows)


def generate_wafers(
    lots: pd.DataFrame, wafers_per_lot: int = WAFERS_PER_LOT, seed: int = DEFAULT_SEED
) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 1)
    rows = []
    wafer_id = 1
    for _, lot in lots.iterrows():
        for n in range(1, wafers_per_lot + 1):
            if rng.random() < WAFER_SCRAP_PROB:
                status = "scrap"
            elif lot["status"] == "complete":
                status = "complete"
            else:
                status = "active"
            rows.append(
                {
                    "wafer_id": wafer_id,
                    "lot_id": int(lot["lot_id"]),
                    "wafer_number": n,
                    "status": status,
                }
            )
            wafer_id += 1
    return pd.DataFrame(rows)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    lots = generate_lots()
    wafers = generate_wafers(lots)
    lots.to_csv(DATA_DIR / "lots.csv", index=False)
    wafers.to_csv(DATA_DIR / "wafers.csv", index=False)
    print(f"[wafer] wrote {len(lots)} lots and {len(wafers)} wafers to {DATA_DIR}/")


if __name__ == "__main__":
    main()
