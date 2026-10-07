"""SPC tables: frozen Phase I control limits and the alarms they raise.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spc_control_limits",
        sa.Column("limit_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("chamber_id", sa.SmallInteger(), nullable=True),
        sa.Column("tool_id", sa.Text(), nullable=False),
        sa.Column("parameter_id", sa.SmallInteger(), nullable=True),
        sa.Column("route_step_id", sa.Integer(), nullable=True),
        sa.Column("is_multivariate", sa.Boolean(), nullable=False),
        sa.Column("version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("center", sa.Double(), nullable=True),
        sa.Column("sigma", sa.Double(), nullable=True),
        sa.Column("t2_dims", sa.SmallInteger(), nullable=True),
        sa.Column("t2_limit", sa.Double(), nullable=True),
        sa.Column("t2_mean", postgresql.ARRAY(sa.Double()), nullable=True),
        sa.Column("t2_cov_inv", postgresql.ARRAY(sa.Double(), dimensions=2), nullable=True),
        sa.Column("n_baseline", sa.Integer(), nullable=False),
        sa.Column("baseline_start", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("baseline_end", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column(
            "computed_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope = 'chamber') = (chamber_id IS NOT NULL)",
            name=op.f("ck_spc_control_limits_chamber_scope"),
        ),
        sa.CheckConstraint(
            "scope IN ('chamber', 'tool')", name=op.f("ck_spc_control_limits_scope_valid")
        ),
        sa.CheckConstraint(
            "source IN ('sensor', 'metrology')", name=op.f("ck_spc_control_limits_source_valid")
        ),
        sa.CheckConstraint(
            "NOT is_multivariate OR (t2_dims >= 2 AND t2_limit > 0 AND t2_mean IS NOT NULL AND t2_cov_inv IS NOT NULL)",
            name=op.f("ck_spc_control_limits_t2_limits"),
        ),
        sa.CheckConstraint(
            "baseline_end > baseline_start", name=op.f("ck_spc_control_limits_baseline_ordered")
        ),
        sa.CheckConstraint(
            "is_multivariate = (parameter_id IS NULL)",
            name=op.f("ck_spc_control_limits_multivariate_has_no_parameter"),
        ),
        sa.CheckConstraint(
            "is_multivariate OR (center IS NOT NULL AND sigma > 0)",
            name=op.f("ck_spc_control_limits_univariate_limits"),
        ),
        sa.ForeignKeyConstraint(
            ["chamber_id"],
            ["chambers.chamber_id"],
            name=op.f("fk_spc_control_limits_chamber_id_chambers"),
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["parameters.parameter_id"],
            name=op.f("fk_spc_control_limits_parameter_id_parameters"),
        ),
        sa.ForeignKeyConstraint(
            ["route_step_id"],
            ["route_steps.route_step_id"],
            name=op.f("fk_spc_control_limits_route_step_id_route_steps"),
        ),
        sa.ForeignKeyConstraint(
            ["tool_id"], ["tools.tool_id"], name=op.f("fk_spc_control_limits_tool_id_tools")
        ),
        sa.PrimaryKeyConstraint("limit_id", name=op.f("pk_spc_control_limits")),
        sa.UniqueConstraint(
            "source",
            "scope",
            "chamber_id",
            "tool_id",
            "parameter_id",
            "route_step_id",
            "is_multivariate",
            "version",
            name=op.f(
                "uq_spc_control_limits_source_scope_chamber_id_tool_id_parameter_id_route_step_id_is_multivariate_version"
            ),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "spc_alarms",
        sa.Column("alarm_id", sa.Integer(), nullable=False),
        sa.Column("limit_id", sa.Integer(), nullable=False),
        sa.Column("chart", sa.Text(), nullable=False),
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("pass_no", sa.SmallInteger(), nullable=False),
        sa.Column("measured_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("statistic", sa.Double(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "chart IN ('we1', 'we2', 'we3', 'we4', 'ewma', 'cusum', 't2')",
            name=op.f("ck_spc_alarms_chart_valid"),
        ),
        sa.CheckConstraint(
            "direction IS NULL OR direction IN ('up', 'down')",
            name=op.f("ck_spc_alarms_direction_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["limit_id"],
            ["spc_control_limits.limit_id"],
            name=op.f("fk_spc_alarms_limit_id_spc_control_limits"),
        ),
        sa.ForeignKeyConstraint(
            ["route_step_id"],
            ["route_steps.route_step_id"],
            name=op.f("fk_spc_alarms_route_step_id_route_steps"),
        ),
        sa.ForeignKeyConstraint(
            ["wafer_id"], ["wafers.wafer_id"], name=op.f("fk_spc_alarms_wafer_id_wafers")
        ),
        sa.PrimaryKeyConstraint("alarm_id", name=op.f("pk_spc_alarms")),
        sa.UniqueConstraint(
            "limit_id",
            "chart",
            "wafer_id",
            "route_step_id",
            "pass_no",
            name=op.f("uq_spc_alarms_limit_id_chart_wafer_id_route_step_id_pass_no"),
        ),
    )
    op.create_index(op.f("ix_spc_alarms_measured_at"), "spc_alarms", ["measured_at"], unique=False)
    op.create_index(op.f("ix_spc_alarms_wafer_id"), "spc_alarms", ["wafer_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_spc_alarms_wafer_id"), table_name="spc_alarms")
    op.drop_index(op.f("ix_spc_alarms_measured_at"), table_name="spc_alarms")
    op.drop_table("spc_alarms")
    op.drop_table("spc_control_limits")
