"""Lot scheduling: moves every lot through the route and records wafer genealogy.

Model, per step:

* A lot waits in queue (exponential), optionally sits on hold, then tracks in to one tool of
  the step's tool type. Its wafers are spread over that tool's chambers by slot, and each
  chamber processes its share one wafer after another.
* Litho steps are sometimes reworked: the whole lot runs the step a second time
  (``pass_no = 2``), possibly on another scanner.
* A few lots are split after a random step: slots in the upper half become a child lot that
  continues on its own.
* Wafers are occasionally scrapped and stop moving.

Tool capacity and queueing between lots are not modelled; lots never block each other.
The loop is over steps (30), and every operation inside it is vectorised over wafers.
Anything that happens after the end of the simulated period is cut off, which leaves
realistic work in progress.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from waferlens.simulate.config import FabConfig, ProfileSpec
from waferlens.simulate.excursions import MINUTES_PER_DAY, Plan
from waferlens.simulate.master import Master

PRIORITIES = np.array([1, 2, 3, 4, 5])
PRIORITY_WEIGHTS = np.array([0.05, 0.15, 0.60, 0.15, 0.05])


@dataclass
class Schedule:
    lots: pd.DataFrame
    wafers: pd.DataFrame
    lot_events: pd.DataFrame
    # Genealogy, times in minutes. Extra columns beyond the table: wafer_idx (0-based),
    # seq, tool_type.
    history: pd.DataFrame
    # Wafers that reached wafer sort inside the period: wafer_idx, product_idx, tested_at.
    sorted_wafers: pd.DataFrame
    n_wafers: int


def build_schedule(
    cfg: FabConfig, master: Master, plan: Plan, profile: ProfileSpec, rng: np.random.Generator
) -> Schedule:
    lg = cfg.logistics
    n_slots = lg.wafers_per_lot
    n_steps = master.n_steps
    period = float(profile.days * MINUTES_PER_DAY)
    n_lots = profile.lots

    mix = np.array([p.mix for p in cfg.products])
    lot_product = rng.choice(len(cfg.products), size=n_lots, p=mix / mix.sum())
    lot_start = np.sort(rng.uniform(0, period, n_lots))
    lot_priority = rng.choice(PRIORITIES, size=n_lots, p=PRIORITY_WEIGHTS)

    n_wafers = n_lots * n_slots
    slot = np.tile(np.arange(1, n_slots + 1), n_lots)
    orig_lot = np.repeat(np.arange(n_lots), n_slots)
    wafer_product = lot_product[orig_lot]
    unit = orig_lot.copy()  # current lot "unit"; splits append new units
    alive = np.ones(n_wafers, dtype=bool)
    scrapped_at = np.full(n_wafers, np.inf)

    unit_product = list(lot_product)
    unit_parent = [-1] * n_lots
    unit_priority = list(lot_priority)
    unit_split_time = [np.nan] * n_lots
    arrival = lot_start.copy()
    unit_end = lot_start.copy()

    hold_lot = rng.random(n_lots) < lg.hold_prob_per_lot
    hold_step = rng.integers(1, n_steps + 1, n_lots)
    hold_minutes = rng.uniform(*lg.hold_hours, n_lots) * 60
    split_lot = rng.random(n_lots) < lg.split_prob_per_lot
    split_step = rng.integers(2, n_steps, n_lots)  # split after this step

    events: list[tuple[int, str, float, int]] = [
        (u, "start", float(lot_start[u]), -1) for u in range(n_lots)
    ]
    holds: list[tuple[int, float, float]] = []
    rows: dict[str, list[np.ndarray]] = {k: [] for k in
        ("wafer_idx", "seq", "pass_no", "unit", "chamber_id", "track_in", "track_out")}  # fmt: skip

    for seq in range(1, n_steps + 1):
        tool_type = master.step_tool_types[seq - 1]
        grid = master.chamber_grid[tool_type]
        n_tools, n_chambers = grid.shape
        minutes = cfg.tool_types[tool_type].process_minutes
        n_units = len(arrival)

        held = np.flatnonzero(hold_lot & (hold_step == seq))
        for u in held.tolist():
            begin, end = float(arrival[u]), float(arrival[u] + hold_minutes[u])
            holds.append((u, begin, end))
            events += [(u, "hold", begin, -1), (u, "release", end, -1)]
        arrival[held] += hold_minutes[held]

        reworked = (tool_type == "litho") & (rng.random(n_units) < lg.rework_prob_per_litho_step)
        here = np.flatnonzero(alive)
        unit_end = arrival.copy()
        for pass_no in (1, 2):
            w = here if pass_no == 1 else here[reworked[unit[here]]]
            if len(w) == 0:
                continue
            u = unit[w]
            tool = rng.integers(n_tools, size=n_units)[u]
            offset = rng.integers(n_chambers, size=n_units)[u]
            position = slot[w] - 1 + offset
            chamber = grid[tool, position % n_chambers]
            order = position // n_chambers - offset // n_chambers
            base = arrival[u] if pass_no == 1 else unit_end[u] + lg.rework_delay_minutes
            track_in = base + order * minutes + rng.uniform(0, 0.2 * minutes, len(w))
            track_out = track_in + minutes * rng.uniform(0.9, 1.1, len(w))
            for key, value in (("wafer_idx", w), ("seq", np.full(len(w), seq)),
                               ("pass_no", np.full(len(w), pass_no)), ("unit", u),
                               ("chamber_id", chamber), ("track_in", track_in),
                               ("track_out", track_out)):  # fmt: skip
                rows[key].append(value)
            np.maximum.at(unit_end, u, track_out)

        scrap = here[rng.random(len(here)) < lg.scrap_prob_per_wafer_step]
        alive[scrap] = False
        scrapped_at[scrap] = unit_end[unit[scrap]]

        if seq < n_steps:
            for u in np.flatnonzero(split_lot & (split_step == seq)).tolist():
                moving = (unit == u) & (slot > n_slots // 2)
                if not moving.any() or moving.sum() == (unit == u).sum():
                    continue
                child = len(arrival)
                unit[moving] = child
                unit_product.append(unit_product[u])
                unit_parent.append(u)
                unit_priority.append(unit_priority[u])
                unit_split_time.append(float(unit_end[u]))
                events.append((u, "split", float(unit_end[u]), child))
                arrival = np.append(arrival, 0.0)
                unit_end = np.append(unit_end, unit_end[u])

        arrival = unit_end + rng.exponential(lg.queue_hours_mean * 60, len(unit_end))

    hist = pd.DataFrame({k: np.concatenate(v) for k, v in rows.items()})
    hist = hist[hist["track_out"] <= period]

    # Undo splits that happen after the period ends: those child lots don't exist yet.
    n_units = len(unit_parent)
    exists = np.ones(n_units, dtype=bool)
    for child in range(n_lots, n_units):
        if unit_split_time[child] > period:
            exists[child] = False
            unit[unit == child] = unit_parent[child]
    events = [e for e in events if e[2] <= period and exists[e[0]]]

    final_end = unit_end
    sort_time = final_end[unit] + rng.uniform(*lg.sort_delay_hours, n_wafers) * 60
    finished_route = np.zeros(n_wafers, dtype=bool)
    last = hist[(hist["seq"] == n_steps)]
    finished_route[last["wafer_idx"].to_numpy()] = True
    scrapped = scrapped_at <= period
    is_sorted = finished_route & ~scrapped & (sort_time <= period)

    wafer_status = np.where(scrapped, "scrapped", np.where(is_sorted, "complete", "active"))
    unit_status = []
    on_hold_at_end = {u for u, s, e in holds if s <= period < e}
    for u in range(n_units):
        members = unit == u
        if not exists[u]:
            unit_status.append(None)
        elif scrapped[members].all():
            unit_status.append("scrapped")
        elif (is_sorted | scrapped)[members].all():
            unit_status.append("complete")
            events.append((u, "complete", float(sort_time[members & is_sorted].max()), -1))
        elif u in on_hold_at_end:
            unit_status.append("hold")
        else:
            unit_status.append("active")

    yy = cfg.start_date.year % 100
    unit_root = [u if unit_parent[u] < 0 else unit_parent[u] for u in range(n_units)]
    keep = np.flatnonzero(exists)
    product_ids = master.tables["products"]["product_id"].to_numpy()
    lots = pd.DataFrame(
        {
            "lot_id": (keep + 1).astype(np.int32),
            "lot_code": [f"L{yy:02d}{unit_root[u] + 1:05d}.{1 if unit_parent[u] < 0 else 2}"
                         for u in keep],
            "parent_lot_id": pd.array([unit_parent[u] + 1 if unit_parent[u] >= 0 else None
                                       for u in keep], dtype="Int32"),
            "product_id": product_ids[np.array(unit_product)[keep]].astype(np.int16),
            "route_id": product_ids[np.array(unit_product)[keep]].astype(np.int16),
            "priority": np.array(unit_priority)[keep].astype(np.int16),
            "start_time": np.array([lot_start[u] if unit_parent[u] < 0 else unit_split_time[u]
                                    for u in keep]),
            "status": [unit_status[u] for u in keep],
        }
    )  # fmt: skip
    wafers = pd.DataFrame(
        {
            "wafer_id": np.arange(1, n_wafers + 1, dtype=np.int32),
            "wafer_code": [f"L{yy:02d}{o + 1:05d}-{s:02d}" for o, s in zip(orig_lot, slot,
                                                                          strict=True)],
            "lot_id": (unit + 1).astype(np.int32),
            "slot": slot.astype(np.int16),
            "status": wafer_status,
        }
    )  # fmt: skip
    events.sort(key=lambda e: (e[2], e[0]))
    lot_events = pd.DataFrame(
        {
            "event_id": np.arange(1, len(events) + 1, dtype=np.int32),
            "lot_id": np.array([e[0] + 1 for e in events], dtype=np.int32),
            "event_type": [e[1] for e in events],
            "event_time": np.array([e[2] for e in events]),
            "related_lot_id": pd.array([e[3] + 1 if e[3] >= 0 else None for e in events],
                                       dtype="Int32"),
            "note": pd.array([None] * len(events), dtype="string"),
        }
    )  # fmt: skip

    wafer_idx = hist["wafer_idx"].to_numpy()
    seq_arr = hist["seq"].to_numpy()
    route_step_id = (wafer_product[wafer_idx] * n_steps + seq_arr).astype(np.int32)
    track_in = hist["track_in"].to_numpy()
    history = pd.DataFrame(
        {
            "wafer_id": (wafer_idx + 1).astype(np.int32),
            "route_step_id": route_step_id,
            "pass_no": hist["pass_no"].to_numpy(np.int16),
            "lot_id": (hist["unit"].to_numpy() + 1).astype(np.int32),
            "chamber_id": hist["chamber_id"].to_numpy(np.int16),
            "recipe_id": plan.recipe_for(route_step_id, track_in),
            "track_in": track_in,
            "track_out": hist["track_out"].to_numpy(),
            "wafer_idx": wafer_idx,
            "seq": seq_arr.astype(np.int16),
            "tool_type": np.array(master.step_tool_types)[seq_arr - 1],
        }
    ).reset_index(drop=True)

    sorted_idx = np.flatnonzero(is_sorted)
    sorted_wafers = pd.DataFrame(
        {"wafer_idx": sorted_idx, "product_idx": wafer_product[sorted_idx],
         "tested_at": sort_time[sorted_idx]}
    )  # fmt: skip
    return Schedule(lots, wafers, lot_events, history, sorted_wafers, n_wafers)
