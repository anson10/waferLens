"""SECOM tables: real UCI SECOM runs and sensor readings (long format).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secom_runs",
        sa.Column("run_id", sa.SmallInteger(), nullable=False),
        sa.Column("run_time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_secom_runs")),
    )
    op.create_index(op.f("ix_secom_runs_run_time"), "secom_runs", ["run_time"], unique=False)
    op.create_table(
        "secom_readings",
        sa.Column("run_id", sa.SmallInteger(), nullable=False),
        sa.Column("sensor_no", sa.SmallInteger(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.CheckConstraint(
            "sensor_no BETWEEN 1 AND 590", name=op.f("ck_secom_readings_sensor_no_range")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["secom_runs.run_id"], name=op.f("fk_secom_readings_run_id_secom_runs")
        ),
        sa.PrimaryKeyConstraint("run_id", "sensor_no", name=op.f("pk_secom_readings")),
    )
    op.create_index(
        op.f("ix_secom_readings_sensor_no"), "secom_readings", ["sensor_no"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_secom_readings_sensor_no"), table_name="secom_readings")
    op.drop_table("secom_readings")
    op.drop_index(op.f("ix_secom_runs_run_time"), table_name="secom_runs")
    op.drop_table("secom_runs")
