"""ORM models for the fab data model.

Three groups of tables:

* Master data: technology nodes, products, routes, tools/chambers, recipes, parameters, bins.
* Production: lots, wafers, lot events and the genealogy table ``wafer_step_history``, which
  records the exact chamber and recipe every wafer saw at every step. Root-cause analysis
  (phase 3) depends on this table.
* Results: tool sensor readings and metrology (TimescaleDB hypertables), wafer maps and bin
  counts from wafer sort, and the simulator's ground-truth excursion log.

The migration in ``migrations/versions`` is the source of truth for the database; these models
must stay in sync with it (``tests/integration/test_schema.py`` enforces that with
``alembic check``). Things the ORM can't express, such as hypertables and the ``wafer_yield``
view, live only in the migration.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TimestampTZ = TIMESTAMP(timezone=True)

LOT_STATUSES = ("active", "hold", "complete", "scrapped")
WAFER_STATUSES = ("active", "complete", "scrapped")
LOT_EVENT_TYPES = ("start", "split", "merge", "hold", "release", "complete", "scrap")
PARAMETER_KINDS = ("sensor", "metrology")
EXCURSION_TYPES = ("step_shift", "drift", "chamber_offset", "recipe_change", "spatial_pattern")
SPATIAL_PATTERNS = (
    "center",
    "donut",
    "edge_loc",
    "edge_ring",
    "loc",
    "near_full",
    "random",
    "scratch",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# --------------------------------------------------------------------------- master data


class TechnologyNode(Base):
    __tablename__ = "technology_nodes"

    node_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    feature_size_nm: Mapped[int] = mapped_column(SmallInteger)

    __table_args__ = (CheckConstraint("feature_size_nm > 0", name="feature_size_positive"),)


class Product(Base):
    __tablename__ = "products"

    product_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("technology_nodes.node_id"), index=True)
    die_area_cm2: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    # Wafer-map grid. gross_dies counts the cells that are on the wafer.
    map_rows: Mapped[int] = mapped_column(SmallInteger)
    map_cols: Mapped[int] = mapped_column(SmallInteger)
    gross_dies: Mapped[int] = mapped_column(Integer)

    node: Mapped[TechnologyNode] = relationship()

    __table_args__ = (
        CheckConstraint("die_area_cm2 > 0", name="die_area_positive"),
        CheckConstraint("map_rows > 0 AND map_cols > 0", name="map_size_positive"),
        CheckConstraint(
            "gross_dies > 0 AND gross_dies <= map_rows * map_cols", name="gross_dies_fit_map"
        ),
    )


class Route(Base):
    __tablename__ = "routes"

    route_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id"))
    version: Mapped[int] = mapped_column(SmallInteger)

    product: Mapped[Product] = relationship()
    steps: Mapped[list[RouteStep]] = relationship(
        back_populates="route", order_by="RouteStep.sequence_no"
    )

    __table_args__ = (UniqueConstraint("product_id", "version"),)


class ToolType(Base):
    __tablename__ = "tool_types"

    tool_type: Mapped[str] = mapped_column(Text, primary_key=True)
    description: Mapped[str] = mapped_column(Text)


class RouteStep(Base):
    __tablename__ = "route_steps"

    route_step_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.route_id"))
    sequence_no: Mapped[int] = mapped_column(SmallInteger)
    step_name: Mapped[str] = mapped_column(Text)
    layer: Mapped[str] = mapped_column(Text)
    tool_type: Mapped[str] = mapped_column(ForeignKey("tool_types.tool_type"), index=True)

    route: Mapped[Route] = relationship(back_populates="steps")

    __table_args__ = (
        UniqueConstraint("route_id", "sequence_no"),
        CheckConstraint("sequence_no > 0", name="sequence_positive"),
    )


class Tool(Base):
    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tool_type: Mapped[str] = mapped_column(ForeignKey("tool_types.tool_type"), index=True)

    chambers: Mapped[list[Chamber]] = relationship(back_populates="tool")


class Chamber(Base):
    __tablename__ = "chambers"

    chamber_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.tool_id"))
    chamber_code: Mapped[str] = mapped_column(Text)

    tool: Mapped[Tool] = relationship(back_populates="chambers")

    __table_args__ = (UniqueConstraint("tool_id", "chamber_code"),)


class Recipe(Base):
    __tablename__ = "recipes"

    recipe_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_step_id: Mapped[int] = mapped_column(ForeignKey("route_steps.route_step_id"))
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(SmallInteger)
    effective_from: Mapped[datetime] = mapped_column(TimestampTZ)

    __table_args__ = (UniqueConstraint("route_step_id", "version"),)


class Parameter(Base):
    """A tool sensor (e.g. rf_power_w) or a metrology parameter (e.g. cd_nm)."""

    __tablename__ = "parameters"

    parameter_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    unit: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("kind", PARAMETER_KINDS), name="kind_valid"),)


class MetrologyPlan(Base):
    """What gets measured after a step, on how many wafers and sites, against which spec."""

    __tablename__ = "metrology_plans"

    route_step_id: Mapped[int] = mapped_column(
        ForeignKey("route_steps.route_step_id"), primary_key=True
    )
    parameter_id: Mapped[int] = mapped_column(
        ForeignKey("parameters.parameter_id"), primary_key=True
    )
    wafers_per_lot: Mapped[int] = mapped_column(SmallInteger)
    sites_per_wafer: Mapped[int] = mapped_column(SmallInteger)
    target: Mapped[float] = mapped_column(Double)
    lsl: Mapped[float] = mapped_column(Double)
    usl: Mapped[float] = mapped_column(Double)

    __table_args__ = (
        CheckConstraint("wafers_per_lot BETWEEN 1 AND 25", name="wafers_per_lot_range"),
        CheckConstraint("sites_per_wafer > 0", name="sites_positive"),
        CheckConstraint("lsl < target AND target < usl", name="spec_ordered"),
    )


class SortBin(Base):
    __tablename__ = "sort_bins"

    bin_code: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    is_pass: Mapped[bool]

    __table_args__ = (CheckConstraint("bin_code >= 1", name="bin_code_positive"),)


# --------------------------------------------------------------------------- production


class SimulationRun(Base):
    """Provenance: which profile and seed produced the data currently loaded."""

    __tablename__ = "simulation_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile: Mapped[str] = mapped_column(Text)
    seed: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=text("now()"))


class Lot(Base):
    __tablename__ = "lots"

    lot_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_code: Mapped[str] = mapped_column(Text, unique=True)
    # Set when this lot was split off another lot.
    parent_lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.lot_id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.product_id"), index=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.route_id"))
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("3"))
    start_time: Mapped[datetime] = mapped_column(TimestampTZ, index=True)
    status: Mapped[str] = mapped_column(Text)

    product: Mapped[Product] = relationship()
    parent: Mapped[Lot | None] = relationship(remote_side=[lot_id])
    wafers: Mapped[list[Wafer]] = relationship(back_populates="lot")

    __table_args__ = (
        CheckConstraint(_in("status", LOT_STATUSES), name="status_valid"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
    )


class Wafer(Base):
    __tablename__ = "wafers"

    wafer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wafer_code: Mapped[str] = mapped_column(Text, unique=True)
    # Current lot. Lot membership at the time of each step is in wafer_step_history.
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.lot_id"), index=True)
    slot: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text)

    lot: Mapped[Lot] = relationship(back_populates="wafers")
    history: Mapped[list[WaferStepHistory]] = relationship(back_populates="wafer")

    __table_args__ = (
        CheckConstraint("slot BETWEEN 1 AND 25", name="slot_range"),
        CheckConstraint(_in("status", WAFER_STATUSES), name="status_valid"),
    )


class LotEvent(Base):
    __tablename__ = "lot_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.lot_id"))
    event_type: Mapped[str] = mapped_column(Text)
    event_time: Mapped[datetime] = mapped_column(TimestampTZ)
    # Split: the child lot. Merge: the lot merged in.
    related_lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.lot_id"))
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("event_type", LOT_EVENT_TYPES), name="event_type_valid"),
        CheckConstraint(
            "event_type NOT IN ('split', 'merge') OR related_lot_id IS NOT NULL",
            name="split_merge_has_related_lot",
        ),
        Index(None, "lot_id", "event_time"),
    )


class WaferStepHistory(Base):
    """Genealogy: which chamber, recipe and lot a wafer was in at each step."""

    __tablename__ = "wafer_step_history"

    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), primary_key=True)
    route_step_id: Mapped[int] = mapped_column(
        ForeignKey("route_steps.route_step_id"), primary_key=True
    )
    # Rework runs a step again; each run is a separate pass.
    pass_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    lot_id: Mapped[int] = mapped_column(ForeignKey("lots.lot_id"))
    chamber_id: Mapped[int] = mapped_column(ForeignKey("chambers.chamber_id"))
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.recipe_id"))
    track_in: Mapped[datetime] = mapped_column(TimestampTZ)
    track_out: Mapped[datetime] = mapped_column(TimestampTZ)

    wafer: Mapped[Wafer] = relationship(back_populates="history")
    chamber: Mapped[Chamber] = relationship()
    recipe: Mapped[Recipe] = relationship()

    __table_args__ = (
        CheckConstraint("track_out >= track_in", name="track_out_after_in"),
        CheckConstraint("pass_no >= 1", name="pass_positive"),
        # Commonality analysis: "which wafers went through chamber X in this window?"
        Index(None, "chamber_id", "track_in"),
        Index(None, "recipe_id"),
        Index(None, "lot_id"),
    )


# --------------------------------------------------------------------------- results


class ToolSensorReading(Base):
    """Per wafer-step summary of a chamber sensor. TimescaleDB hypertable on ``time``."""

    __tablename__ = "tool_sensor_readings"

    time: Mapped[datetime] = mapped_column(TimestampTZ, primary_key=True)
    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), primary_key=True)
    route_step_id: Mapped[int] = mapped_column(
        ForeignKey("route_steps.route_step_id"), primary_key=True
    )
    parameter_id: Mapped[int] = mapped_column(
        ForeignKey("parameters.parameter_id"), primary_key=True
    )
    chamber_id: Mapped[int] = mapped_column(ForeignKey("chambers.chamber_id"))
    value: Mapped[float] = mapped_column(Double)

    __table_args__ = (Index(None, "chamber_id", "parameter_id", "time"),)


class MetrologyMeasurement(Base):
    """One site of an inline metrology measurement. TimescaleDB hypertable on ``time``."""

    __tablename__ = "metrology_measurements"

    time: Mapped[datetime] = mapped_column(TimestampTZ, primary_key=True)
    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), primary_key=True)
    route_step_id: Mapped[int] = mapped_column(
        ForeignKey("route_steps.route_step_id"), primary_key=True
    )
    parameter_id: Mapped[int] = mapped_column(
        ForeignKey("parameters.parameter_id"), primary_key=True
    )
    site_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    # Site position in mm from wafer centre.
    site_x_mm: Mapped[float] = mapped_column(Double)
    site_y_mm: Mapped[float] = mapped_column(Double)
    value: Mapped[float] = mapped_column(Double)

    __table_args__ = (
        CheckConstraint("site_no >= 1", name="site_positive"),
        CheckConstraint("site_x_mm ^ 2 + site_y_mm ^ 2 <= 150 ^ 2", name="site_on_300mm_wafer"),
        Index(None, "route_step_id", "parameter_id", "time"),
    )


class WaferMap(Base):
    """Wafer sort result as a 2D grid of bin codes: 0 = off wafer, 1 = pass, >= 2 = fail bin.

    FabEye's format (0 off, 1 good, 2 fail) is this grid with every fail bin mapped to 2.
    """

    __tablename__ = "wafer_maps"

    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), primary_key=True)
    tested_at: Mapped[datetime] = mapped_column(TimestampTZ, index=True)
    bin_map: Mapped[list[list[int]]] = mapped_column(ARRAY(SmallInteger, dimensions=2))

    __table_args__ = (CheckConstraint("array_ndims(bin_map) = 2", name="bin_map_is_2d"),)


class WaferBinSummary(Base):
    __tablename__ = "wafer_bin_summary"

    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), primary_key=True)
    bin_code: Mapped[int] = mapped_column(ForeignKey("sort_bins.bin_code"), primary_key=True)
    die_count: Mapped[int] = mapped_column(Integer)

    __table_args__ = (CheckConstraint("die_count >= 0", name="die_count_non_negative"),)


class ExcursionGroundTruth(Base):
    """Every excursion the simulator injected. Detection is scored against this table."""

    __tablename__ = "excursions_ground_truth"

    excursion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.run_id"))
    excursion_type: Mapped[str] = mapped_column(Text)
    chamber_id: Mapped[int | None] = mapped_column(ForeignKey("chambers.chamber_id"), index=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.recipe_id"))
    parameter_id: Mapped[int | None] = mapped_column(ForeignKey("parameters.parameter_id"))
    spatial_pattern: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(TimestampTZ)
    end_time: Mapped[datetime | None] = mapped_column(TimestampTZ)
    magnitude_sigma: Mapped[float | None] = mapped_column(Double)
    description: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("excursion_type", EXCURSION_TYPES), name="type_valid"),
        CheckConstraint(
            f"spatial_pattern IS NULL OR {_in('spatial_pattern', SPATIAL_PATTERNS)}",
            name="pattern_valid",
        ),
        CheckConstraint("end_time IS NULL OR end_time > start_time", name="end_after_start"),
        CheckConstraint("chamber_id IS NOT NULL OR recipe_id IS NOT NULL", name="has_root_cause"),
        CheckConstraint(
            "excursion_type <> 'spatial_pattern' OR spatial_pattern IS NOT NULL",
            name="spatial_has_pattern",
        ),
    )


# --------------------------------------------------------------------------- SPC (phase 3)


class WaferPatternTruth(Base):
    """Sorted wafers whose map shows an injected spatial pattern, and which excursion put it
    there (the strongest, if several touched the wafer). Wafers not listed show no pattern;
    wafer-map classification (FabEye, phase 5a) is scored against this table."""

    __tablename__ = "wafer_pattern_truth"

    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), primary_key=True)
    excursion_id: Mapped[int] = mapped_column(
        ForeignKey("excursions_ground_truth.excursion_id"), index=True
    )


SPC_TABLES = ("spc_control_limits", "spc_alarms")  # written by waferlens.spc, not the loader
SPC_SCOPES = ("chamber", "tool")
SPC_SOURCES = ("sensor", "metrology")
SPC_CHARTS = ("we1", "we2", "we3", "we4", "ewma", "cusum", "t2")


class SpcControlLimit(Base):
    """Phase I limits for one monitored series, frozen for Phase II monitoring.

    A series is a source (sensor / metrology), a scope (one chamber, or a whole tool pooled)
    and a parameter; metrology series are also per route step. Hotelling T² series have no
    parameter: they cover all metrology parameters of a step together (``t2_*`` columns).
    Re-estimating creates a new ``version``; alarms point at the version that raised them.
    """

    __tablename__ = "spc_control_limits"

    limit_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    chamber_id: Mapped[int | None] = mapped_column(ForeignKey("chambers.chamber_id"))
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.tool_id"))
    parameter_id: Mapped[int | None] = mapped_column(ForeignKey("parameters.parameter_id"))
    route_step_id: Mapped[int | None] = mapped_column(ForeignKey("route_steps.route_step_id"))
    is_multivariate: Mapped[bool]
    version: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    center: Mapped[float | None] = mapped_column(Double)
    sigma: Mapped[float | None] = mapped_column(Double)
    t2_dims: Mapped[int | None] = mapped_column(SmallInteger)
    t2_limit: Mapped[float | None] = mapped_column(Double)
    # Phase I mean vector and inverse covariance, so frozen T² limits can be reused.
    t2_mean: Mapped[list[float] | None] = mapped_column(ARRAY(Double))
    t2_cov_inv: Mapped[list[list[float]] | None] = mapped_column(ARRAY(Double, dimensions=2))
    n_baseline: Mapped[int] = mapped_column(Integer)
    baseline_start: Mapped[datetime] = mapped_column(TimestampTZ)
    baseline_end: Mapped[datetime] = mapped_column(TimestampTZ)
    method: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(TimestampTZ, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "source", "scope", "chamber_id", "tool_id", "parameter_id", "route_step_id",
            "is_multivariate", "version", postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(_in("source", SPC_SOURCES), name="source_valid"),
        CheckConstraint(_in("scope", SPC_SCOPES), name="scope_valid"),
        CheckConstraint("(scope = 'chamber') = (chamber_id IS NOT NULL)", name="chamber_scope"),
        CheckConstraint(
            "is_multivariate = (parameter_id IS NULL)", name="multivariate_has_no_parameter"
        ),
        CheckConstraint(
            "is_multivariate OR (center IS NOT NULL AND sigma > 0)", name="univariate_limits"
        ),
        CheckConstraint(
            "NOT is_multivariate OR (t2_dims >= 2 AND t2_limit > 0 AND t2_mean IS NOT NULL"
            " AND t2_cov_inv IS NOT NULL)",
            name="t2_limits",
        ),
        CheckConstraint("baseline_end > baseline_start", name="baseline_ordered"),
    )  # fmt: skip


class SpcAlarm(Base):
    """One point that signalled on one chart. Unique per series, chart and measurement, so
    rerunning SPC can never duplicate an alarm."""

    __tablename__ = "spc_alarms"

    alarm_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    limit_id: Mapped[int] = mapped_column(ForeignKey("spc_control_limits.limit_id"))
    chart: Mapped[str] = mapped_column(Text)
    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"))
    route_step_id: Mapped[int] = mapped_column(ForeignKey("route_steps.route_step_id"))
    pass_no: Mapped[int] = mapped_column(SmallInteger)
    measured_at: Mapped[datetime] = mapped_column(TimestampTZ)
    statistic: Mapped[float] = mapped_column(Double)
    direction: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("limit_id", "chart", "wafer_id", "route_step_id", "pass_no"),
        CheckConstraint(_in("chart", SPC_CHARTS), name="chart_valid"),
        CheckConstraint("direction IS NULL OR direction IN ('up', 'down')", name="direction_valid"),
        Index(None, "measured_at"),
        Index(None, "wafer_id"),
    )


# --------------------------------------------------------------------------- root cause (phase 3)

ROOTCAUSE_TABLES = ("rootcause_candidates",)  # written by waferlens.rootcause, not the loader


class WaferPattern(Base):
    """FabEye's classification of one sorted wafer map (waferlens.patterns): the most likely
    WM-811K pattern, its confidence, FabEye's auto-accept flag and conformal prediction set."""

    __tablename__ = "wafer_patterns"

    wafer_id: Mapped[int] = mapped_column(ForeignKey("wafers.wafer_id"), primary_key=True)
    pattern: Mapped[str] = mapped_column(Text, index=True)
    confidence: Mapped[float] = mapped_column(Double)
    auto_accept: Mapped[bool]
    prediction_set: Mapped[list[str]] = mapped_column(ARRAY(Text))
    alpha: Mapped[float] = mapped_column(Double)
    model: Mapped[str] = mapped_column(Text)
    scored_at: Mapped[datetime] = mapped_column(TimestampTZ)

    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),)


