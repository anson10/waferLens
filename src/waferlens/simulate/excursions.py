"""Excursion plan and recipe versions.

The plan is drawn before any wafer is processed: which chamber drifts, when, by how much,
which recipe update goes wrong. Every planned excursion becomes a row in
``excursions_ground_truth``; detection in phase 3 is scored against exactly these rows.

Times are minutes since the simulation start.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from waferlens.simulate.config import FabConfig, ProfileSpec
from waferlens.simulate.master import Master

MINUTES_PER_DAY = 24 * 60
CHAMBER_TYPES = ("step_shift", "drift", "chamber_offset")


@dataclass(frozen=True)
class Excursion:
    excursion_id: int
    excursion_type: str
    start: float
    end: float
    magnitude: float  # in sigma; signed for sensor and recipe shifts
    description: str
    chamber_id: int | None = None
    parameter_id: int | None = None  # sensor (chamber types) or metrology parameter (recipe)
    recipe_id: int | None = None
    route_step_id: int | None = None
    spatial_pattern: str | None = None
    geometry_seed: int = 0

    def effect(self, t: np.ndarray) -> np.ndarray:
        """Shift in sigma at times ``t``; zero outside the excursion window."""
        inside = (t >= self.start) & (t < self.end)
        if self.excursion_type == "drift":
            ramp = (t - self.start) / (self.end - self.start)
            return np.where(inside, self.magnitude * ramp, 0.0)
        return np.where(inside, self.magnitude, 0.0)


@dataclass
class Plan:
    excursions: list[Excursion]
    recipes: pd.DataFrame  # recipe_id, route_step_id, name, version, effective_from (minutes)
    _versions: dict[int, list[tuple[float, int]]]  # route_step_id -> [(from, recipe_id)] v2+

    def recipe_for(self, route_step_ids: np.ndarray, times: np.ndarray) -> np.ndarray:
        """Recipe in force for each (route step, time). v1 has recipe_id == route_step_id."""
        recipe = route_step_ids.astype(np.int32).copy()
        for rs_id, versions in self._versions.items():
            on_step = route_step_ids == rs_id
            for effective_from, recipe_id in versions:  # ascending, later versions win
                recipe[on_step & (times >= effective_from)] = recipe_id
        return recipe

    def of_type(self, *types: str) -> list[Excursion]:
        return [e for e in self.excursions if e.excursion_type in types]


def plan_excursions(
    cfg: FabConfig, master: Master, profile: ProfileSpec, rng: np.random.Generator
) -> Plan:
    period = profile.days * MINUTES_PER_DAY
    spec = cfg.excursions
    steps = master.tables["route_steps"]
    product_codes = master.tables["products"]["code"].tolist()

    recipes = pd.DataFrame(
        {
            "recipe_id": steps["route_step_id"].to_numpy(np.int32),
            "route_step_id": steps["route_step_id"].to_numpy(np.int32),
            "name": [f"{s.upper()}_{product_codes[r - 1]}"
                     for s, r in zip(steps["step_name"], steps["route_id"], strict=True)],
            "version": np.ones(len(steps), dtype=np.int16),
            "effective_from": np.zeros(len(steps)),
        }
    )  # fmt: skip
    extra_recipes: list[dict[str, object]] = []
    versions: dict[int, list[tuple[float, int]]] = {}
    recipe_name = dict(zip(recipes["route_step_id"], recipes["name"], strict=True))

    def new_version(rs_id: int, effective_from: float) -> int:
        recipe_id = len(recipes) + len(extra_recipes) + 1
        versions.setdefault(rs_id, []).append((effective_from, recipe_id))
        extra_recipes.append(
            {"recipe_id": recipe_id, "route_step_id": rs_id, "name": recipe_name[rs_id],
             "version": len(versions[rs_id]) + 1, "effective_from": effective_from}
        )  # fmt: skip
        return recipe_id

    types = list(spec.type_weights)
    weights = np.array([spec.type_weights[t] for t in types])
    drawn = rng.choice(types, size=profile.excursions, p=weights / weights.sum())

    busy: dict[int, list[tuple[float, float]]] = {}  # chamber -> windows already used
    changed_steps: set[int] = set()
    measured_steps = sorted(master.metrology)
    planned: list[dict[str, object]] = []

    for ex_type in drawn:
        lo_d, hi_d = spec.duration_days[ex_type]
        duration = rng.uniform(lo_d, hi_d) * MINUTES_PER_DAY
        lo_m, hi_m = spec.magnitude_sigma[ex_type]
        magnitude = float(rng.uniform(lo_m, hi_m))

        if ex_type == "recipe_change":
            free = [s for s in measured_steps if s not in changed_steps]
            if not free:
                continue
            rs_id = int(rng.choice(free))
            changed_steps.add(rs_id)
            start = rng.uniform(0.05, 0.85) * period
            end = min(start + duration, period)
            bad = new_version(rs_id, start)
            new_version(rs_id, end)  # the fix: revert to known-good settings
            param = master.metrology[rs_id].params[0].parameter_id
            magnitude *= rng.choice([-1.0, 1.0])
            planned.append(
                {"excursion_type": ex_type, "start": start, "end": end,
                 "magnitude": magnitude, "recipe_id": bad, "route_step_id": rs_id,
                 "parameter_id": param,
                 "description": f"{recipe_name[rs_id]} v{len(versions[rs_id])} shifts "
                                f"{_param_name(master, param)} by {magnitude:+.1f} sigma"}
            )  # fmt: skip
            continue

        candidates = {
            t: w for t, w in spec.tool_type_weights.items()
            if ex_type != "spatial_pattern" or cfg.tool_types[t].spatial_patterns
        }  # fmt: skip
        names = list(candidates)
        p = np.array([candidates[t] for t in names])
        for _attempt in range(100):
            tool_type = str(rng.choice(names, p=p / p.sum()))
            chamber = int(rng.choice(master.chamber_grid[tool_type].ravel()))
            start = rng.uniform(0.05, 0.85) * period
            end = min(start + duration, period)
            if all(end <= s or start >= e for s, e in busy.get(chamber, [])):
                break
        else:
            continue
        busy.setdefault(chamber, []).append((start, end))
        label = master.chamber_label[chamber]
        tt = cfg.tool_types[tool_type]

        if ex_type == "spatial_pattern":
            pattern = str(rng.choice(tt.spatial_patterns))
            planned.append(
                {"excursion_type": ex_type, "start": start, "end": end, "magnitude": magnitude,
                 "chamber_id": chamber, "spatial_pattern": pattern,
                 "geometry_seed": int(rng.integers(2**31)),
                 "description": f"{label} causes {pattern} defects"}
            )  # fmt: skip
            continue

        sensor = tt.primary_sensor
        magnitude *= rng.choice([-1.0, 1.0])
        what = {
            "step_shift": f"step shift of {magnitude:+.1f} sigma",
            "drift": f"drifts to {magnitude:+.1f} sigma over "
            f"{(end - start) / MINUTES_PER_DAY:.0f} days",
            "chamber_offset": f"offset of {magnitude:+.1f} sigma (chamber mismatch)",
        }[ex_type]
        planned.append(
            {"excursion_type": ex_type, "start": start, "end": end, "magnitude": magnitude,
             "chamber_id": chamber, "parameter_id": master.param_ids[sensor],
             "description": f"{label} {sensor} {what}"}
        )  # fmt: skip

    benign = [s for s in master.tables["route_steps"]["route_step_id"] if s not in changed_steps]
    n_benign = min(profile.benign_recipe_changes, len(benign))
    for rs_id in rng.choice(benign, size=n_benign, replace=False):
        new_version(int(rs_id), rng.uniform(0.05, 0.95) * period)

    planned.sort(key=lambda e: float(e["start"]))  # type: ignore[arg-type]
    excursions = [Excursion(excursion_id=i, **e) for i, e in enumerate(planned, start=1)]  # type: ignore[arg-type]
    for v in versions.values():
        v.sort()
    if extra_recipes:
        recipes = pd.concat([recipes, pd.DataFrame(extra_recipes)], ignore_index=True)
    recipes = recipes.astype({"recipe_id": np.int32, "route_step_id": np.int32,
                              "version": np.int16})  # fmt: skip
    return Plan(excursions, recipes, versions)


def _param_name(master: Master, parameter_id: int) -> str:
    return next(n for n, i in master.param_ids.items() if i == parameter_id)
