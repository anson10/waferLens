"""Master data: nodes, products, routes, tools, chambers, parameters, metrology plans, bins.

Everything here is derived from the config and is identical for every seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from waferlens.simulate.config import FabConfig, MetrologySpec

WAFER_DIAMETER_MM = 300.0
EDGE_EXCLUSION = 0.97  # die centres beyond 97% of the radius are off the usable wafer


@dataclass(frozen=True)
class MeasuredParam:
    parameter_id: int
    target: float
    sigma: float
    radial: float


@dataclass(frozen=True)
class MetrologyStep:
    """Everything needed to generate metrology for one route step of one product."""

    route_step_id: int
    params: list[MeasuredParam]
    cholesky: np.ndarray  # lower-triangular factor of the parameter correlation matrix


@dataclass(frozen=True)
class ProductGeometry:
    product_id: int
    grid: int
    die_area_cm2: float
    on_wafer: np.ndarray  # (grid, grid) bool
    x: np.ndarray  # die-centre coordinates of on-wafer dies, normalised to radius 1
    y: np.ndarray
    base_d0: float


@dataclass
class Master:
    tables: dict[str, pd.DataFrame]
    n_steps: int
    step_tool_types: list[str]
    param_ids: dict[str, int]
    chamber_grid: dict[str, np.ndarray]  # tool type -> (tools, chambers) chamber ids
    chamber_tool_type: dict[int, str]
    chamber_label: dict[int, str]  # e.g. "ETCH-02/B"
    products: list[ProductGeometry]
    metrology: dict[int, MetrologyStep] = field(default_factory=dict)

    def route_step_id(self, product_idx: np.ndarray | int, seq: int) -> np.ndarray | int:
        """Route step ids are dense: product p (0-based), step s (1-based) -> p * S + s."""
        return product_idx * self.n_steps + seq


def _geometry(product_id: int, grid: int, base_d0: float) -> ProductGeometry:
    centres = (np.arange(grid) + 0.5) / grid * 2 - 1
    xx, yy = np.meshgrid(centres, centres)
    on_wafer = np.hypot(xx, yy) <= EDGE_EXCLUSION
    die_area = round((WAFER_DIAMETER_MM / 10 / grid) ** 2, 4)
    return ProductGeometry(
        product_id, grid, die_area, on_wafer, xx[on_wafer], yy[on_wafer], base_d0
    )


def _scaled(m: MetrologySpec, scale: float) -> tuple[float, float]:
    if m.scales_with_node:
        return m.target * scale, m.sigma * scale
    return m.target, m.sigma


def build_master(cfg: FabConfig) -> Master:
    nodes = pd.DataFrame(
        {
            "node_id": np.arange(1, len(cfg.nodes) + 1, dtype=np.int16),
            "name": [n.name for n in cfg.nodes],
            "feature_size_nm": np.array([n.feature_size_nm for n in cfg.nodes], dtype=np.int16),
        }
    )
    node_id = dict(zip(nodes["name"], nodes["node_id"], strict=True))

    geometries = [
        _geometry(i, p.map_grid, cfg.node(p.node).base_d0)
        for i, p in enumerate(cfg.products, start=1)
    ]
    products = pd.DataFrame(
        {
            "product_id": np.arange(1, len(cfg.products) + 1, dtype=np.int16),
            "code": [p.code for p in cfg.products],
            "node_id": np.array([node_id[p.node] for p in cfg.products], dtype=np.int16),
            "die_area_cm2": [g.die_area_cm2 for g in geometries],
            "map_rows": np.array([g.grid for g in geometries], dtype=np.int16),
            "map_cols": np.array([g.grid for g in geometries], dtype=np.int16),
            "gross_dies": np.array([int(g.on_wafer.sum()) for g in geometries], dtype=np.int32),
        }
    )
    routes = pd.DataFrame(
        {
            "route_id": products["product_id"].to_numpy(),
            "product_id": products["product_id"].to_numpy(),
            "version": np.ones(len(products), dtype=np.int16),
        }
    )
    tool_types = pd.DataFrame(
        {
            "tool_type": list(cfg.tool_types),
            "description": [t.description for t in cfg.tool_types.values()],
        }
    )

    n_steps = len(cfg.route)
    step_rows = [
        {
            "route_step_id": p_idx * n_steps + seq,
            "route_id": p_idx + 1,
            "sequence_no": seq,
            "step_name": step.name,
            "layer": step.layer,
            "tool_type": step.tool_type,
        }
        for p_idx in range(len(cfg.products))
        for seq, step in enumerate(cfg.route, start=1)
    ]
    route_steps = pd.DataFrame(step_rows).astype(
        {"route_step_id": np.int32, "route_id": np.int16, "sequence_no": np.int16}
    )

    tool_rows, chamber_rows = [], []
    chamber_grid: dict[str, np.ndarray] = {}
    chamber_tool_type: dict[int, str] = {}
    chamber_label: dict[int, str] = {}
    next_chamber = 1
    for tt_name, tt in cfg.tool_types.items():
        grid = np.zeros((tt.tools, tt.chambers_per_tool), dtype=np.int16)
        for t in range(tt.tools):
            tool_id = f"{tt_name.upper()}-{t + 1:02d}"
            tool_rows.append({"tool_id": tool_id, "tool_type": tt_name})
            for c in range(tt.chambers_per_tool):
                code = chr(ord("A") + c)
                chamber_rows.append(
                    {"chamber_id": next_chamber, "tool_id": tool_id, "chamber_code": code}
                )
                grid[t, c] = next_chamber
                chamber_tool_type[next_chamber] = tt_name
                chamber_label[next_chamber] = f"{tool_id}/{code}"
                next_chamber += 1
        chamber_grid[tt_name] = grid
    tools = pd.DataFrame(tool_rows)
    chambers = pd.DataFrame(chamber_rows).astype({"chamber_id": np.int16})

    param_rows: list[dict[str, object]] = []
    param_ids: dict[str, int] = {}
    for tt in cfg.tool_types.values():
        for name, s in tt.sensors.items():
            param_ids[name] = len(param_rows) + 1
            param_rows.append(
                {"parameter_id": param_ids[name], "name": name, "unit": s.unit, "kind": "sensor"}
            )
    for step in cfg.route:
        for m in step.metrology:
            if m.parameter not in param_ids:
                param_ids[m.parameter] = len(param_rows) + 1
                param_rows.append(
                    {"parameter_id": param_ids[m.parameter], "name": m.parameter,
                     "unit": m.unit, "kind": "metrology"}
                )  # fmt: skip
    parameters = pd.DataFrame(param_rows).astype({"parameter_id": np.int16})

    plan_rows: list[dict[str, object]] = []
    metrology: dict[int, MetrologyStep] = {}
    spec = cfg.measurement.spec_sigma
    for p_idx, product in enumerate(cfg.products):
        scale = cfg.node(product.node).feature_size_nm / 28
        for seq, step in enumerate(cfg.route, start=1):
            if not step.metrology:
                continue
            rs_id = p_idx * n_steps + seq
            params = []
            for m in step.metrology:
                target, sigma = _scaled(m, scale)
                params.append(MeasuredParam(param_ids[m.parameter], target, sigma, m.radial))
                plan_rows.append(
                    {
                        "route_step_id": rs_id,
                        "parameter_id": param_ids[m.parameter],
                        "wafers_per_lot": cfg.measurement.metrology_wafers_per_lot,
                        "sites_per_wafer": len(SITES_MM),
                        "target": target,
                        "lsl": target - spec * sigma,
                        "usl": target + spec * sigma,
                    }
                )
            corr = np.eye(len(step.metrology))
            names = [m.parameter for m in step.metrology]
            for a, b, rho in step.correlations:
                i, j = names.index(a), names.index(b)
                corr[i, j] = corr[j, i] = rho
            metrology[rs_id] = MetrologyStep(rs_id, params, np.linalg.cholesky(corr))
    metrology_plans = pd.DataFrame(plan_rows).astype(
        {"route_step_id": np.int32, "parameter_id": np.int16, "wafers_per_lot": np.int16,
         "sites_per_wafer": np.int16}
    )  # fmt: skip

    sort_bins = pd.DataFrame(
        {
            "bin_code": np.array([b.code for b in cfg.sort_bins], dtype=np.int16),
            "name": [b.name for b in cfg.sort_bins],
            "is_pass": [b.is_pass for b in cfg.sort_bins],
        }
    )

    return Master(
        tables={
            "technology_nodes": nodes,
            "products": products,
            "routes": routes,
            "tool_types": tool_types,
            "route_steps": route_steps,
            "tools": tools,
            "chambers": chambers,
            "parameters": parameters,
            "metrology_plans": metrology_plans,
            "sort_bins": sort_bins,
        },
        n_steps=n_steps,
        step_tool_types=[s.tool_type for s in cfg.route],
        param_ids=param_ids,
        chamber_grid=chamber_grid,
        chamber_tool_type=chamber_tool_type,
        chamber_label=chamber_label,
        products=geometries,
        metrology=metrology,
    )


# Standard 9-site metrology pattern on a 300 mm wafer: centre, 4 at mid-radius, 4 near the edge.
SITES_MM: np.ndarray = np.array(
    [(0.0, 0.0)]
    + [(75 * np.cos(a), 75 * np.sin(a)) for a in np.deg2rad([0, 90, 180, 270])]
    + [(140 * np.cos(a), 140 * np.sin(a)) for a in np.deg2rad([45, 135, 225, 315])]
)
