"""Run commonality for every injected excursion and store the ranked suspects.

Each analysis gets only the excursion's time window, never its chamber or recipe; where
the true cause lands in the ranking is the score (``marts.fct_root_cause_eval``).
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
            text("SELECT excursion_id, start_time, end_time FROM excursions_ground_truth "
                 "ORDER BY excursion_id")
        ).all()  # fmt: skip

    frames = []
    for excursion_id, window_start, window_end in windows:
        ranked = commonality(engine, window_start, window_end, low_quantile=low_quantile,
                             min_support=min_support)  # fmt: skip
        if ranked.empty:
            continue
        is_chamber = (ranked["factor_type"] == "chamber").to_numpy()
        frames.append(
            pd.DataFrame(
                {
                    "excursion_id": excursion_id,
                    "window_start": pd.Timestamp(window_start),
                    "window_end": pd.Timestamp(window_end),
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
        )

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
