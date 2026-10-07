"""Real-time SPC tables, written by the stream consumer (waferlens.stream, phase 6): Kafka
offsets, online EWMA/CUSUM state per chamber x sensor, and the alarms with their end-to-end
latency. One transaction per batch keeps the three consistent (ADR-0012).

``grafana_reader`` reads them through the default privileges from migration 0006.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stream_offsets",
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("next_offset", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("topic", "partition", name=op.f("pk_stream_offsets")),
    )
    op.create_table(
        "stream_alarms",
        sa.Column("alarm_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("chart", sa.Text(), nullable=False),
        sa.Column("chamber_id", sa.SmallInteger(), nullable=False),
        sa.Column("parameter_id", sa.SmallInteger(), nullable=False),
        sa.Column("limit_id", sa.Integer(), nullable=False),
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("measured_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("statistic", sa.Double(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("produced_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "detected_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("chart IN ('ewma', 'cusum')", name=op.f("ck_stream_alarms_chart_valid")),
        sa.CheckConstraint(
            "direction IN ('up', 'down')", name=op.f("ck_stream_alarms_direction_valid")
        ),
        sa.ForeignKeyConstraint(
            ["chamber_id"],
            ["chambers.chamber_id"],
            name=op.f("fk_stream_alarms_chamber_id_chambers"),
        ),
        sa.ForeignKeyConstraint(
            ["limit_id"],
            ["spc_control_limits.limit_id"],
            name=op.f("fk_stream_alarms_limit_id_spc_control_limits"),
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["parameters.parameter_id"],
            name=op.f("fk_stream_alarms_parameter_id_parameters"),
        ),
        sa.PrimaryKeyConstraint("alarm_id", name=op.f("pk_stream_alarms")),
        sa.UniqueConstraint("event_id", "chart", name=op.f("uq_stream_alarms_event_id_chart")),
    )
    op.create_index(
        op.f("ix_stream_alarms_detected_at"), "stream_alarms", ["detected_at"], unique=False
    )
    op.create_table(
        "stream_spc_state",
        sa.Column("chamber_id", sa.SmallInteger(), nullable=False),
        sa.Column("parameter_id", sa.SmallInteger(), nullable=False),
        sa.Column("limit_id", sa.Integer(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("ewma", sa.Double(), nullable=False),
        sa.Column("cusum_up", sa.Double(), nullable=False),
        sa.Column("cusum_down", sa.Double(), nullable=False),
        sa.Column("last_measured_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_event_id", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chamber_id"],
            ["chambers.chamber_id"],
            name=op.f("fk_stream_spc_state_chamber_id_chambers"),
        ),
        sa.ForeignKeyConstraint(
            ["limit_id"],
            ["spc_control_limits.limit_id"],
            name=op.f("fk_stream_spc_state_limit_id_spc_control_limits"),
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["parameters.parameter_id"],
            name=op.f("fk_stream_spc_state_parameter_id_parameters"),
        ),
        sa.PrimaryKeyConstraint("chamber_id", "parameter_id", name=op.f("pk_stream_spc_state")),
    )


def downgrade() -> None:
    op.drop_table("stream_spc_state")
    op.drop_index(op.f("ix_stream_alarms_detected_at"), table_name="stream_alarms")
    op.drop_table("stream_alarms")
    op.drop_table("stream_offsets")
