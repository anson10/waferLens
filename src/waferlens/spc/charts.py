"""Control-chart statistics as pure numpy functions.

Every function takes a series already standardised against frozen Phase I limits,
``z = (x - center) / sigma``, in time order, and returns one boolean per point: "this point
signals". Keeping the charts free of I/O makes each one testable on hand-made sequences and
lets the ARL benchmark (phase 3b) run them on millions of simulated points.

Defaults are the textbook pairs (Montgomery, *Introduction to Statistical Quality Control*):
EWMA lambda = 0.2, L = 3 and CUSUM k = 0.5, h = 5 both give an in-control ARL of roughly
500 points.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal, stats

MR_TO_SIGMA = 1.128  # d2 for moving ranges of two points


@dataclass(frozen=True)
class Limits:
    center: float
    sigma: float
    n: int


def phase1_limits(values: np.ndarray, trim_sigma: float = 4.0) -> Limits | None:
    """Robust Phase I estimate for an individuals chart.

    Center = median; sigma = average moving range / 1.128, which a slow drift inside the
    baseline inflates far less than the sample standard deviation does. One trimming pass
    drops points beyond ``trim_sigma`` (a baseline contaminated by an outlier or the start of
    an excursion) and re-estimates. Needs at least 10 points.
    """
    x = values[np.isfinite(values)]
    estimate = _robust(x)
    if estimate is None:
        return None
    center, sigma = estimate
    x = x[np.abs(x - center) <= trim_sigma * sigma]
    estimate = _robust(x)
    if estimate is None:
        return None
    center, sigma = estimate
    return Limits(center, sigma, len(x))


def _robust(x: np.ndarray) -> tuple[float, float] | None:
    if len(x) < 10:
        return None
    sigma = float(np.mean(np.abs(np.diff(x)))) / MR_TO_SIGMA
    return (float(np.median(x)), sigma) if sigma > 0 else None


def western_electric(z: np.ndarray) -> dict[str, np.ndarray]:
    """Western Electric rules, each flagging the point that completes the pattern:

    we1  one point beyond 3 sigma
    we2  2 of 3 consecutive points beyond 2 sigma, same side
    we3  4 of 5 consecutive points beyond 1 sigma, same side
    we4  8 consecutive points on the same side of the center
    """
    return {
        "we1": np.abs(z) > 3,
        "we2": _k_of_n(z > 2, 2, 3) | _k_of_n(z < -2, 2, 3),
        "we3": _k_of_n(z > 1, 4, 5) | _k_of_n(z < -1, 4, 5),
        "we4": _k_of_n(z > 0, 8, 8) | _k_of_n(z < 0, 8, 8),
    }


def _k_of_n(hit: np.ndarray, k: int, n: int) -> np.ndarray:
    """True at i when at least k of the n points ending at i are hits (i >= n - 1)."""
    counts = np.convolve(hit.astype(np.int32), np.ones(n, dtype=np.int32))[: len(hit)]
    out = counts >= k
    out[: n - 1] = False
    return out & hit  # the completing point must itself be a hit


def ewma(z: np.ndarray, lam: float = 0.2, width: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    """EWMA statistic and its signal, with exact (time-varying) limits.

    w_i = lam * z_i + (1 - lam) * w_{i-1}, w_0 = 0; signals when
    |w_i| > width * sqrt(lam / (2 - lam) * (1 - (1 - lam)^(2i))).
    """
    w = np.asarray(signal.lfilter([lam], [1.0, -(1.0 - lam)], z), dtype=float)
    i = np.arange(1, len(z) + 1)
    limit = width * np.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * i)))
    return w, np.abs(w) > limit


def cusum(
    z: np.ndarray, k: float = 0.5, h: float = 5.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Tabular CUSUM (upper, lower, signal up, signal down), reset after each signal.

    C+_i = max(0, C+_{i-1} + z_i - k), C-_i = max(0, C-_{i-1} - z_i - k); a side signals when
    it exceeds h and both restart from 0, as after a corrective action. Without the reset a
    single false alarm would keep flagging every following point while the sum hovers above
    h (measured: 1.6% of in-control points instead of ~0.4%), and run lengths would no longer
    be comparable with the published ARL tables. A plain loop: ~1M points/s, fast enough.
    """
    n = len(z)
    upper, lower = np.empty(n), np.empty(n)
    up, down = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    c_up = c_down = 0.0
    for i, v in enumerate(z.tolist()):
        c_up = max(0.0, c_up + v - k)
        c_down = max(0.0, c_down - v - k)
        upper[i], lower[i] = c_up, c_down
        if c_up > h or c_down > h:
            up[i], down[i] = c_up > h, c_down > h
            c_up = c_down = 0.0
    return upper, lower, up, down


@dataclass(frozen=True)
class T2Limits:
    mean: np.ndarray
    cov_inv: np.ndarray
    limit: float
    n: int


def t2_limits(x: np.ndarray, alpha: float = 0.0027) -> T2Limits | None:
    """Phase I mean and inverse covariance for Hotelling T² on rows of ``x`` (m x p).

    The Phase II limit for a new observation when mean and covariance are *estimated* from
    m baseline rows (Montgomery, eq. 11.19):

        UCL = p (m + 1) (m - 1) / (m^2 - m p) * F(1 - alpha; p, m - p)

    It tends to the chi-square(p) quantile as m grows. With ~30 baseline wafers the
    chi-square limit is far too tight: on demo it made T² false-alarm every ~5 points.
    alpha = 0.0027 matches a 3-sigma univariate chart.
    """
    x = x[np.isfinite(x).all(axis=1)]
    m, p = x.shape
    if m < max(10, 3 * p):
        return None
    cov = np.cov(x, rowvar=False)
    if np.linalg.cond(cov) > 1e12:
        return None
    limit = p * (m + 1) * (m - 1) / (m * m - m * p) * stats.f.ppf(1 - alpha, p, m - p)
    return T2Limits(x.mean(axis=0), np.linalg.inv(cov), float(limit), m)


def hotelling_t2(x: np.ndarray, limits: T2Limits) -> tuple[np.ndarray, np.ndarray]:
    """T² statistic per row and whether it exceeds the limit."""
    d = x - limits.mean
    t2 = np.einsum("ij,jk,ik->i", d, limits.cov_inv, d)
    return t2, t2 > limits.limit
