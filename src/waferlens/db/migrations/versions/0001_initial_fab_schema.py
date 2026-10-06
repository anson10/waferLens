"""Initial fab schema: master data, genealogy, hypertables, wafer maps, ground truth.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HYPERTABLES = ("tool_sensor_readings", "metrology_measurements")

WAFER_YIELD_VIEW = """
CREATE VIEW wafer_yield AS
-- Yield per sorted wafer: good dies / tested dies. Pass/fail comes from sort_bins.is_pass,
-- so adding a new fail bin never needs a change here.
SELECT
    s.wafer_id,
    SUM(s.die_count)                                        AS tested_dies,
    COALESCE(SUM(s.die_count) FILTER (WHERE b.is_pass), 0)  AS good_dies,
    ROUND(
        100.0 * COALESCE(SUM(s.die_count) FILTER (WHERE b.is_pass), 0)
        / NULLIF(SUM(s.die_count), 0),
        2
    )                                                       AS yield_pct
FROM wafer_bin_summary s
JOIN sort_bins b USING (bin_code)
GROUP BY s.wafer_id
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "parameters",
        sa.Column("parameter_id", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('sensor', 'metrology')", name=op.f("ck_parameters_kind_valid")
        ),
        sa.PrimaryKeyConstraint("parameter_id", name=op.f("pk_parameters")),
        sa.UniqueConstraint("name", name=op.f("uq_parameters_name")),
    )
    op.create_table(
        "simulation_runs",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_simulation_runs")),
    )
    op.create_table(
        "sort_bins",
        sa.Column("bin_code", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_pass", sa.Boolean(), nullable=False),
        sa.CheckConstraint("bin_code >= 1", name=op.f("ck_sort_bins_bin_code_positive")),
        sa.PrimaryKeyConstraint("bin_code", name=op.f("pk_sort_bins")),
        sa.UniqueConstraint("name", name=op.f("uq_sort_bins_name")),
    )
    op.create_table(
        "technology_nodes",
        sa.Column("node_id", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("feature_size_nm", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "feature_size_nm > 0", name=op.f("ck_technology_nodes_feature_size_positive")
        ),
        sa.PrimaryKeyConstraint("node_id", name=op.f("pk_technology_nodes")),
        sa.UniqueConstraint("name", name=op.f("uq_technology_nodes_name")),
    )
    op.create_table(
        "tool_types",
        sa.Column("tool_type", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("tool_type", name=op.f("pk_tool_types")),
    )
    op.create_table(
        "products",
        sa.Column("product_id", sa.SmallInteger(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("node_id", sa.SmallInteger(), nullable=False),
        sa.Column("die_area_cm2", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("map_rows", sa.SmallInteger(), nullable=False),
        sa.Column("map_cols", sa.SmallInteger(), nullable=False),
        sa.Column("gross_dies", sa.Integer(), nullable=False),
        sa.CheckConstraint("die_area_cm2 > 0", name=op.f("ck_products_die_area_positive")),
        sa.CheckConstraint(
            "gross_dies > 0 AND gross_dies <= map_rows * map_cols",
            name=op.f("ck_products_gross_dies_fit_map"),
        ),
        sa.CheckConstraint(
            "map_rows > 0 AND map_cols > 0", name=op.f("ck_products_map_size_positive")
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["technology_nodes.node_id"],
            name=op.f("fk_products_node_id_technology_nodes"),
        ),
        sa.PrimaryKeyConstraint("product_id", name=op.f("pk_products")),
        sa.UniqueConstraint("code", name=op.f("uq_products_code")),
    )
    op.create_index(op.f("ix_products_node_id"), "products", ["node_id"], unique=False)
    op.create_table(
        "tools",
        sa.Column("tool_id", sa.Text(), nullable=False),
        sa.Column("tool_type", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tool_type"], ["tool_types.tool_type"], name=op.f("fk_tools_tool_type_tool_types")
        ),
        sa.PrimaryKeyConstraint("tool_id", name=op.f("pk_tools")),
    )
    op.create_index(op.f("ix_tools_tool_type"), "tools", ["tool_type"], unique=False)
    op.create_table(
        "chambers",
        sa.Column("chamber_id", sa.SmallInteger(), nullable=False),
        sa.Column("tool_id", sa.Text(), nullable=False),
        sa.Column("chamber_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tool_id"], ["tools.tool_id"], name=op.f("fk_chambers_tool_id_tools")
        ),
        sa.PrimaryKeyConstraint("chamber_id", name=op.f("pk_chambers")),
        sa.UniqueConstraint(
            "tool_id", "chamber_code", name=op.f("uq_chambers_tool_id_chamber_code")
        ),
    )
    op.create_table(
        "routes",
        sa.Column("route_id", sa.SmallInteger(), nullable=False),
        sa.Column("product_id", sa.SmallInteger(), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.product_id"], name=op.f("fk_routes_product_id_products")
        ),
        sa.PrimaryKeyConstraint("route_id", name=op.f("pk_routes")),
        sa.UniqueConstraint("product_id", "version", name=op.f("uq_routes_product_id_version")),
    )
    op.create_table(
        "lots",
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("lot_code", sa.Text(), nullable=False),
        sa.Column("parent_lot_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.SmallInteger(), nullable=False),
        sa.Column("route_id", sa.SmallInteger(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("3"), nullable=False),
        sa.Column("start_time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'hold', 'complete', 'scrapped')",
            name=op.f("ck_lots_status_valid"),
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name=op.f("ck_lots_priority_range")),
        sa.ForeignKeyConstraint(
            ["parent_lot_id"], ["lots.lot_id"], name=op.f("fk_lots_parent_lot_id_lots")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.product_id"], name=op.f("fk_lots_product_id_products")
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["routes.route_id"], name=op.f("fk_lots_route_id_routes")
        ),
        sa.PrimaryKeyConstraint("lot_id", name=op.f("pk_lots")),
        sa.UniqueConstraint("lot_code", name=op.f("uq_lots_lot_code")),
    )
    op.create_index(op.f("ix_lots_parent_lot_id"), "lots", ["parent_lot_id"], unique=False)
    op.create_index(op.f("ix_lots_product_id"), "lots", ["product_id"], unique=False)
    op.create_index(op.f("ix_lots_start_time"), "lots", ["start_time"], unique=False)
    op.create_table(
        "route_steps",
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("route_id", sa.SmallInteger(), nullable=False),
        sa.Column("sequence_no", sa.SmallInteger(), nullable=False),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("layer", sa.Text(), nullable=False),
        sa.Column("tool_type", sa.Text(), nullable=False),
        sa.CheckConstraint("sequence_no > 0", name=op.f("ck_route_steps_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["route_id"], ["routes.route_id"], name=op.f("fk_route_steps_route_id_routes")
        ),
        sa.ForeignKeyConstraint(
            ["tool_type"],
            ["tool_types.tool_type"],
            name=op.f("fk_route_steps_tool_type_tool_types"),
        ),
        sa.PrimaryKeyConstraint("route_step_id", name=op.f("pk_route_steps")),
        sa.UniqueConstraint(
            "route_id", "sequence_no", name=op.f("uq_route_steps_route_id_sequence_no")
        ),
    )
    op.create_index(op.f("ix_route_steps_tool_type"), "route_steps", ["tool_type"], unique=False)
    op.create_table(
        "lot_events",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("related_lot_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('start', 'split', 'merge', 'hold', 'release', 'complete', 'scrap')",
            name=op.f("ck_lot_events_event_type_valid"),
        ),
        sa.CheckConstraint(
            "event_type NOT IN ('split', 'merge') OR related_lot_id IS NOT NULL",
            name=op.f("ck_lot_events_split_merge_has_related_lot"),
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.lot_id"], name=op.f("fk_lot_events_lot_id_lots")
        ),
        sa.ForeignKeyConstraint(
            ["related_lot_id"], ["lots.lot_id"], name=op.f("fk_lot_events_related_lot_id_lots")
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_lot_events")),
    )
    op.create_index(
        op.f("ix_lot_events_lot_id_event_time"),
        "lot_events",
        ["lot_id", "event_time"],
        unique=False,
    )
    op.create_table(
        "metrology_plans",
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.SmallInteger(), nullable=False),
        sa.Column("wafers_per_lot", sa.SmallInteger(), nullable=False),
        sa.Column("sites_per_wafer", sa.SmallInteger(), nullable=False),
        sa.Column("target", sa.Double(), nullable=False),
        sa.Column("lsl", sa.Double(), nullable=False),
        sa.Column("usl", sa.Double(), nullable=False),
        sa.CheckConstraint(
            "lsl < target AND target < usl", name=op.f("ck_metrology_plans_spec_ordered")
        ),
        sa.CheckConstraint("sites_per_wafer > 0", name=op.f("ck_metrology_plans_sites_positive")),
        sa.CheckConstraint(
            "wafers_per_lot BETWEEN 1 AND 25", name=op.f("ck_metrology_plans_wafers_per_lot_range")
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["parameters.parameter_id"],
            name=op.f("fk_metrology_plans_parameter_id_parameters"),
        ),
        sa.ForeignKeyConstraint(
            ["route_step_id"],
            ["route_steps.route_step_id"],
            name=op.f("fk_metrology_plans_route_step_id_route_steps"),
        ),
        sa.PrimaryKeyConstraint("route_step_id", "parameter_id", name=op.f("pk_metrology_plans")),
    )
    op.create_table(
        "recipes",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("effective_from", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["route_step_id"],
            ["route_steps.route_step_id"],
            name=op.f("fk_recipes_route_step_id_route_steps"),
        ),
        sa.PrimaryKeyConstraint("recipe_id", name=op.f("pk_recipes")),
        sa.UniqueConstraint(
            "route_step_id", "version", name=op.f("uq_recipes_route_step_id_version")
        ),
    )
    op.create_table(
        "wafers",
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("wafer_code", sa.Text(), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'complete', 'scrapped')", name=op.f("ck_wafers_status_valid")
        ),
        sa.CheckConstraint("slot BETWEEN 1 AND 25", name=op.f("ck_wafers_slot_range")),
        sa.ForeignKeyConstraint(["lot_id"], ["lots.lot_id"], name=op.f("fk_wafers_lot_id_lots")),
        sa.PrimaryKeyConstraint("wafer_id", name=op.f("pk_wafers")),
        sa.UniqueConstraint("wafer_code", name=op.f("uq_wafers_wafer_code")),
    )
    op.create_index(op.f("ix_wafers_lot_id"), "wafers", ["lot_id"], unique=False)
    op.create_table(
        "excursions_ground_truth",
        sa.Column("excursion_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("excursion_type", sa.Text(), nullable=False),
        sa.Column("chamber_id", sa.SmallInteger(), nullable=True),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("parameter_id", sa.SmallInteger(), nullable=True),
        sa.Column("spatial_pattern", sa.Text(), nullable=True),
        sa.Column("start_time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_time", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("magnitude_sigma", sa.Double(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "excursion_type <> 'spatial_pattern' OR spatial_pattern IS NOT NULL",
            name=op.f("ck_excursions_ground_truth_spatial_has_pattern"),
        ),
        sa.CheckConstraint(
            "excursion_type IN ('step_shift', 'drift', 'chamber_offset', 'recipe_change', 'spatial_pattern')",
            name=op.f("ck_excursions_ground_truth_type_valid"),
        ),
        sa.CheckConstraint(
            "spatial_pattern IS NULL OR spatial_pattern IN ('center', 'donut', 'edge_loc', 'edge_ring', 'loc', 'near_full', 'random', 'scratch')",
            name=op.f("ck_excursions_ground_truth_pattern_valid"),
        ),
        sa.CheckConstraint(
            "chamber_id IS NOT NULL OR recipe_id IS NOT NULL",
            name=op.f("ck_excursions_ground_truth_has_root_cause"),
        ),
        sa.CheckConstraint(
            "end_time IS NULL OR end_time > start_time",
            name=op.f("ck_excursions_ground_truth_end_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["chamber_id"],
            ["chambers.chamber_id"],
            name=op.f("fk_excursions_ground_truth_chamber_id_chambers"),
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["parameters.parameter_id"],
            name=op.f("fk_excursions_ground_truth_parameter_id_parameters"),
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.recipe_id"],
            name=op.f("fk_excursions_ground_truth_recipe_id_recipes"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["simulation_runs.run_id"],
            name=op.f("fk_excursions_ground_truth_run_id_simulation_runs"),
        ),
        sa.PrimaryKeyConstraint("excursion_id", name=op.f("pk_excursions_ground_truth")),
    )
    op.create_index(
        op.f("ix_excursions_ground_truth_chamber_id"),
        "excursions_ground_truth",
        ["chamber_id"],
        unique=False,
    )
    op.create_table(
        "metrology_measurements",
        sa.Column("time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.SmallInteger(), nullable=False),
        sa.Column("site_no", sa.SmallInteger(), nullable=False),
        sa.Column("site_x_mm", sa.Double(), nullable=False),
        sa.Column("site_y_mm", sa.Double(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.CheckConstraint("site_no >= 1", name=op.f("ck_metrology_measurements_site_positive")),
        sa.CheckConstraint(
            "site_x_mm ^ 2 + site_y_mm ^ 2 <= 150 ^ 2",
            name=op.f("ck_metrology_measurements_site_on_300mm_wafer"),
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["parameters.parameter_id"],
            name=op.f("fk_metrology_measurements_parameter_id_parameters"),
        ),
        sa.ForeignKeyConstraint(
            ["route_step_id"],
            ["route_steps.route_step_id"],
            name=op.f("fk_metrology_measurements_route_step_id_route_steps"),
        ),
        sa.ForeignKeyConstraint(
            ["wafer_id"],
            ["wafers.wafer_id"],
            name=op.f("fk_metrology_measurements_wafer_id_wafers"),
        ),
        sa.PrimaryKeyConstraint(
            "time",
            "wafer_id",
            "route_step_id",
            "parameter_id",
            "site_no",
            name=op.f("pk_metrology_measurements"),
        ),
    )
    op.create_index(
        op.f("ix_metrology_measurements_route_step_id_parameter_id_time"),
        "metrology_measurements",
        ["route_step_id", "parameter_id", "time"],
        unique=False,
    )
    op.create_table(
        "tool_sensor_readings",
        sa.Column("time", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("parameter_id", sa.SmallInteger(), nullable=False),
        sa.Column("chamber_id", sa.SmallInteger(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chamber_id"],
            ["chambers.chamber_id"],
            name=op.f("fk_tool_sensor_readings_chamber_id_chambers"),
        ),
        sa.ForeignKeyConstraint(
            ["parameter_id"],
            ["parameters.parameter_id"],
            name=op.f("fk_tool_sensor_readings_parameter_id_parameters"),
        ),
        sa.ForeignKeyConstraint(
            ["route_step_id"],
            ["route_steps.route_step_id"],
            name=op.f("fk_tool_sensor_readings_route_step_id_route_steps"),
        ),
        sa.ForeignKeyConstraint(
            ["wafer_id"], ["wafers.wafer_id"], name=op.f("fk_tool_sensor_readings_wafer_id_wafers")
        ),
        sa.PrimaryKeyConstraint(
            "time",
            "wafer_id",
            "route_step_id",
            "parameter_id",
            name=op.f("pk_tool_sensor_readings"),
        ),
    )
    op.create_index(
        op.f("ix_tool_sensor_readings_chamber_id_parameter_id_time"),
        "tool_sensor_readings",
        ["chamber_id", "parameter_id", "time"],
        unique=False,
    )
    op.create_table(
        "wafer_bin_summary",
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("bin_code", sa.SmallInteger(), nullable=False),
        sa.Column("die_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "die_count >= 0", name=op.f("ck_wafer_bin_summary_die_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["bin_code"],
            ["sort_bins.bin_code"],
            name=op.f("fk_wafer_bin_summary_bin_code_sort_bins"),
        ),
        sa.ForeignKeyConstraint(
            ["wafer_id"], ["wafers.wafer_id"], name=op.f("fk_wafer_bin_summary_wafer_id_wafers")
        ),
        sa.PrimaryKeyConstraint("wafer_id", "bin_code", name=op.f("pk_wafer_bin_summary")),
    )
    op.create_table(
        "wafer_maps",
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("tested_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("bin_map", postgresql.ARRAY(sa.SmallInteger(), dimensions=2), nullable=False),
        sa.CheckConstraint("array_ndims(bin_map) = 2", name=op.f("ck_wafer_maps_bin_map_is_2d")),
        sa.ForeignKeyConstraint(
            ["wafer_id"], ["wafers.wafer_id"], name=op.f("fk_wafer_maps_wafer_id_wafers")
        ),
        sa.PrimaryKeyConstraint("wafer_id", name=op.f("pk_wafer_maps")),
    )
    op.create_index(op.f("ix_wafer_maps_tested_at"), "wafer_maps", ["tested_at"], unique=False)
    op.create_table(
        "wafer_step_history",
        sa.Column("wafer_id", sa.Integer(), nullable=False),
        sa.Column("route_step_id", sa.Integer(), nullable=False),
        sa.Column("pass_no", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("chamber_id", sa.SmallInteger(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("track_in", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("track_out", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("pass_no >= 1", name=op.f("ck_wafer_step_history_pass_positive")),
        sa.CheckConstraint(
            "track_out >= track_in", name=op.f("ck_wafer_step_history_track_out_after_in")
        ),
        sa.ForeignKeyConstraint(
            ["chamber_id"],
            ["chambers.chamber_id"],
            name=op.f("fk_wafer_step_history_chamber_id_chambers"),
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"], ["lots.lot_id"], name=op.f("fk_wafer_step_history_lot_id_lots")
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["recipes.recipe_id"],
            name=op.f("fk_wafer_step_history_recipe_id_recipes"),
        ),
        sa.ForeignKeyConstraint(
            ["route_step_id"],
            ["route_steps.route_step_id"],
            name=op.f("fk_wafer_step_history_route_step_id_route_steps"),
        ),
        sa.ForeignKeyConstraint(
            ["wafer_id"], ["wafers.wafer_id"], name=op.f("fk_wafer_step_history_wafer_id_wafers")
        ),
        sa.PrimaryKeyConstraint(
            "wafer_id", "route_step_id", "pass_no", name=op.f("pk_wafer_step_history")
        ),
    )
    op.create_index(
        op.f("ix_wafer_step_history_chamber_id_track_in"),
        "wafer_step_history",
        ["chamber_id", "track_in"],
        unique=False,
    )
    op.create_index(
        op.f("ix_wafer_step_history_lot_id"), "wafer_step_history", ["lot_id"], unique=False
    )
    op.create_index(
        op.f("ix_wafer_step_history_recipe_id"), "wafer_step_history", ["recipe_id"], unique=False
    )

    # Hypertables partition by time into 7-day chunks. The composite primary key already
    # starts with `time`, so TimescaleDB's default time index would be a duplicate.
    for table in HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', by_range('time', INTERVAL '7 days'), "
            "create_default_indexes => false)"
        )

    op.execute(WAFER_YIELD_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS wafer_yield")
    op.drop_index(op.f("ix_wafer_step_history_recipe_id"), table_name="wafer_step_history")
    op.drop_index(op.f("ix_wafer_step_history_lot_id"), table_name="wafer_step_history")
    op.drop_index(
        op.f("ix_wafer_step_history_chamber_id_track_in"), table_name="wafer_step_history"
    )
    op.drop_table("wafer_step_history")
    op.drop_index(op.f("ix_wafer_maps_tested_at"), table_name="wafer_maps")
    op.drop_table("wafer_maps")
    op.drop_table("wafer_bin_summary")
    op.drop_index(
        op.f("ix_tool_sensor_readings_chamber_id_parameter_id_time"),
        table_name="tool_sensor_readings",
    )
    op.drop_table("tool_sensor_readings")
    op.drop_index(
        op.f("ix_metrology_measurements_route_step_id_parameter_id_time"),
        table_name="metrology_measurements",
    )
    op.drop_table("metrology_measurements")
    op.drop_index(
        op.f("ix_excursions_ground_truth_chamber_id"), table_name="excursions_ground_truth"
    )
    op.drop_table("excursions_ground_truth")
    op.drop_index(op.f("ix_wafers_lot_id"), table_name="wafers")
    op.drop_table("wafers")
    op.drop_table("recipes")
    op.drop_table("metrology_plans")
    op.drop_index(op.f("ix_lot_events_lot_id_event_time"), table_name="lot_events")
    op.drop_table("lot_events")
    op.drop_index(op.f("ix_route_steps_tool_type"), table_name="route_steps")
    op.drop_table("route_steps")
    op.drop_index(op.f("ix_lots_start_time"), table_name="lots")
    op.drop_index(op.f("ix_lots_product_id"), table_name="lots")
    op.drop_index(op.f("ix_lots_parent_lot_id"), table_name="lots")
    op.drop_table("lots")
    op.drop_table("routes")
    op.drop_table("chambers")
    op.drop_index(op.f("ix_tools_tool_type"), table_name="tools")
    op.drop_table("tools")
    op.drop_index(op.f("ix_products_node_id"), table_name="products")
    op.drop_table("products")
    op.drop_table("tool_types")
    op.drop_table("technology_nodes")
    op.drop_table("sort_bins")
    op.drop_table("simulation_runs")
    op.drop_table("parameters")
