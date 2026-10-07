"""Scores every sorted wafer map with FabEye and replaces ``wafer_patterns``.

Maps are read in chunks with a server-side cursor (a demo fab holds 25k maps), sent in
FabEye's batches of 64, and written in one transaction at the end, so a failed run leaves
the previous scores in place.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, insert, text

from waferlens.db.models import WaferPattern
from waferlens.patterns.fabeye import FabEye

CHUNK = 2048
ALPHA = 0.1  # FabEye's 90% prediction sets


@dataclass
class ScoreReport:
    wafers: int = 0
    by_pattern: dict[str, int] = field(default_factory=dict)
    accepted: int = 0
    model: str = ""
    seconds: float = 0.0


def score_wafers(engine: Engine, client: FabEye, alpha: float = ALPHA) -> ScoreReport:
    started = time.perf_counter()
    report = ScoreReport(model=client.version())
    scored_at = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    with engine.connect().execution_options(stream_results=True, yield_per=CHUNK) as conn:
        result = conn.execute(text("SELECT wafer_id, bin_map FROM wafer_maps ORDER BY wafer_id"))
        for chunk in result.partitions():
            ids = [r.wafer_id for r in chunk]
            for wafer_id, p in zip(ids, client.predict([r.bin_map for r in chunk], alpha),
                                   strict=True):  # fmt: skip
                rows.append({"wafer_id": wafer_id, "pattern": p.pattern,
                             "confidence": p.confidence, "auto_accept": p.auto_accept,
                             "prediction_set": p.prediction_set, "alpha": alpha,
                             "model": report.model, "scored_at": scored_at})  # fmt: skip
                report.by_pattern[p.pattern] = report.by_pattern.get(p.pattern, 0) + 1
                report.accepted += p.auto_accept
    with engine.begin() as conn:
        conn.execute(delete(WaferPattern))
        if rows:
            conn.execute(insert(WaferPattern), rows)
    report.wafers = len(rows)
    report.seconds = round(time.perf_counter() - started, 1)
    return report
