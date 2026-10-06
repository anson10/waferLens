"""Wafer sort: per-die pass/fail and bin from a Poisson defect model.

For each die, local defect density D0 is the sum of three parts:

* base:      node D0, higher towards the wafer edge, times the wafer's excursion exposure
             (each chamber excursion the wafer went through above the threshold multiplies it);
* parametric: base D0 * metrology penalty (true metrology beyond 2 sigma, all steps);
* pattern:   a spatial field (edge ring, scratch, ...) on wafers that went through a chamber
             during a spatial-pattern excursion. Invisible to sensors and metrology.

A die fails with probability 1 - exp(-A · D0) (Poisson yield, A = die area). A failing die's
bin follows whichever part caused it: the excursion tool type's fail bin for patterns,
leakage (3) for parametric loss, and the configured base mix otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyarrow as pa

from waferlens.simulate.config import FabConfig
from waferlens.simulate.excursions import CHAMBER_TYPES, Excursion, Plan
from waferlens.simulate.master import Master, ProductGeometry

PATTERN_PEAK_FAIL = 2.0  # A·D0 at a pattern's peak per sigma of intensity (p ≈ 1 - e^-2m)
LEAKAGE_BIN = 3
BATCH = 2000


@dataclass
class WaferMaps:
    table: pa.Table  # wafer_id, tested_at (minutes), bin_map list<list<int16>>
    good_dies: np.ndarray
    tested_dies: np.ndarray


def pattern_field(
    name: str, x: np.ndarray, y: np.ndarray, geometry: np.random.Generator
) -> np.ndarray:
    """Defect intensity in [0, 1] (near_full: 3) for dies at normalised (x, y)."""
    r = np.hypot(x, y)
    if name == "center":
        return np.exp(-((r / 0.35) ** 2))
    if name == "donut":
        return np.exp(-(((r - 0.55) / 0.12) ** 2))
    if name == "edge_ring":
        return np.clip((r - 0.8) / 0.12, 0, 1)
    if name == "edge_loc":
        theta0 = geometry.uniform(-np.pi, np.pi)
        angle = np.abs((np.arctan2(y, x) - theta0 + np.pi) % (2 * np.pi) - np.pi)
        return np.clip((r - 0.75) / 0.12, 0, 1) * (angle < 0.6)
    if name == "loc":
        rho, phi = 0.7 * np.sqrt(geometry.random()), geometry.uniform(-np.pi, np.pi)
        cx, cy = rho * np.cos(phi), rho * np.sin(phi)
        return np.exp(-((np.hypot(x - cx, y - cy) / 0.2) ** 2))
    if name == "scratch":
        length = geometry.uniform(0.6, 1.2)
        phi = geometry.uniform(0, np.pi)
        cx, cy = geometry.uniform(-0.4, 0.4, 2)
        dx, dy = np.cos(phi), np.sin(phi)
        along = np.clip((x - cx) * dx + (y - cy) * dy, -length / 2, length / 2)
        dist = np.hypot(x - (cx + along * dx), y - (cy + along * dy))
        return np.exp(-((dist / 0.035) ** 2))
    if name == "random":
        return np.full_like(x, 0.25)
    if name == "near_full":
        return np.full_like(x, 3.0)
    raise ValueError(f"unknown spatial pattern {name}")


def _exposure(
    cfg: FabConfig, plan: Plan, history: pd.DataFrame, n_wafers: int
) -> tuple[np.ndarray, list[tuple[np.ndarray, Excursion]]]:
    """D0 multiplier per wafer from chamber excursions, and the wafers each spatial
    excursion touched."""
    chamber = history["chamber_id"].to_numpy()
    track_in = history["track_in"].to_numpy()
    wafer_idx = history["wafer_idx"].to_numpy()
    k = cfg.yield_model.excursion_d0_per_sigma
    threshold = cfg.yield_model.excursion_d0_threshold_sigma
    multiplier = np.ones(n_wafers)
    for ex in plan.of_type(*CHAMBER_TYPES):
        hit = np.flatnonzero(chamber == ex.chamber_id)
        excess = np.maximum(0.0, np.abs(ex.effect(track_in[hit])) - threshold)
        np.multiply.at(multiplier, wafer_idx[hit], 1 + k * excess)
    touched = []
    for ex in plan.of_type("spatial_pattern"):
        hit = (chamber == ex.chamber_id) & (track_in >= ex.start) & (track_in < ex.end)
        touched.append((np.unique(wafer_idx[hit]), ex))
    return multiplier, touched


def generate_wafer_maps(
    cfg: FabConfig,
    master: Master,
    plan: Plan,
    history: pd.DataFrame,
    sorted_wafers: pd.DataFrame,
    metrology_penalty: np.ndarray,
    n_wafers: int,
    rng: np.random.Generator,
) -> WaferMaps:
    ym = cfg.yield_model
    multiplier, touched = _exposure(cfg, plan, history, n_wafers)

    # Strongest spatial excursion per wafer (pattern_hit_prob of touched wafers show it).
    pattern_of = np.full(n_wafers, -1)
    strength = np.zeros(n_wafers)
    for wafers, ex in touched:
        shows = wafers[rng.random(len(wafers)) < ym.pattern_hit_prob]
        stronger = shows[ex.magnitude > strength[shows]]
        pattern_of[stronger] = ex.excursion_id
        strength[stronger] = ex.magnitude
    by_id = {ex.excursion_id: ex for ex in plan.excursions}
    fail_bin = {
        ex.excursion_id: cfg.tool_types[master.chamber_tool_type[ex.chamber_id]].fail_bin
        for ex in plan.of_type("spatial_pattern")
        if ex.chamber_id is not None
    }

    base_bins = np.array(list(ym.base_fail_bins), dtype=np.int16)
    base_p = np.array(list(ym.base_fail_bins.values()))
    base_p = base_p / base_p.sum()

    tables: list[pa.Table] = []
    good = np.zeros(n_wafers, dtype=np.int64)
    tested = np.zeros(n_wafers, dtype=np.int64)
    for geo in master.products:
        mine = sorted_wafers[sorted_wafers["product_idx"] == geo.product_id - 1]
        for start in range(0, len(mine), BATCH):
            batch = mine.iloc[start : start + BATCH]
            w = batch["wafer_idx"].to_numpy()
            bins = _sort_batch(
                cfg, geo, w, multiplier, metrology_penalty, pattern_of, by_id, fail_bin,
                base_bins, base_p, rng,
            )  # fmt: skip
            good[w] = (bins == 1).sum(axis=1)
            tested[w] = bins.shape[1]
            tables.append(_to_arrow(geo, w, batch["tested_at"].to_numpy(), bins))

    table = pa.concat_tables(tables).sort_by("wafer_id") if tables else _empty_table()
    return WaferMaps(table, good, tested)


def _sort_batch(
    cfg: FabConfig,
    geo: ProductGeometry,
    w: np.ndarray,
    multiplier: np.ndarray,
    penalty: np.ndarray,
    pattern_of: np.ndarray,
    by_id: dict[int, Excursion],
    fail_bin: dict[int, int],
    base_bins: np.ndarray,
    base_p: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Bin code per (wafer, on-wafer die)."""
    ym = cfg.yield_model
    area = geo.die_area_cm2
    r = np.hypot(geo.x, geo.y)
    edge = 1 + ym.edge_loss * np.clip((r - 0.85) / 0.15, 0, 1)
    d_base = geo.base_d0 * edge[None, :] * multiplier[w][:, None]
    d_param = np.broadcast_to(
        (geo.base_d0 * ym.metrology_penalty * penalty[w])[:, None], d_base.shape
    )
    d_pattern = np.zeros_like(d_base)
    pattern_bin = np.zeros(len(w), dtype=np.int16)
    for i in np.flatnonzero(pattern_of[w] >= 0):
        ex = by_id[int(pattern_of[w[i]])]
        assert ex.spatial_pattern is not None
        geometry = np.random.default_rng(ex.geometry_seed)  # same defect geometry per excursion
        field = pattern_field(ex.spatial_pattern, geo.x, geo.y, geometry)
        d_pattern[i] = field * PATTERN_PEAK_FAIL * ex.magnitude / area
        pattern_bin[i] = fail_bin[ex.excursion_id]

    total = d_base + d_param + d_pattern
    fails = rng.random(total.shape) < 1 - np.exp(-area * total)
    cause = rng.random(total.shape) * total
    bins = np.ones(total.shape, dtype=np.int16)
    is_pattern = fails & (cause < d_pattern)
    is_param = fails & ~is_pattern & (cause < d_pattern + d_param)
    is_base = fails & ~is_pattern & ~is_param
    bins[is_pattern] = np.broadcast_to(pattern_bin[:, None], bins.shape)[is_pattern]
    bins[is_param] = LEAKAGE_BIN
    bins[is_base] = rng.choice(base_bins, size=int(is_base.sum()), p=base_p)
    return bins


def _to_arrow(
    geo: ProductGeometry, w: np.ndarray, tested_at: np.ndarray, bins: np.ndarray
) -> pa.Table:
    """Full grids (0 = off wafer) as list<list<int16>>, built from flat buffers."""
    g = geo.grid
    grids = np.zeros((len(w), g, g), dtype=np.int16)
    grids[:, geo.on_wafer] = bins
    flat = pa.array(grids.ravel(), type=pa.int16())
    rows = pa.ListArray.from_arrays(pa.array(np.arange(0, len(w) * g * g + 1, g, dtype=np.int32)),
                                    flat)  # fmt: skip
    maps = pa.ListArray.from_arrays(pa.array(np.arange(0, len(w) * g + 1, g, dtype=np.int32)),
                                    rows)  # fmt: skip
    return pa.table(
        {
            "wafer_id": pa.array((w + 1).astype(np.int32)),
            "tested_at": pa.array(tested_at.astype(np.float64)),
            "bin_map": maps,
        }
    )


def _empty_table() -> pa.Table:
    return pa.table(
        {
            "wafer_id": pa.array([], pa.int32()),
            "tested_at": pa.array([], pa.float64()),
            "bin_map": pa.array([], pa.list_(pa.list_(pa.int16()))),
        }
    )
