# ADR-0010: Consume FabEye as a service instead of retraining

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

The question WaferLens answers ends with "what does it look like on the wafer?". Wafer-map
pattern classification is already solved in the sister project FabEye: a CNN trained on
WM-811K with lot-disjoint evaluation, class-conditional conformal prediction sets and a
calibrated auto-accept rule, exported to ONNX behind a FastAPI service (`/predict/batch`,
`/calibration`, `/metrics`).

What FabEye could never measure is how its model behaves on maps from a fab with
timestamps, process history and known causes: WM-811K has no time and no ground truth beyond
an expert label. WaferLens has both, because its simulator logs which wafers carry an
injected pattern (`wafer_pattern_truth`).

## Options considered

1. **Retrain a classifier here** on simulated maps. Easy to score high on clean simulated
   patterns, duplicates FabEye, and proves nothing about real data.
2. **Import FabEye as a Python package** and run the ONNX model in-process. Tight coupling:
   WaferLens would pin FabEye's dependencies (onnxruntime, OpenCV) and bypass its API,
   auth, calibration checks and metrics.
3. **Call FabEye as a service**, built from its GitHub repository at a pinned commit, through
   the same API any client would use.

## Decision

Option 3. docker-compose builds `fabeye` from `github.com/anson10/FabEye` at a pinned commit
(the ONNX model and calibration file are in that repo). `waferlens.patterns` converts sort
bin maps to FabEye's 0/1/2 format, sends them 64 at a time with the API key, and stores
pattern, confidence, auto-accept flag and prediction set in `wafer_patterns`; a Dagster
asset runs it after every load. The evaluation scores FabEye against the simulator's
per-wafer truth and against FabEye's own claims from `/calibration`. WaferLens never trains
a wafer-map model (CLAUDE.md).

## Consequences

- **A domain-shift test FabEye couldn't run:** on 24,090 simulated wafers FabEye reaches
  macro-F1 0.909 (0.858 on real lots), but its guarantees break for two classes: strong
  uniform "random" fields are called Near-full (Random set coverage 52% against ~90%), and
  thin scratches on small maps are missed more. 450 wafers get an empty prediction set, a
  usable out-of-distribution flag.
- **The test is easier than real data,** because simulated patterns are parametric; the
  report says so rather than claiming FabEye is better on WaferLens maps.
- **Version pinning:** upgrading FabEye is a one-line change to the commit in
  docker-compose, and every score row records the model and API version.
- **Costs:** the full pipeline now needs the FabEye container (`make up` starts it); the
  first build fetches the repo and installs onnxruntime and OpenCV (~1 minute). Scoring
  24k wafers takes ~90 s over HTTP, about 2.5x slower than FabEye's raw ONNX throughput,
  the price of JSON over a network boundary.
