"""Typed fab configuration, loaded from ``config/fab.yaml``."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator

from waferlens.db.models import EXCURSION_TYPES, SPATIAL_PATTERNS

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "fab.yaml"

ExcursionType = Literal["step_shift", "drift", "chamber_offset", "recipe_change", "spatial_pattern"]
Range = tuple[float, float]


class _Model(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}


class ProfileSpec(_Model):
    lots: PositiveInt
    days: PositiveInt
    excursions: int = Field(ge=0)
    benign_recipe_changes: int = Field(ge=0)


class NodeSpec(_Model):
    name: str
    feature_size_nm: PositiveInt
    base_d0: PositiveFloat


class ProductSpec(_Model):
    code: str
    node: str
    map_grid: int = Field(ge=8, le=80)
    mix: PositiveFloat


class SortBinSpec(_Model):
    code: int = Field(ge=1)
    name: str
    is_pass: bool


class SensorSpec(_Model):
    nominal: float
    sigma: PositiveFloat
    unit: str


class ToolTypeSpec(_Model):
    description: str
    tools: PositiveInt
    chambers_per_tool: int = Field(ge=1, le=26)
    process_minutes: PositiveFloat
    fail_bin: int
    spatial_patterns: list[str] = []
    sensors: dict[str, SensorSpec]

    @property
    def primary_sensor(self) -> str:
        return next(iter(self.sensors))


class MetrologySpec(_Model):
    parameter: str
    unit: str
    target: float
    sigma: PositiveFloat
    scales_with_node: bool = False
    radial: float = 0.0


class StepSpec(_Model):
    name: str
    layer: str
    tool_type: str
    metrology: list[MetrologySpec] = []
    correlations: list[tuple[str, str, float]] = []


class LogisticsSpec(_Model):
    wafers_per_lot: int = Field(ge=2, le=25)
    queue_hours_mean: PositiveFloat
    hold_prob_per_lot: float = Field(ge=0, le=1)
    hold_hours: Range
    split_prob_per_lot: float = Field(ge=0, le=1)
    rework_prob_per_litho_step: float = Field(ge=0, le=1)
    rework_delay_minutes: PositiveFloat
    scrap_prob_per_wafer_step: float = Field(ge=0, le=1)
    metrology_delay_minutes: Range
    sort_delay_hours: Range


class MeasurementSpec(_Model):
    metrology_wafers_per_lot: int = Field(ge=1, le=25)
    spec_sigma: PositiveFloat
    site_noise_ratio: float = Field(ge=0)
    chamber_bias_sigma: float = Field(ge=0)
    sensor_to_metrology_coupling: float = Field(ge=0, lt=1)


class YieldModelSpec(_Model):
    edge_loss: float = Field(ge=0)
    metrology_penalty: float = Field(ge=0)
    excursion_d0_per_sigma: float = Field(ge=0)
    excursion_d0_threshold_sigma: float = Field(ge=0)
    pattern_hit_prob: float = Field(ge=0, le=1)
    base_fail_bins: dict[int, float]


class ExcursionSpec(_Model):
    type_weights: dict[ExcursionType, float]
    magnitude_sigma: dict[ExcursionType, Range]
    duration_days: dict[ExcursionType, Range]
    tool_type_weights: dict[str, float]


class FabConfig(_Model):
    start_date: date
    profiles: dict[str, ProfileSpec]
    nodes: list[NodeSpec]
    products: list[ProductSpec]
    sort_bins: list[SortBinSpec]
    tool_types: dict[str, ToolTypeSpec]
    route: list[StepSpec]
    logistics: LogisticsSpec
    measurement: MeasurementSpec
    yield_model: YieldModelSpec
    excursions: ExcursionSpec

    @model_validator(mode="after")
    def _check_references(self) -> FabConfig:
        nodes = {n.name for n in self.nodes}
        bins = {b.code for b in self.sort_bins}
        errors: list[str] = []

        errors += [f"product {p.code}: unknown node {p.node}" for p in self.products
                   if p.node not in nodes]  # fmt: skip
        if not math.isclose(sum(p.mix for p in self.products), 1.0, abs_tol=1e-6):
            errors.append("product mix must sum to 1")
        if [b.code for b in self.sort_bins if b.is_pass] != [1]:
            errors.append("bin 1 must be the only pass bin")

        units: dict[str, str] = {}
        for name, tt in self.tool_types.items():
            if tt.fail_bin not in bins:
                errors.append(f"tool type {name}: unknown fail_bin {tt.fail_bin}")
            errors += [f"tool type {name}: unknown spatial pattern {p}"
                       for p in tt.spatial_patterns if p not in SPATIAL_PATTERNS]  # fmt: skip
            for sensor, spec in tt.sensors.items():
                if units.setdefault(sensor, spec.unit) != spec.unit:
                    errors.append(f"sensor {sensor} has two units")

        for step in self.route:
            if step.tool_type not in self.tool_types:
                errors.append(f"step {step.name}: unknown tool type {step.tool_type}")
            measured = {m.parameter for m in step.metrology}
            for m in step.metrology:
                if units.setdefault(m.parameter, m.unit) != m.unit:
                    errors.append(f"parameter {m.parameter} has two units")
            for a, b, rho in step.correlations:
                if a not in measured or b not in measured or not -1 < rho < 1:
                    errors.append(f"step {step.name}: bad correlation {a}/{b}/{rho}")

        if len({s.name for s in self.route}) != len(self.route):
            errors.append("route step names must be unique")
        if set(self.excursions.type_weights) != set(EXCURSION_TYPES):
            errors.append("excursions.type_weights must cover every excursion type")
        unknown = [t for t in self.excursions.tool_type_weights if t not in self.tool_types]
        errors += [f"excursions: unknown tool type {t}" for t in unknown]
        if sum(self.yield_model.base_fail_bins.values()) <= 0 or not set(
            self.yield_model.base_fail_bins
        ) <= bins - {1}:
            errors.append("yield_model.base_fail_bins must be fail bins with positive weight")

        if errors:
            raise ValueError("; ".join(errors))
        return self

    def node(self, name: str) -> NodeSpec:
        return next(n for n in self.nodes if n.name == name)


def load_config(path: Path = DEFAULT_CONFIG) -> FabConfig:
    with path.open() as f:
        return FabConfig.model_validate(yaml.safe_load(f))
