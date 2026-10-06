"""Tool sensor readings and inline metrology.

All values are generated as z-scores first and converted to engineering units last:

* Sensor z = static chamber bias + noise + chamber excursion effect (primary sensor only).
* Metrology z (true, per wafer) = correlated noise, with the first parameter mixed as
  sqrt(1 - c²) * noise + c * primary sensor z of the chamber that processed the wafer, so an
  in-control step keeps unit variance; plus any recipe-change shift.

True metrology exists for every wafer at every measured step and drives yield. Only the
sampled wafers (e.g. 5 of 25 per lot) are actually measured, at 9 sites, with a radial
profile and site noise on top. That is the gap a real fab lives with.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from waferlens.simulate.config import FabConfig
from waferlens.simulate.excursions import CHAMBER_TYPES, Plan
from waferlens.simulate.master import SITES_MM, Master

SITE_RADIUS_SQ = (np.hypot(SITES_MM[:, 0], SITES_MM[:, 1]) / 150.0) ** 2


@dataclass
class Measurements:
    sensor_readings: pd.DataFrame  # time in minutes
    metrology: pd.DataFrame  # time in minutes
    metrology_penalty: np.ndarray  # per wafer_idx: sum of true |z| beyond 2 sigma


def generate_measurements(
    cfg: FabConfig,
    master: Master,
    plan: Plan,
    history: pd.DataFrame,
    n_wafers: int,
    period: float,
    rng: np.random.Generator,
) -> Measurements:
    n_chambers = max(master.chamber_tool_type) + 1
    n_params = max(master.param_ids.values()) + 1
    chamber_bias = rng.normal(0, cfg.measurement.chamber_bias_sigma, (n_chambers, n_params))
    chamber_excursions = plan.of_type(*CHAMBER_TYPES)

    chamber = history["chamber_id"].to_numpy()
    track_in = history["track_in"].to_numpy()
    primary_z = np.zeros(len(history))
    frames: list[pd.DataFrame] = []
    tool_type_col = history["tool_type"].to_numpy()

    for tt_name, tt in cfg.tool_types.items():
        r = np.flatnonzero(tool_type_col == tt_name)
        if len(r) == 0:
            continue
        ch, t = chamber[r], track_in[r]
        for j, (sensor, spec) in enumerate(tt.sensors.items()):
            pid = master.param_ids[sensor]
            z = chamber_bias[ch, pid] + rng.standard_normal(len(r))
            for ex in chamber_excursions:
                if ex.parameter_id == pid:
                    hit = ch == ex.chamber_id
                    z[hit] += ex.effect(t[hit])
            if j == 0:
                primary_z[r] = z
            frames.append(
                pd.DataFrame(
                    {
                        "time": t,
                        "wafer_id": history["wafer_id"].to_numpy()[r],
                        "route_step_id": history["route_step_id"].to_numpy()[r],
                        "parameter_id": np.full(len(r), pid, dtype=np.int16),
                        "chamber_id": ch,
                        "value": spec.nominal + spec.sigma * z,
                    }
                )
            )
    sensor_readings = pd.concat(frames, ignore_index=True)

    # Metrology measures the result of the last pass of a step.
    final = ~history.duplicated(["wafer_id", "route_step_id"], keep="last").to_numpy()
    penalty = np.zeros(n_wafers)
    coupling = cfg.measurement.sensor_to_metrology_coupling
    per_lot = cfg.measurement.metrology_wafers_per_lot
    noise = cfg.measurement.site_noise_ratio
    lo_delay, hi_delay = cfg.logistics.metrology_delay_minutes
    route_step = history["route_step_id"].to_numpy()
    recipe = history["recipe_id"].to_numpy()
    lot = history["lot_id"].to_numpy()
    wafer_idx = history["wafer_idx"].to_numpy()
    track_out = history["track_out"].to_numpy()
    recipe_shifts = plan.of_type("recipe_change")
    n_sites = len(SITES_MM)
    metro_frames: list[pd.DataFrame] = []

    for rs_id, step in master.metrology.items():
        r = np.flatnonzero(final & (route_step == rs_id))
        if len(r) == 0:
            continue
        n, n_p = len(r), len(step.params)
        z = rng.standard_normal((n, n_p)) @ step.cholesky.T
        z[:, 0] = np.sqrt(1 - coupling**2) * z[:, 0] + coupling * primary_z[r]
        for ex in recipe_shifts:
            if ex.route_step_id == rs_id:
                z[recipe[r] == ex.recipe_id, 0] += ex.magnitude
        np.add.at(penalty, wafer_idx[r], np.maximum(0.0, np.abs(z) - 2.0).sum(axis=1))

        key = pd.Series(rng.random(n))
        sampled = (key.groupby(lot[r]).rank(method="first") <= per_lot).to_numpy()
        when = track_out[r] + rng.uniform(lo_delay, hi_delay, n)
        sampled = sampled & (when <= period)
        s = np.flatnonzero(sampled)
        if len(s) == 0:
            continue

        for p_idx, param in enumerate(step.params):
            # rows: sampled wafer x site
            wafer_z = np.repeat(z[s, p_idx], n_sites)
            site_z = (
                wafer_z
                + param.radial * np.tile(SITE_RADIUS_SQ, len(s))
                + noise * rng.standard_normal(len(s) * n_sites)
            )
            metro_frames.append(
                pd.DataFrame(
                    {
                        "time": np.repeat(when[s], n_sites),
                        "wafer_id": np.repeat(wafer_idx[r][s] + 1, n_sites).astype(np.int32),
                        "route_step_id": np.full(len(s) * n_sites, rs_id, dtype=np.int32),
                        "parameter_id": np.full(len(s) * n_sites, param.parameter_id,
                                                dtype=np.int16),
                        "site_no": np.tile(np.arange(1, n_sites + 1, dtype=np.int16), len(s)),
                        "site_x_mm": np.tile(SITES_MM[:, 0], len(s)),
                        "site_y_mm": np.tile(SITES_MM[:, 1], len(s)),
                        "value": param.target + param.sigma * site_z,
                    }
                )
            )  # fmt: skip

    metrology = pd.concat(metro_frames, ignore_index=True)
    return Measurements(sensor_readings, metrology, penalty)
