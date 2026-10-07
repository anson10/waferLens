"""Real-time SPC: EWMA and CUSUM updated one point at a time.

The batch engine (``waferlens.spc``) charts a whole series at once; here each chamber x sensor
series keeps a small state (point count, EWMA, the two CUSUM sums, the last point seen) and
moves it forward per event. Same frozen Phase I limits, same rules, same reset after a CUSUM
signal: fed the same points in the same order, it raises exactly the batch engine's EWMA and
CUSUM alarms (tested against ``charts.ewma`` / ``charts.cusum``).

Western Electric rules and T² stay in batch: the first need a window of past points, T² needs
a wafer's full metrology, and sensor drift is what EWMA and CUSUM catch fastest (ADR-0006).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

LAMBDA = 0.2
WIDTH = 3.0
K = 0.5
H = 5.0


@dataclass(frozen=True)
class Limits:
    """Frozen Phase I limits of one chamber-scope sensor series (``spc_control_limits``)."""

    limit_id: int
    center: float
    sigma: float
    baseline_end: datetime


@dataclass(frozen=True)
class SeriesState:
    limit_id: int
    n: int = 0  # live points seen (EWMA's i)
    ewma: float = 0.0
    cusum_up: float = 0.0
    cusum_down: float = 0.0
    last_measured_at: datetime | None = None
    last_event_id: str | None = None


@dataclass(frozen=True)
class Alarm:
    chart: str  # 'ewma' | 'cusum'
    statistic: float
    direction: str  # 'up' | 'down'


def ewma_limit(n: int, lam: float = LAMBDA, width: float = WIDTH) -> float:
    """Exact (time-varying) EWMA limit at the n-th point, as in ``charts.ewma``."""
    return width * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * n)))


def is_new(state: SeriesState, measured_at: datetime, event_id: str) -> bool:
    """Events arrive in order per chamber; anything at or before the last one is a replay."""
    if state.last_measured_at is None:
        return True
    if measured_at != state.last_measured_at:
        return measured_at > state.last_measured_at
    return state.last_event_id is None or event_id > state.last_event_id


def update(state: SeriesState, limits: Limits, value: float, measured_at: datetime,
           event_id: str) -> tuple[SeriesState, list[Alarm]]:  # fmt: skip
    """Advance one series by one point. Points inside the baseline window only move the
    bookkeeping (they defined the limits; the batch engine doesn't chart them either)."""
    if state.limit_id != limits.limit_id:  # limits relearned: start the charts over
        state = SeriesState(limit_id=limits.limit_id)
    seen = replace(state, last_measured_at=measured_at, last_event_id=event_id)
    if measured_at < limits.baseline_end:
        return seen, []

    z = (value - limits.center) / limits.sigma
    n = state.n + 1
    w = LAMBDA * z + (1 - LAMBDA) * state.ewma
    alarms = []
    if abs(w) > ewma_limit(n):
        alarms.append(Alarm("ewma", w, "up" if w > 0 else "down"))
    up = max(0.0, state.cusum_up + z - K)
    down = max(0.0, state.cusum_down - z - K)
    if up > H or down > H:
        alarms.append(Alarm("cusum", up if up > H else down, "up" if up > H else "down"))
        up = down = 0.0  # restart after a signal, like a corrective action
    return replace(seen, n=n, ewma=w, cusum_up=up, cusum_down=down), alarms