PATTERN_TABLES = ("wafer_patterns",)  # written by waferlens.patterns (FabEye), not the loader

FACTOR_TYPES = ("chamber", "recipe")


class RootcauseCandidate(Base):
    """One suspect from a commonality analysis of one time window: a chamber or recipe version
    the low-yield wafers met inside the window, with its 2x2 evidence and its rank.

    The evaluation runs one analysis per injected excursion, given only the excursion's time
    window, and ``excursion_id`` records which; the rank of the true cause is the score.
    """

    __tablename__ = "rootcause_candidates"

    candidate_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    excursion_id: Mapped[int] = mapped_column(
        ForeignKey("excursions_ground_truth.excursion_id"), index=True
    )
    window_start: Mapped[datetime] = mapped_column(TimestampTZ)
    window_end: Mapped[datetime] = mapped_column(TimestampTZ)
    factor_type: Mapped[str] = mapped_column(Text)
    chamber_id: Mapped[int | None] = mapped_column(ForeignKey("chambers.chamber_id"))
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.recipe_id"))
    n_through: Mapped[int] = mapped_column(Integer)
    low_through: Mapped[int] = mapped_column(Integer)
    n_population: Mapped[int] = mapped_column(Integer)
    n_low: Mapped[int] = mapped_column(Integer)
    lift: Mapped[float | None] = mapped_column(Double)
    chi2: Mapped[float | None] = mapped_column(Double)
    suspect_rank: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("excursion_id", "factor_type", "chamber_id", "recipe_id",
                         postgresql_nulls_not_distinct=True),
        CheckConstraint(_in("factor_type", FACTOR_TYPES), name="factor_type_valid"),
        CheckConstraint(
            "(factor_type = 'chamber') = (chamber_id IS NOT NULL AND recipe_id IS NULL)"
            " AND (factor_type = 'recipe') = (recipe_id IS NOT NULL AND chamber_id IS NULL)",
            name="one_factor",
        ),
        CheckConstraint("0 <= low_through AND low_through <= n_through"
                        " AND n_through <= n_population", name="counts_consistent"),
        CheckConstraint("suspect_rank >= 1", name="rank_positive"),
        CheckConstraint("window_end > window_start", name="window_ordered"),
    )  # fmt: skip


