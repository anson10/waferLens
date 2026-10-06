"""Runs the simulator end to end and writes one Parquet file per database table.

Each stage gets its own random stream spawned from the seed, so changing one stage (say,
the wafer map model) doesn't reshuffle the others.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from waferlens.simulate.config import FabConfig, ProfileSpec
from waferlens.simulate.excursions import MINUTES_PER_DAY, plan_excursions
from waferlens.simulate.master import build_master
from waferlens.simulate.measurements import generate_measurements
from waferlens.simulate.schedule import build_schedule
from waferlens.simulate.wafer_maps import generate_wafer_maps

RUN_ID = 1
# Columns holding minutes since the start of the simulation, per table.
TIME_COLUMNS = {
    "recipes": ["effective_from"],
    "lots": ["start_time"],
    "lot_events": ["event_time"],
    "wafer_step_history": ["track_in", "track_out"],
    "tool_sensor_readings": ["time"],
    "metrology_measurements": ["time"],
    "excursions_ground_truth": ["start_time", "end_time"],
}


@dataclass
class SimulationResult:
    tables: dict[str, pd.DataFrame | pa.Table]
    summary: dict[str, object] = field(default_factory=dict)


def simulate(
    cfg: FabConfig, profile: str | ProfileSpec, seed: int, profile_name: str | None = None
) -> SimulationResult:
    started = time.perf_counter()
    if isinstance(profile, str):
        profile_name, profile = profile, cfg.profiles[profile]
    name = profile_name or "custom"
    period = float(profile.days * MINUTES_PER_DAY)
    plan_rng, schedule_rng, measure_rng, maps_rng = (
        np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(4)
    )

    master = build_master(cfg)
    plan = plan_excursions(cfg, master, profile, plan_rng)
    schedule = build_schedule(cfg, master, plan, profile, schedule_rng)
    measured = generate_measurements(
        cfg, master, plan, schedule.history, schedule.n_wafers, period, measure_rng
    )
    maps = generate_wafer_maps(
        cfg, master, plan, schedule.history, schedule.sorted_wafers,
        measured.metrology_penalty, schedule.n_wafers, maps_rng,
    )  # fmt: skip

    ground_truth = pd.DataFrame(
        {
            "excursion_id": np.array([e.excursion_id for e in plan.excursions], dtype=np.int32),
            "run_id": np.full(len(plan.excursions), RUN_ID, dtype=np.int32),
            "excursion_type": [e.excursion_type for e in plan.excursions],
            "chamber_id": pd.array([e.chamber_id for e in plan.excursions], dtype="Int16"),
            "recipe_id": pd.array([e.recipe_id for e in plan.excursions], dtype="Int32"),
            "parameter_id": pd.array([e.parameter_id for e in plan.excursions], dtype="Int16"),
            "spatial_pattern": pd.array([e.spatial_pattern for e in plan.excursions],
                                        dtype="string"),
            "start_time": np.array([e.start for e in plan.excursions], dtype=float),
            "end_time": np.array([e.end for e in plan.excursions], dtype=float),
            "magnitude_sigma": np.array([e.magnitude for e in plan.excursions], dtype=float),
            "description": [e.description for e in plan.excursions],
        }
    )  # fmt: skip
    simulation_runs = pd.DataFrame(
        {
            "run_id": [RUN_ID],
            "profile": [name],
            "seed": [seed],
            "config": [json.dumps({"profile": profile.model_dump(),
                                   "fab": cfg.model_dump(mode="json")})],
            "created_at": [pd.Timestamp(datetime.now(UTC))],
        }
    )  # fmt: skip
    history_columns = ["wafer_id", "route_step_id", "pass_no", "lot_id", "chamber_id",
                       "recipe_id", "track_in", "track_out"]  # fmt: skip

    tables: dict[str, pd.DataFrame | pa.Table] = {
        **master.tables,
        "recipes": plan.recipes,
        "simulation_runs": simulation_runs,
        "lots": schedule.lots,
        "wafers": schedule.wafers,
        "lot_events": schedule.lot_events,
        "wafer_step_history": schedule.history[history_columns],
        "tool_sensor_readings": measured.sensor_readings,
        "metrology_measurements": measured.metrology,
        "wafer_maps": maps.table,
        "excursions_ground_truth": ground_truth,
    }
    start = pd.Timestamp(cfg.start_date, tz="UTC")
    for table, columns in TIME_COLUMNS.items():
        df = tables[table]
        assert isinstance(df, pd.DataFrame)
        tables[table] = df.assign(**{c: _timestamps(start, df[c]) for c in columns})
    tables["wafer_maps"] = _maps_timestamps(start, maps.table)

    tested = maps.tested_dies[maps.tested_dies > 0]
    good = maps.good_dies[maps.tested_dies > 0]
    yields = 100 * good / tested if len(tested) else np.array([np.nan])
    summary: dict[str, object] = {
        "profile": name,
        "seed": seed,
        "rows": {t: (len(df) if isinstance(df, pd.DataFrame) else df.num_rows)
                 for t, df in tables.items()},
        "wafers_sorted": len(tested),
        "yield_pct": {"mean": round(float(np.mean(yields)), 2),
                      "p10": round(float(np.percentile(yields, 10)), 2),
                      "median": round(float(np.median(yields)), 2)},
        "excursions": dict(pd.Series([e.excursion_type for e in plan.excursions],
                                     dtype="string").value_counts().sort_index()),
        "seconds": round(time.perf_counter() - started, 1),
    }  # fmt: skip
    summary["total_rows"] = sum(summary["rows"].values())  # type: ignore[union-attr]
    return SimulationResult(tables, summary)


def _timestamps(start: pd.Timestamp, minutes: pd.Series) -> pd.Series:
    # Postgres stores microseconds; truncating here keeps keys identical after a round trip.
    return (start + pd.to_timedelta(minutes, unit="min")).dt.floor("us")


def _maps_timestamps(start: pd.Timestamp, table: pa.Table) -> pa.Table:
    minutes = pd.Series(table.column("tested_at").to_numpy())
    stamps = pa.array(_timestamps(start, minutes), type=pa.timestamp("us", tz="UTC"))
    return table.set_column(table.schema.get_field_index("tested_at"), "tested_at", stamps)


def write_parquet(result: SimulationResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in result.tables.items():
        arrow = (
            table
            if isinstance(table, pa.Table)
            else pa.Table.from_pandas(table, preserve_index=False)
        )
        pq.write_table(arrow, out_dir / f"{name}.parquet", compression="zstd")
    (out_dir / "manifest.json").write_text(json.dumps(result.summary, indent=2, default=str) + "\n")
