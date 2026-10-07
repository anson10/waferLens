"""SECOM model results: the registered model's holdout metrics, per-run scores and sensor
importance, written by ``waferlens.ml.store`` for Grafana. MLflow keeps the full history;
these tables hold the latest model only.

``grafana_reader`` can read them through the default privileges from migration 0006.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secom_model_versions",
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("trained_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("train_runs", sa.Integer(), nullable=False),
        sa.Column("test_runs", sa.Integer(), nullable=False),
        sa.Column("test_fails", sa.Integer(), nullable=False),
        sa.Column("test_starts", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("holdout_pr_auc", sa.Double(), nullable=False),
        sa.Column("holdout_pr_auc_low", sa.Double(), nullable=False),
        sa.Column("holdout_pr_auc_high", sa.Double(), nullable=False),
        sa.Column("holdout_prevalence", sa.Double(), nullable=False),
        sa.Column("random_split_pr_auc", sa.Double(), nullable=False),
        sa.Column("baseline_pr_auc", sa.Double(), nullable=False),
        sa.Column("alarm_threshold", sa.Double(), nullable=False),
        sa.Column("mlflow_run_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("model_version", name=op.f("pk_secom_model_versions")),
    )
    op.create_table(
        "secom_scores",
        sa.Column("run_id", sa.SmallInteger(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("alarm", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "split IN ('walk_forward', 'holdout')", name=op.f("ck_secom_scores_split")
        ),
        sa.ForeignKeyConstraint(
            ["model_version"],
            ["secom_model_versions.model_version"],
            name=op.f("fk_secom_scores_model_version_secom_model_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["secom_runs.run_id"], name=op.f("fk_secom_scores_run_id_secom_runs")
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_secom_scores")),
    )
    op.create_table(
        "secom_sensor_importance",
        sa.Column("sensor_no", sa.SmallInteger(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("importance", sa.Double(), nullable=False),
        sa.Column("importance_rank", sa.SmallInteger(), nullable=False),
        sa.Column("missing_pct", sa.Double(), nullable=False),
        sa.CheckConstraint(
            "sensor_no BETWEEN 1 AND 590", name=op.f("ck_secom_sensor_importance_sensor_no_range")
        ),
        sa.ForeignKeyConstraint(
            ["model_version"],
            ["secom_model_versions.model_version"],
            name=op.f("fk_secom_sensor_importance_model_version_secom_model_versions"),
        ),
        sa.PrimaryKeyConstraint("sensor_no", name=op.f("pk_secom_sensor_importance")),
    )


def downgrade() -> None:
    op.drop_table("secom_sensor_importance")
    op.drop_table("secom_scores")
    op.drop_table("secom_model_versions")
