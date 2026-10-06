"""Insert benchmark: ORM vs SQLAlchemy Core vs COPY, on real sensor rows.

Each method inserts the same rows into ``tool_sensor_readings`` inside a transaction that is
rolled back, so the loaded database is unchanged. The rows are shifted ten years ahead so
they don't collide with loaded keys; every foreign key still points at a real parent row.
Needs a loaded database (``make seed``).

    python -m waferlens.ingest.benchmark --rows 20000
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from psycopg import Connection as PgConnection
from sqlalchemy import Connection, insert, text
from sqlalchemy.orm import Session

from waferlens.db.models import Base, ToolSensorReading
from waferlens.db.session import get_engine
from waferlens.ingest.loader import _copy_frame

TABLE = Base.metadata.tables["tool_sensor_readings"]
FK_NAMES = sorted(str(fk.name) for fk in TABLE.foreign_key_constraints)


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): v for k, v in row.items()} for row in df.to_dict("records")]


def _orm(conn: Connection, df: pd.DataFrame) -> None:
    session = Session(bind=conn)
    session.add_all(ToolSensorReading(**row) for row in _records(df))
    session.flush()


def _core(conn: Connection, df: pd.DataFrame) -> None:
    conn.execute(insert(TABLE), _records(df))


def _copy(conn: Connection, df: pd.DataFrame) -> None:
    pg = conn.connection.driver_connection
    assert isinstance(pg, PgConnection)
    _copy_frame(pg, TABLE, df)


def _copy_without_fk_checks(conn: Connection, df: pd.DataFrame) -> None:
    for name in FK_NAMES:
        conn.execute(text(f"ALTER TABLE {TABLE.name} DROP CONSTRAINT {name}"))
    _copy(conn, df)


METHODS: dict[str, Callable[[Connection, pd.DataFrame], None]] = {
    "ORM (session.add_all + flush)": _orm,
    "Core (insert, executemany)": _core,
    "COPY (FKs checked per row)": _copy,
    "COPY (FKs dropped)": _copy_without_fk_checks,
}


def run_benchmark(data_dir: Path, rows: int) -> list[tuple[str, int, float]]:
    df = pq.read_table(data_dir / "tool_sensor_readings.parquet").slice(0, rows).to_pandas()
    df["time"] = df["time"] + pd.DateOffset(years=10)
    results = []
    engine = get_engine()
    for name, method in METHODS.items():
        with engine.connect() as conn:
            trans = conn.begin()
            started = time.perf_counter()
            method(conn, df)
            elapsed = time.perf_counter() - started
            trans.rollback()
        results.append((name, len(df), elapsed))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--data", type=Path, default=Path("data/demo"))
    args = parser.parse_args()
    results = run_benchmark(args.data, args.rows)
    base = results[0][1] / results[0][2]
    print("| Method | Rows | Seconds | Rows/s | vs ORM |\n|---|---|---|---|---|")
    for name, n, seconds in results:
        rate = n / seconds
        print(f"| {name} | {n:,} | {seconds:.2f} | {rate:,.0f} | {rate / base:.1f}x |")


if __name__ == "__main__":
    main()
