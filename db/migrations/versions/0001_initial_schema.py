"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lots",
        sa.Column("lot_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product", sa.String(length=64), nullable=False),
        sa.Column("technology_node", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
    )

    op.create_table(
        "wafers",
        sa.Column("wafer_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("lots.lot_id"), nullable=False),
        sa.Column("wafer_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_wafers_lot_id", "wafers", ["lot_id"])

    op.create_table(
        "process_steps",
        sa.Column("step_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("step_name", sa.String(length=64), nullable=False),
        sa.Column("tool_id", sa.String(length=32), nullable=False),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("sequence_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_process_steps_tool_id", "process_steps", ["tool_id"])

    op.create_table(
        "measurements",
        sa.Column("measurement_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("wafer_id", sa.Integer(), sa.ForeignKey("wafers.wafer_id"), nullable=False),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("process_steps.step_id"), nullable=False),
        sa.Column("parameter", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_measurements_wafer_id", "measurements", ["wafer_id"])
    op.create_index("ix_measurements_step_id", "measurements", ["step_id"])
    op.create_index("ix_measurements_parameter", "measurements", ["parameter"])
    op.create_index("ix_measurements_timestamp", "measurements", ["timestamp"])

    op.create_table(
        "yield_records",
        sa.Column("record_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("wafer_id", sa.Integer(), sa.ForeignKey("wafers.wafer_id"), nullable=False),
        sa.Column("die_count", sa.Integer(), nullable=False),
        sa.Column("pass_count", sa.Integer(), nullable=False),
        sa.Column("yield_pct", sa.Float(), nullable=False),
        sa.Column("defect_density", sa.Float(), nullable=False),
    )
    op.create_index("ix_yield_records_wafer_id", "yield_records", ["wafer_id"])

    op.create_table(
        "spc_flags",
        sa.Column("flag_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "measurement_id",
            sa.Integer(),
            sa.ForeignKey("measurements.measurement_id"),
            nullable=False,
        ),
        sa.Column("rule_violated", sa.String(length=32), nullable=False),
        sa.Column("flagged_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_spc_flags_measurement_id", "spc_flags", ["measurement_id"])
    op.create_index("ix_spc_flags_flagged_at", "spc_flags", ["flagged_at"])


def downgrade() -> None:
    op.drop_table("spc_flags")
    op.drop_table("yield_records")
    op.drop_table("measurements")
    op.drop_table("process_steps")
    op.drop_table("wafers")
    op.drop_table("lots")
