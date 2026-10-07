"""Data contracts checked before anything is written to the database.

Two layers:

* **Per-table pandera schemas**, generated from the ORM metadata so they can't drift from
  the schema: exact column set, nullability, type family, unique primary key. Postgres would
  reject most of these too, but halfway through a 3M-row COPY and with a less readable error.
* **Cross-table rules** the database can't express as a CHECK constraint, e.g. "metrology is
  measured after the step it measures" or "a wafer map has its product's grid".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandera.pandas as pa
import pyarrow as pa_arrow
import pyarrow.compute as pc
from sqlalchemy import Boolean, Double, Float, Integer, Numeric, SmallInteger, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

from waferlens.db.models import PATTERN_TABLES, ROOTCAUSE_TABLES, SPC_TABLES, Base

Tables = dict[str, pd.DataFrame | pa_arrow.Table]

# Tables on Base that are not in the Parquet drop: wafer_bin_summary is derived inside the
# database from wafer_maps (ADR-0003); the SPC and root-cause tables are written by
# waferlens.spc / waferlens.rootcause. The loader still truncates them: results derived from
# replaced data are stale.
DERIVED = frozenset({"wafer_bin_summary", *SPC_TABLES, *ROOTCAUSE_TABLES, *PATTERN_TABLES})
# wafer_maps carries a nested list column; it's checked by check_wafer_maps instead.
ARROW_TABLES = frozenset({"wafer_maps"})


class ContractError(ValueError):
    pass


def _type_check(column_type: object) -> pa.Check | None:
    if isinstance(column_type, (Integer, SmallInteger)):
        return pa.Check(lambda s: pd.api.types.is_integer_dtype(s), element_wise=False,
                        error="expected an integer column")  # fmt: skip
    if isinstance(column_type, (Double, Float, Numeric)):
        return pa.Check(lambda s: pd.api.types.is_numeric_dtype(s), element_wise=False,
                        error="expected a numeric column")  # fmt: skip
    if isinstance(column_type, Boolean):
        return pa.Check(lambda s: pd.api.types.is_bool_dtype(s), element_wise=False,
                        error="expected a boolean column")  # fmt: skip
    if isinstance(column_type, TIMESTAMP):
        return pa.Check(lambda s: isinstance(s.dtype, pd.DatetimeTZDtype), element_wise=False,
                        error="expected a timezone-aware timestamp column")  # fmt: skip
    if isinstance(column_type, (Text, JSONB)):
        # Inspects values for object columns, so a column of numbers stored as objects fails.
        return pa.Check(lambda s: pd.api.types.is_string_dtype(s), element_wise=False,
                        error="expected text")  # fmt: skip
    return None


def schema_for(table: Table) -> pa.DataFrameSchema:
    columns = {}
    for col in table.columns:
        check = _type_check(col.type)
        columns[col.name] = pa.Column(
            nullable=bool(col.nullable), checks=[check] if check else [], required=True
        )
    pk = [c.name for c in table.primary_key.columns]
    return pa.DataFrameSchema(columns, strict=True, unique=pk, name=table.name)


SCHEMAS: dict[str, pa.DataFrameSchema] = {
    name: schema_for(table)
    for name, table in Base.metadata.tables.items()
    if name not in DERIVED | ARROW_TABLES
}


def check_tables(tables: Tables) -> None:
    """Raise ContractError listing every broken rule across all tables."""
    errors: list[str] = []
    missing = set(Base.metadata.tables) - DERIVED - set(tables)
    if missing:
        raise ContractError(f"missing tables: {sorted(missing)}")

    for name, schema in SCHEMAS.items():
        df = tables[name]
        if not isinstance(df, pd.DataFrame):
            errors.append(f"{name}: expected a DataFrame")
            continue
        try:
            schema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            for row in exc.failure_cases.drop_duplicates(["column", "check"]).itertuples():
                errors.append(f"{name}.{row.column}: {row.check}")

    if not errors:
        errors += _cross_table(tables)
    if errors:
        raise ContractError("; ".join(errors))


def _frame(tables: Tables, name: str) -> pd.DataFrame:
    t = tables[name]
    assert isinstance(t, pd.DataFrame)
    return t


def _cross_table(tables: Tables) -> list[str]:
    errors: list[str] = []
    history = _frame(tables, "wafer_step_history")
    last_pass = history.drop_duplicates(["wafer_id", "route_step_id"], keep="last")

    metrology = _frame(tables, "metrology_measurements")
    timed = metrology[["wafer_id", "route_step_id", "time"]].merge(
        last_pass[["wafer_id", "route_step_id", "track_out"]],
        on=["wafer_id", "route_step_id"], how="left",
    )  # fmt: skip
    if timed["track_out"].isna().any():
        errors.append("metrology_measurements: wafer was never processed at the measured step")
    elif (timed["time"] <= timed["track_out"]).any():
        errors.append("metrology_measurements: measured before the step finished")

    sensors = _frame(tables, "tool_sensor_readings")
    if not np.isfinite(sensors["value"].to_numpy()).all():
        errors.append("tool_sensor_readings: non-finite values")
    on_history = sensors[["wafer_id", "route_step_id", "time", "chamber_id"]].merge(
        history[["wafer_id", "route_step_id", "track_in", "chamber_id"]],
        left_on=["wafer_id", "route_step_id", "time"],
        right_on=["wafer_id", "route_step_id", "track_in"], how="left", suffixes=("", "_h"),
    )  # fmt: skip
    if (on_history["chamber_id"] != on_history["chamber_id_h"]).any():
        errors.append("tool_sensor_readings: chamber differs from wafer_step_history")

    errors += check_wafer_maps(tables)
    return errors


def check_wafer_maps(tables: Tables) -> list[str]:
    maps = tables["wafer_maps"]
    if not isinstance(maps, pa_arrow.Table):
        return ["wafer_maps: expected an Arrow table"]
    expected = {"wafer_id", "tested_at", "bin_map"}
    if set(maps.column_names) != expected:
        return [f"wafer_maps: columns {sorted(maps.column_names)} != {sorted(expected)}"]
    ids = maps.column("wafer_id").to_numpy()
    if len(np.unique(ids)) != len(ids):
        return ["wafer_maps: duplicate wafer_id"]

    wafers = _frame(tables, "wafers").set_index("wafer_id")
    lots = _frame(tables, "lots").set_index("lot_id")
    products = _frame(tables, "products").set_index("product_id")
    if not pd.Index(ids).isin(wafers.index).all():
        return ["wafer_maps: unknown wafer_id"]
    product = lots.loc[wafers.loc[ids, "lot_id"], "product_id"].to_numpy()
    grid = products.loc[product, "map_rows"].to_numpy()

    errors = []
    if (wafers.loc[ids, "status"] != "complete").any():
        errors.append("wafer_maps: map for a wafer that isn't complete")
    bin_map = maps.column("bin_map")
    rows = pc.list_value_length(bin_map).to_numpy()
    cols = pc.list_value_length(pc.list_flatten(bin_map)).to_numpy()
    if (rows != grid).any() or (cols != np.repeat(grid, grid)).any():
        errors.append("wafer_maps: grid size differs from the product's map size")
    else:
        values = pc.list_flatten(pc.list_flatten(bin_map)).to_numpy()
        on_wafer = np.add.reduceat(values > 0, np.r_[0, np.cumsum(grid * grid)[:-1]])
        if (on_wafer != products.loc[product, "gross_dies"].to_numpy()).any():
            errors.append("wafer_maps: on-wafer die count differs from gross_dies")
        bins = set(_frame(tables, "sort_bins")["bin_code"]) | {0}
        if not set(np.unique(values)) <= bins:
            errors.append("wafer_maps: bin code not in sort_bins")
    return errors
