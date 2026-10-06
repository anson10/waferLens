"""Pandera schemas that gate CSV rows before they reach the database.

Fabs live and die by data quality gates — a bad yield read or an
orphaned foreign key silently corrupts every downstream SPC/yield
aggregation. These schemas fail the ingest loudly instead.
"""

from __future__ import annotations

import pandera.pandas as pa
from pandera import Check, Column

lots_schema = pa.DataFrameSchema(
    {
        "lot_id": Column(int, Check.ge(1), unique=True),
        "product": Column(str, nullable=False),
        "technology_node": Column(str, nullable=False),
        "start_date": Column(str, nullable=False),
        "status": Column(str, Check.isin(["active", "complete", "hold"])),
    }
)

wafers_schema = pa.DataFrameSchema(
    {
        "wafer_id": Column(int, Check.ge(1), unique=True),
        "lot_id": Column(int, Check.ge(1)),
        "wafer_number": Column(int, Check.in_range(1, 25)),
        "status": Column(str, Check.isin(["active", "complete", "scrap"])),
    }
)

process_steps_schema = pa.DataFrameSchema(
    {
        "step_id": Column(int, Check.ge(1), unique=True),
        "step_name": Column(str, nullable=False),
        "tool_id": Column(str, nullable=False),
        "layer": Column(str, nullable=False),
        "sequence_order": Column(int, Check.ge(1)),
    }
)

measurements_schema = pa.DataFrameSchema(
    {
        "measurement_id": Column(int, Check.ge(1), unique=True),
        "wafer_id": Column(int, Check.ge(1)),
        "step_id": Column(int, Check.ge(1)),
        "parameter": Column(str, nullable=False),
        "value": Column(float, nullable=False),
        "unit": Column(str, nullable=False),
        "timestamp": Column(str, nullable=False),
    }
)

yield_records_schema = pa.DataFrameSchema(
    {
        "record_id": Column(int, Check.ge(1), unique=True),
        "wafer_id": Column(int, Check.ge(1)),
        "die_count": Column(int, Check.gt(0)),
        "pass_count": Column(int, Check.ge(0)),
        "yield_pct": Column(float, Check.in_range(0, 100)),
        "defect_density": Column(float, Check.ge(0)),
    }
)


def check_referential_integrity(wafers_df, lots_df, measurements_df, yield_df, steps_df) -> None:
    """Raise if any FK references a row that doesn't exist in its parent table."""
    orphaned_wafers = set(wafers_df["lot_id"]) - set(lots_df["lot_id"])
    if orphaned_wafers:
        raise ValueError(f"wafers reference missing lot_id(s): {orphaned_wafers}")

    orphaned_measurement_wafers = set(measurements_df["wafer_id"]) - set(wafers_df["wafer_id"])
    if orphaned_measurement_wafers:
        raise ValueError(
            f"measurements reference missing wafer_id(s): {orphaned_measurement_wafers}"
        )

    orphaned_measurement_steps = set(measurements_df["step_id"]) - set(steps_df["step_id"])
    if orphaned_measurement_steps:
        raise ValueError(
            f"measurements reference missing step_id(s): {orphaned_measurement_steps}"
        )

    orphaned_yield_wafers = set(yield_df["wafer_id"]) - set(wafers_df["wafer_id"])
    if orphaned_yield_wafers:
        raise ValueError(f"yield_records reference missing wafer_id(s): {orphaned_yield_wafers}")

    bad_pass_counts = yield_df[yield_df["pass_count"] > yield_df["die_count"]]
    if not bad_pass_counts.empty:
        raise ValueError(
            f"yield_records with pass_count > die_count: {bad_pass_counts['record_id'].tolist()}"
        )


def validate_all(lots_df, wafers_df, steps_df, measurements_df, yield_df) -> None:
    """Run all pandera schema checks plus cross-table referential integrity checks."""
    lots_schema.validate(lots_df)
    wafers_schema.validate(wafers_df)
    process_steps_schema.validate(steps_df)
    measurements_schema.validate(measurements_df)
    yield_records_schema.validate(yield_df)
    check_referential_integrity(wafers_df, lots_df, measurements_df, yield_df, steps_df)
