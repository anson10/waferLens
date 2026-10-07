"""Average run length (ARL) by Monte Carlo: how many points each chart needs to signal.

ARL₀ (no shift) is the mean number of points between false alarms; ARL₁ (a shift of
delta sigma from the first point) is the mean detection delay. Each chart runs on a batch of
independent sequences at once (rows of a matrix), with the same parameters as
``waferlens.spc.charts``; a test checks the batch versions against the 1-D ones and the
results against published tables (Montgomery, *Introduction to Statistical Quality Control*).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy import signal, stats

Detector = Callable[[np.ndarray], np.ndarray]  # (runs, points) -> first signal index or -1


def _first(hit: np.ndarray) -> np.ndarray:
    """Index of the first True per row, -1 where a row never signals."""
    first = hit.argmax(axis=1)
    return np.where(hit.any(axis=1), first, -1)


def _k_of_n(hit: np.ndarray, k: int, n: int) -> np.ndarray:
    csum = np.cumsum(hit, axis=1, dtype=np.int32)
    window = csum.copy()
    window[:, n:] -= csum[:, :-n]
    out = (window >= k) & hit
    out[:, : n - 1] = False
    return out


def shewhart(z: np.ndarray) -> np.ndarray:
    return _first(np.abs(z) > 3)


def western_electric_any(z: np.ndarray) -> np.ndarray:
    """First point on which any of Western Electric rules 1-4 signals."""
    hit = np.abs(z) > 3
    hit |= _k_of_n(z > 2, 2, 3) | _k_of_n(z < -2, 2, 3)
    hit |= _k_of_n(z > 1, 4, 5) | _k_of_n(z < -1, 4, 5)
    hit |= _k_of_n(z > 0, 8, 8) | _k_of_n(z < 0, 8, 8)
    return _first(hit)


def ewma(z: np.ndarray, lam: float = 0.2, width: float = 3.0) -> np.ndarray:
    w = signal.lfilter([lam], [1.0, -(1.0 - lam)], z, axis=1)
    i = np.arange(1, z.shape[1] + 1)
    limit = width * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * i)))
    return _first(np.abs(w) > limit)


def cusum(z: np.ndarray, k: float = 0.5, h: float = 5.0) -> np.ndarray:
    """Tabular CUSUM; only the first signal matters for a run length, so no reset."""
    runs, points = z.shape
    c_up, c_down = np.zeros(runs), np.zeros(runs)
    first = np.full(runs, -1)
    for t in range(points):
        c_up = np.maximum(0.0, c_up + z[:, t] - k)
        c_down = np.maximum(0.0, c_down - z[:, t] - k)
        new = (first < 0) & ((c_up > h) | (c_down > h))
        first[new] = t
        if (first >= 0).all():
            break
    return first


@dataclass(frozen=True)
class Arl:
    chart: str
    shift: float
    arl: float
    sdrl: float
    censored: int  # runs that never signalled within the horizon (counted at the horizon)


def run_lengths(detect: Detector, z: np.ndarray) -> tuple[np.ndarray, int]:
    first = detect(z)
    censored = int((first < 0).sum())
    return np.where(first < 0, z.shape[1], first + 1), censored


UNIVARIATE: dict[str, Detector] = {
    "Shewhart (WE rule 1)": shewhart,
    "Western Electric 1-4": western_electric_any,
    "EWMA (λ 0.2, L 3)": ewma,
    "CUSUM (k 0.5, h 5)": cusum,
}


def univariate_arl(
    shifts: list[float], runs: int = 2000, horizon: int = 5000, seed: int = 7
) -> list[Arl]:
    """Zero-state ARL: the mean shifts by ``delta`` sigma from the first point."""
    rng = np.random.default_rng(seed)
    out = []
    for delta in shifts:
        z = rng.standard_normal((runs, horizon)) + delta
        for name, detect in UNIVARIATE.items():
            lengths, censored = run_lengths(detect, z)
            out.append(Arl(name, delta, float(lengths.mean()), float(lengths.std()), censored))
    return out


def multivariate_arl(
    shifts: list[float], rho: float = 0.6, runs: int = 2000, horizon: int = 5000, seed: int = 11
) -> list[Arl]:
    """Two correlated parameters (rho), one of them shifting by ``delta``.

    T² with known parameters (chi-square limit at alpha 0.0027) against the common
    alternative of a 3-sigma chart on each parameter separately.
    """
    rng = np.random.default_rng(seed)
    cov = np.array([[1.0, rho], [rho, 1.0]])
    cov_inv = np.linalg.inv(cov)
    limit = float(stats.chi2.ppf(1 - 0.0027, 2))
    out = []
    for delta in shifts:
        shift = np.array([delta, 0.0])
        x = rng.multivariate_normal([0.0, 0.0], cov, size=(runs, horizon)) + shift
        t2 = np.einsum("rti,ij,rtj->rt", x, cov_inv, x)
        for name, hit in (
            ("Hotelling T² (p 2, ρ 0.6)", t2 > limit),
            ("Shewhart on each parameter", (np.abs(x) > 3).any(axis=2)),
        ):
            first = _first(hit)
            censored = int((first < 0).sum())
            lengths = np.where(first < 0, horizon, first + 1)
            out.append(Arl(name, delta, float(lengths.mean()), float(lengths.std()), censored))
    return out
