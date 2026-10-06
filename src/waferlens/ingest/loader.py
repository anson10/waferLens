"""Loads a simulator output directory into PostgreSQL.

The whole load is one transaction: truncate every table, drop the foreign keys, COPY each
table, derive ``wafer_bin_summary`` from the wafer maps in SQL, refresh the ``wafer_yield``
materialized view, re-add the foreign keys, reset id sequences, analyze. If anything fails,
the transaction rolls back and the previous data is untouched, and running it twice gives
the same result.

Foreign keys are dropped during COPY because Postgres checks them one row at a time
(~5k rows/s here). Re-adding a constraint validates all rows in one set-based join, so
integrity is still fully enforced before commit, just much faster. This is the approach in
the PostgreSQL docs, "Populating a Database".
"""

from __future__ import annotations

import io
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from psycopg import Connection as PgConnection
from psycopg import sql
from sqlalchemy import Connection, Engine, ForeignKeyConstraint, Table, text
from sqlalchemy.schema import AddConstraint, DropConstraint

from waferlens.db.models import Base
from waferlens.db.session import get_engine
from waferlens.ingest.contracts import ARROW_TABLES, DERIVED, Tables, check_tables

CHUNK_ROWS = 200_000
LOAD_ORDER: list[Table] = [t for t in Base.metadata.sorted_tables if t.name not in DERIVED]

# Bin counts per wafer, straight from the stored maps, so the two can never disagree.
# unnest() flattens the 2-D array; 0 marks cells off the wafer.
DERIVE_BIN_SUMMARY = """
INSERT INTO wafer_bin_summary (wafer_id, bin_code, die_count)
SELECT m.wafer_id, cell.bin_code, count(*)
FROM wafer_maps AS m
CROSS JOIN LATERAL unnest(m.bin_map) AS cell(bin_code)
WHERE cell.bin_code > 0
GROUP BY m.wafer_id, cell.bin_code
"""


@dataclass
class LoadReport:
    rows: dict[str, int] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())


def read_tables(data_dir: Path) -> Tables:
    tables: Tables = {}
    for table in LOAD_ORDER:
        path = data_dir / f"{table.name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `make simulate` first")
        arrow = pq.read_table(path)
        tables[table.name] = arrow if table.name in ARROW_TABLES else arrow.to_pandas()
    return tables


def load(data_dir: Path, engine: Engine | None = None, *, validate: bool = True) -> LoadReport:
    started = time.perf_counter()
    report = LoadReport()
    tables = read_tables(data_dir)
    report.seconds["read_parquet"] = round(time.perf_counter() - started, 2)
    if validate:
        t = time.perf_counter()
        check_tables(tables)
        report.seconds["contracts"] = round(time.perf_counter() - t, 2)

    engine = engine or get_engine()
    with engine.begin() as conn:
        pg = conn.connection.driver_connection
        assert isinstance(pg, PgConnection), "the loader needs the psycopg 3 driver"
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        foreign_keys = _foreign_keys()
        for fk in foreign_keys:
            conn.execute(DropConstraint(fk))

        for table in LOAD_ORDER:
            t = time.perf_counter()
            data = tables[table.name]
            if isinstance(data, pa.Table):
                _copy_wafer_maps(pg, table, data)
                report.rows[table.name] = data.num_rows
            else:
                copy_frame(pg, table, data)
                report.rows[table.name] = len(data)
            report.seconds[table.name] = round(time.perf_counter() - t, 2)

        t = time.perf_counter()
        result = conn.execute(text(DERIVE_BIN_SUMMARY))
        report.rows["wafer_bin_summary"] = result.rowcount
        report.seconds["wafer_bin_summary"] = round(time.perf_counter() - t, 2)

        t = time.perf_counter()
        conn.execute(text("REFRESH MATERIALIZED VIEW wafer_yield"))
        report.seconds["wafer_yield"] = round(time.perf_counter() - t, 2)

        t = time.perf_counter()
        for fk in foreign_keys:
            conn.execute(AddConstraint(fk))
        report.seconds["foreign_keys"] = round(time.perf_counter() - t, 2)

        _reset_sequences(conn)
        t = time.perf_counter()
        conn.execute(text("ANALYZE"))
        report.seconds["analyze"] = round(time.perf_counter() - t, 2)

    report.total_seconds = round(time.perf_counter() - started, 2)
    return report