# --------------------------------------------------------------------------- external datasets


class ExternalBase(DeclarativeBase):
    """Real external datasets. A separate metadata from the simulated fab, so reloading the
    fab (which truncates every ``Base`` table) never touches them."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


SECOM_SENSORS = 590  # the UCI page says 591; the file has 590 columns (docs/data/secom.md)


class SecomRun(ExternalBase):
    """One production entity from UCI SECOM, in file order, with its in-house test result."""

    __tablename__ = "secom_runs"

    run_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    # The source has no timezone; stored as UTC by assumption.
    run_time: Mapped[datetime] = mapped_column(TimestampTZ, index=True)
    failed: Mapped[bool]

    readings: Mapped[list[SecomReading]] = relationship(back_populates="run")


class SecomReading(ExternalBase):
    """One sensor value of one run, in long format. Missing values (4.5%) have no row."""

    __tablename__ = "secom_readings"

    run_id: Mapped[int] = mapped_column(ForeignKey("secom_runs.run_id"), primary_key=True)
    sensor_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    value: Mapped[float] = mapped_column(Double)

    run: Mapped[SecomRun] = relationship(back_populates="readings")

    __table_args__ = (
        CheckConstraint(f"sensor_no BETWEEN 1 AND {SECOM_SENSORS}", name="sensor_no_range"),
        Index(None, "sensor_no"),
    )


# --------------------------------------------------------------------------- SECOM model results
# Written by waferlens.ml.store after each experiment; replaced, not appended (latest model only;
# MLflow keeps the history). On ExternalBase because they derive from SECOM alone.


class SecomModelVersion(ExternalBase):
    """The registered fail-prediction model and its holdout result (one row per version)."""

    __tablename__ = "secom_model_versions"

    model_version: Mapped[str] = mapped_column(Text, primary_key=True)
    config: Mapped[str] = mapped_column(Text)
    trained_at: Mapped[datetime] = mapped_column(TimestampTZ)
    train_runs: Mapped[int]
    test_runs: Mapped[int]
    test_fails: Mapped[int]
    test_starts: Mapped[datetime] = mapped_column(TimestampTZ)
    holdout_pr_auc: Mapped[float] = mapped_column(Double)
    holdout_pr_auc_low: Mapped[float] = mapped_column(Double)
    holdout_pr_auc_high: Mapped[float] = mapped_column(Double)
    holdout_prevalence: Mapped[float] = mapped_column(Double)
    random_split_pr_auc: Mapped[float] = mapped_column(Double)
    baseline_pr_auc: Mapped[float] = mapped_column(Double)
    alarm_threshold: Mapped[float] = mapped_column(Double)
    mlflow_run_id: Mapped[str] = mapped_column(Text)


class SecomScore(ExternalBase):
    """Out-of-sample fail score of one run: walk-forward inside the training period, the
    registered model on the holdout. The first walk-forward block has no score."""

    __tablename__ = "secom_scores"

    run_id: Mapped[int] = mapped_column(ForeignKey("secom_runs.run_id"), primary_key=True)
    model_version: Mapped[str] = mapped_column(ForeignKey("secom_model_versions.model_version"))
    split: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Double)
    alarm: Mapped[bool]

    __table_args__ = (CheckConstraint("split IN ('walk_forward', 'holdout')", name="split"),)


class SecomSensorImportance(ExternalBase):
    """Mean |contribution| of each sensor to the registered model's holdout scores."""

    __tablename__ = "secom_sensor_importance"

    sensor_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    model_version: Mapped[str] = mapped_column(ForeignKey("secom_model_versions.model_version"))
    importance: Mapped[float] = mapped_column(Double)
    importance_rank: Mapped[int] = mapped_column(SmallInteger)
    missing_pct: Mapped[float] = mapped_column(Double)

    __table_args__ = (
        CheckConstraint(f"sensor_no BETWEEN 1 AND {SECOM_SENSORS}", name="sensor_no_range"),
    )
