"""Run commonality for every injected excursion and store the ranked suspects.

Each analysis gets only the excursion's time window, never its chamber or recipe; where
the true cause lands in the ranking is the score (``marts.fct_root_cause_eval``).

Two signals mark a wafer as bad. Yield (phase 3) for every excursion. And, for spatial
excursions once FabEye has scored the wafers, the excursion's wafer-map pattern
(phase 5a): a pattern-led investigation, starting from the pattern an engineer sees on the
wafers, as a pattern alarm would hand it over.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from psycopg import Connection as PgConnection
from sqlalchemy import Engine, text

from waferlens.db.models import Base
from waferlens.db.session import get_engine
from waferlens.ingest.loader import copy_frame
from waferlens.patterns.fabeye import FROM_SIMULATOR
from waferlens.rootcause.commonality import commonality

CANDIDATES = Base.metadata.tables["rootcause_candidates"]


@dataclass
class RootcauseReport:
    windows: int = 0
    candidates: int = 0
    seconds: float = 0.0


def evaluate_excursions(
    engine: Engine | None = None, *, low_quantile: float = 0.2, min_support: int = 5
) -> RootcauseReport:
    started = time.perf_counter()
    engine = engine or get_engine()
    with engine.connect() as conn:
        windows = conn.execute(
            text("SELECT excursion_id, start_time, end_time, spatial_pattern "
                 "FROM excursions_ground_truth ORDER BY excursion_id")
        ).all()  # fmt: skip
        has_patterns = bool(conn.execute(text(
            "SELECT to_regclass('marts.fct_wafer_pattern') IS NOT NULL"
        )).scalar_one())  # fmt: skip
        if has_patterns:
            has_patterns = bool(conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM marts.fct_wafer_pattern)"
            )).scalar_one())  # fmt: skip

    frames = []
    for excursion_id, window_start, window_end, spatial_pattern in windows:
        ranked = commonality(engine, window_start, window_end, low_quantile=low_quantile,
                             min_support=min_support)  # fmt: skip
        frames.append(_frame(excursion_id, window_start, window_end, ranked, "yield", None))
        if has_patterns and spatial_pattern is not None:
            pattern = FROM_SIMULATOR[spatial_pattern]
            ranked = commonality(engine, window_start, window_end, min_support=min_support,
                                 pattern=pattern)  # fmt: skip
            frames.append(
                _frame(excursion_id, window_start, window_end, ranked, "pattern", pattern)
            )
    frames = [f for f in frames if not f.empty]

    candidates = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=[c.name for c in CANDIDATES.columns if c.name != "candidate_id"]
    )  # fmt: skip
    candidates.insert(0, "candidate_id", np.arange(1, len(candidates) + 1, dtype=np.int64))
    for col in ("window_start", "window_end"):
        candidates[col] = pd.to_datetime(candidates[col], utc=True)

    with engine.begin() as conn:
        pg = conn.connection.driver_connection
        assert isinstance(pg, PgConnection)
        conn.execute(text("TRUNCATE rootcause_candidates"))
        copy_frame(pg, CANDIDATES, candidates)
        conn.execute(
            text("SELECT setval(pg_get_serial_sequence('rootcause_candidates', 'candidate_id'),"
                 " COALESCE((SELECT max(candidate_id) FROM rootcause_candidates), 0) + 1, false)")
        )  # fmt: skip
    return RootcauseReport(len(windows), len(candidates), round(time.perf_counter() - started, 1))


def _frame(excursion_id: int, window_start: object, window_end: object, ranked: pd.DataFrame,
           signal: str, pattern: str | None) -> pd.DataFrame:  # fmt: skip
    if ranked.empty:
        return pd.DataFrame()
    is_chamber = (ranked["factor_type"] == "chamber").to_numpy()
    return pd.DataFrame(
        {
            "excursion_id": excursion_id,
            "window_start": pd.Timestamp(window_start),  # type: ignore[arg-type]
            "window_end": pd.Timestamp(window_end),  # type: ignore[arg-type]
            "signal": signal,
            "pattern": pattern,
            "factor_type": ranked["factor_type"].to_numpy(),
            "chamber_id": ranked["factor_id"].where(is_chamber).astype("Int32"),
            "recipe_id": ranked["factor_id"].where(~is_chamber).astype("Int32"),
            "n_through": ranked["n_through"].to_numpy(),
            "low_through": ranked["low_through"].to_numpy(),
            "n_population": ranked["n_population"].to_numpy(),
            "n_low": ranked["n_low"].to_numpy(),
            "lift": ranked["lift"].astype(float).to_numpy(),
            "chi2": ranked["chi2"].astype(float).to_numpy(),
            "suspect_rank": ranked["suspect_rank"].to_numpy(),
        }
    )
