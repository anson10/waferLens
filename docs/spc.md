# SPC engine

`make spc` (or the `spc_results` Dagster asset) reads `marts.fct_measurements`, learns
Phase I control limits for every series, monitors everything after the baseline in
Phase II, and writes `spc_control_limits` and `spc_alarms`. dbt then builds
`marts.fct_spc_alarms` from them. Code: `src/waferlens/spc/` (`charts.py` = the statistics as
pure numpy, `engine.py` = series, limits, persistence).

## Series

| Source | Scope | One series per | Demo count |
|---|---|---|---|
| Sensor | chamber | chamber × parameter | 160 |
| Sensor | tool | tool × parameter (chambers pooled) | 80 |
| Metrology (wafer mean) | chamber | chamber × route step × parameter | ~350 |
| Metrology (wafer mean) | tool | tool × route step × parameter | ~170 |
| Metrology, multivariate | chamber | chamber × route step (all parameters of the step) | T² |

Chamber and tool scope run side by side: pooling chambers mixes their static offsets into
one distribution, which widens the limits. Phase 3b measures what that costs.

Demo run: 900 series, 875 with usable limits (25 skipped for fewer than 20 baseline points),
156,779 alarms in ~87 s, ~1.5 GB peak memory.

## Phase I: limits from a baseline

- **Window:** each series' first 30 days (`--baseline-days`).
- **Center:** median. **Sigma:** average moving range / 1.128 (d2 for n = 2). A slow drift
  inside the baseline inflates the moving range far less than the sample standard deviation
  (tested: 3-sigma drift, sigma estimated within 15%).
- **Trimming:** one pass drops points beyond 4 sigma and re-estimates, so a baseline that
  catches an outlier or the start of an excursion still gives sane limits.
- **T²:** baseline mean vector and inverse covariance; limit = chi-square(p) quantile at
  alpha = 0.0027 (same false-alarm rate as a 3-sigma chart).
- **Frozen and versioned:** limits are stored and reused by every later run. `--relearn`
  writes a new version; alarms always point at the version that raised them.

## Phase II: charts

| Chart | Rule | Good at |
|---|---|---|
| `we1` | 1 point beyond 3σ | large sudden shifts, outliers |
| `we2` | 2 of 3 beyond 2σ, same side | moderate shifts |
| `we3` | 4 of 5 beyond 1σ, same side | small to moderate shifts |
| `we4` | 8 in a row on one side | small sustained shifts |
| `ewma` | λ = 0.2, L = 3, exact time-varying limits | small shifts, slow drifts |
| `cusum` | tabular, k = 0.5, h = 5, reset after each signal | small sustained shifts |
| `t2` | Hotelling T² over a step's metrology parameters | broken correlations between parameters |

Alarms are recomputed in full on every run and keyed on (limits, chart, wafer, step, pass),
so reruns can't duplicate them.

## Calibration: false-alarm rates match theory

Measured on the demo fab, chamber-scope sensor points in Phase II that lie outside every
injected excursion on their chamber (2.46M points):

| Chart | Alarms per point | Theory |
|---|---|---|
| `we1` | 0.280% | 2·P(Z > 3) = 0.27% |
| `we2` | 0.215% | ≈ 0.21% |
| `we3` | 0.464% | ≈ 0.45% |
| `we4` | 0.787% | 2·0.5⁸ = 0.78% |
| `cusum` | 0.231% | two-sided ARL₀ ≈ 465 → ≈ 0.22% |
| `ewma` | 0.295% | per-point exceedance, λ = 0.2, L = 3 |

The first CUSUM version used Page's identity (a cumulative sum minus its running minimum),
which is vectorised but never resets: one false alarm then flagged every following point
while the sum hovered above h, giving 1.61% instead of ~0.22%. CUSUM now resets after each
signal, as the published ARL tables assume. A property test (`hypothesis`) checks these
rates on simulated in-control data for random seeds. Its tolerances are 5 standard deviations of each
rate measured over 300 seeds: a first, tighter WE4 bound failed in CI on seed 26 (0.66%),
which turned out to be the lowest of the 300, not a broken chart. WE4 rates spread the most
because its alarms cluster.

## What 3b and 3c add

- Average run length (ARL) per chart for shifts of 0.25σ–3σ, and detection delay against
  `excursions_ground_truth`.
- Commonality analysis: which chamber or recipe the low-yield wafers share, scored against the
  injected root cause.
