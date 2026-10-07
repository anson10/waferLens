# ADR-0006: EWMA and CUSUM alongside Western Electric, limits per chamber

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

Fab SPC is traditionally a Shewhart individuals chart with the Western Electric run rules.
The excursions that matter in WaferLens are often small: chamber offsets of 0.5–1σ, drifts
that start at zero and ramp up over days, recipe changes of 1–2.5σ. Each wafer processed
after an excursion starts but before it is caught is exposed, so detection delay is
measured in wafers at risk; each false alarm costs an engineer's investigation, so the
false-alarm rate matters just as much.

We measured both, by simulation against published tables and on the demo fab against its
ground truth (docs/spc_benchmark.md).

## Options considered

1. **Shewhart rule 1 only.** Few false alarms (ARL₀ ≈ 370), but slow on small shifts:
   ~156 points at 0.5σ, ~44 at 1σ.
2. **Western Electric rules 1–4 together.** Faster on small shifts (~28 points at 0.5σ) but
   ARL₀ ≈ 90: four times the false alarms. Rule 4 (8 in a row on one side) also fires on
   static chamber offsets when chambers are pooled.
3. **EWMA (λ 0.2, L 3) and tabular CUSUM (k 0.5, h 5).** Charts with memory: ~42 and ~38
   points at 0.5σ, with ARL₀ ≈ 540 and ≈ 475, i.e. *fewer* false alarms than Shewhart.
4. **Hotelling T² for correlated parameters.** Catches changes in the joint behaviour of a
   step's parameters that per-parameter charts miss.

## Decision

Run every chart and store every alarm, but treat **EWMA and CUSUM as the primary detectors**,
keep **Western Electric rule 1 as the backstop** for large sudden shifts (all charts signal
within 2–3 points at 3σ), report rules 2–4 as supporting evidence, and use T² on metrology
steps. Set limits **per chamber**, with tool-level limits kept for comparison.

## Consequences

- **Small shifts caught about 4× sooner than with Shewhart at a lower false-alarm rate**
  (simulation, within 3% of published ARL values). On the demo fab at chamber scope, EWMA
  and CUSUM raised their first alarm after a median of 8–9 affected measurements, Shewhart
  after 33, against a chance baseline of 140–200 measurements.
- **Chamber-level limits detect sooner than tool-level ones:** pooling chambers slows EWMA
  from 8 to 12.5 points and CUSUM from 8.5 to 18.5, and makes WE rule 4 nearly useless
  (37.5 points vs a chance baseline of 48.5). This matches ADR-0002: excursions live in
  chambers.
- **More alarms to manage:** every chart's alarms are stored (156k on demo), so dashboards
  (phase 4) must group them by excursion and chart family rather than list them raw.
- **Memory charts are less intuitive:** an EWMA or CUSUM signal does not point at a single bad
  measurement. The alarm table keeps the statistic so an engineer can see the trend.
- **SPC is blind to spatial patterns by construction:** 13 of 40 demo excursions change no
  sensor or metrology value at all. That gap is what the wafer-map classifier (FabEye,
  phase 5) covers.
- **Lessons the measurement forced:** CUSUM must reset after a signal (1.6% → 0.23%
  false alarms), and T² limits must use the F-based formula for estimated parameters (the
  chi-square limit false-alarmed every ~5 points with ~30 baseline wafers).
