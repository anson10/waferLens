"""Reads CSVs from data/ and inserts into the database.

Insertion order respects FK constraints: lots → wafers → process_steps
→ measurements → yield_records.

Primary keys from the CSVs are used as-is so foreign key references
across tables remain consistent.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text

from db.models import Lot, Measurement, ProcessStep, Wafer, YieldRecord
from db.session import get_session

DATA_DIR = Path("data")


def _clear_tables(session) -> None:
    """Delete all rows in FK-safe reverse order."""
    for table in ("yield_records", "measurements", "process_steps", "wafers", "lots"):
        session.execute(text(f"DELETE FROM {table}"))


def load_lots(session, df: pd.DataFrame) -> None:
    session.bulk_insert_mappings(
        Lot,
        df.assign(start_date=pd.to_datetime(df["start_date"]).dt.date)
        .to_dict(orient="records"),
    )


def load_wafers(session, df: pd.DataFrame) -> None:
    session.bulk_insert_mappings(Wafer, df.to_dict(orient="records"))


def load_process_steps(session, df: pd.DataFrame) -> None:
    session.bulk_insert_mappings(ProcessStep, df.to_dict(orient="records"))


def load_measurements(session, df: pd.DataFrame) -> None:
    session.bulk_insert_mappings(
        Measurement,
        df.assign(timestamp=pd.to_datetime(df["timestamp"])).to_dict(orient="records"),
    )


def load_yield_records(session, df: pd.DataFrame) -> None:
    session.bulk_insert_mappings(YieldRecord, df.to_dict(orient="records"))


def run(data_dir: Path = DATA_DIR, clear: bool = False) -> dict[str, int]:
    lots_df = pd.read_csv(data_dir / "lots.csv")
    wafers_df = pd.read_csv(data_dir / "wafers.csv")
    steps_df = pd.read_csv(data_dir / "process_steps.csv")
    measurements_df = pd.read_csv(data_dir / "measurements.csv")
    yield_df = pd.read_csv(data_dir / "yield_records.csv")

    with get_session() as session:
        if clear:
            _clear_tables(session)

        load_lots(session, lots_df)
        load_wafers(session, wafers_df)
        load_process_steps(session, steps_df)
        load_measurements(session, measurements_df)
        load_yield_records(session, yield_df)

        session.commit()

    return {
        "lots": len(lots_df),
        "wafers": len(wafers_df),
        "process_steps": len(steps_df),
        "measurements": len(measurements_df),
        "yield_records": len(yield_df),
    }


def main() -> None:
    counts = run(clear=True)
    for table, n in counts.items():
        print(f"[loader] {table}: {n} rows inserted")


if __name__ == "__main__":
    main()