def _foreign_keys() -> list[ForeignKeyConstraint]:
    return [
        fk
        for table in Base.metadata.sorted_tables
        for fk in sorted(table.foreign_key_constraints, key=lambda c: str(c.name))
    ]


def copy_frame(pg: PgConnection, table: Table, df: pd.DataFrame) -> None:
    columns = [c.name for c in table.columns]
    stmt = sql.SQL("COPY {} ({}) FROM STDIN (FORMAT csv, NULL '\\N')").format(
        sql.Identifier(table.name), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    stamps = [c for c in columns if isinstance(df[c].dtype, pd.DatetimeTZDtype)]
    with pg.cursor() as cur, cur.copy(stmt) as copy:
        for start in range(0, len(df), CHUNK_ROWS):
            chunk = df.iloc[start : start + CHUNK_ROWS][columns]
            # pandas formats tz-aware timestamps one by one; numpy does it in C.
            chunk = chunk.assign(**{c: _iso_utc(chunk[c]) for c in stamps})
            buf = io.StringIO()
            chunk.to_csv(buf, index=False, header=False, na_rep="\\N")
            copy.write(buf.getvalue())


def _iso_utc(stamps: pd.Series) -> np.ndarray:
    naive = stamps.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy("datetime64[us]")
    text = np.char.add(np.datetime_as_string(naive, unit="us"), "Z")
    return np.where(np.isnat(naive), "\\N", text)


def _copy_wafer_maps(pg: PgConnection, table: Table, maps: pa.Table) -> None:
    stmt = sql.SQL("COPY {} (wafer_id, tested_at, bin_map) FROM STDIN").format(
        sql.Identifier(table.name)
    )
    ids = maps.column("wafer_id").to_numpy()
    tested = _iso_utc(pd.Series(maps.column("tested_at").to_pandas()))
    literals = array_literals(maps.column("bin_map"))
    with pg.cursor() as cur, cur.copy(stmt) as copy:
        for wafer_id, tested_at, literal in zip(ids, tested, literals, strict=True):
            copy.write(b"%d\t%s\t%s\n" % (wafer_id, str(tested_at).encode(), literal))


def array_literals(bin_map: pa.ChunkedArray | pa.Array) -> Iterator[bytes]:
    """Postgres array literals ``{{0,1,..},..}`` for list<list<int>> grids, in input order.

    Bin codes are single digits, so each grid is assembled from bytes with numpy instead of
    turning ~40M cells into Python ints and strings.
    """
    rows = pc.list_value_length(bin_map).to_numpy()
    values = pc.list_flatten(pc.list_flatten(bin_map)).to_numpy()
    if len(values) and (values.min() < 0 or values.max() > 9):
        raise ValueError("array_literals expects single-digit bin codes")
    offset = 0
    for g in rows:
        cells = values[offset : offset + g * g].reshape(g, g)
        offset += g * g
        line = np.full((g, 2 * g + 2), ord(","), dtype=np.uint8)
        line[:, 0] = ord("{")
        line[:, 1 : 2 * g : 2] = cells + ord("0")
        line[:, 2 * g] = ord("}")
        yield b"{" + line.tobytes()[:-1] + b"}"


def _reset_sequences(conn: Connection) -> None:
    """Explicit ids were loaded, so move each serial sequence past the highest id."""
    for table in LOAD_ORDER:
        pk = list(table.primary_key.columns)
        if len(pk) != 1:
            continue
        col = pk[0].name
        seq = conn.execute(
            text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": col}
        ).scalar()
        if seq:
            conn.execute(
                text(f"SELECT setval(:s, COALESCE((SELECT max({col}) FROM {table.name}), 0) + 1,"
                     " false)"),
                {"s": seq},
            )  # fmt: skip
