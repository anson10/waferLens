# ADR-0008: SECOM evaluation: time-ordered split, walk-forward selection, PR-AUC

- **Status:** Accepted
- **Date:** 2026-10-07

## Context

Phase 5b predicts the pass/fail result of UCI SECOM runs from 590 anonymised process
sensors: 1,567 runs, 104 fails (6.6%), July to October 2008 (docs/data/secom.md). Three
properties of the data decide how a model can be judged:

- **The fail rate drifts** from 22% in July to 3% in September. Most published SECOM results
  use random or k-fold splits, which put runs from the same week in training and test.
- **Fails are rare.** Accuracy rewards predicting "pass" every time (93%), and ROC-AUC is
  dominated by the passes.
- **104 fails in total.** Any test set holds a few dozen at most, so every number has a wide
  interval, and choosing among many models on the same data selects partly for luck.

The question a fab would ask is forward in time: trained on what we have, how well does it
rank next month's runs?

## Options considered

1. **Random stratified split or k-fold CV**, reporting accuracy or ROC-AUC. Comparable with
   the literature; mixes past and future, and the metrics flatter a rare-class problem.
2. **Single time-ordered split, select on the test set.** Honest about time, but tuning on
   the holdout turns it into a validation set.
3. **Time-ordered holdout, walk-forward selection inside the training period, PR-AUC.** The
   holdout (latest 30%) is scored once; configurations are compared on expanding-window
   folds of the earlier 70%; the random-split score is computed only to measure the gap.

## Decision

Option 3:

- **Split:** first 70% of runs (by time) for training and selection, last 30% as holdout
  (470 runs, 26 fails).
- **Selection:** 17 configurations (logistic regression and LightGBM × missing-value
  strategy × feature selection) ranked by PR-AUC over walk-forward out-of-fold scores; all
  preprocessing fitted inside the pipeline on training rows only.
- **Metrics:** PR-AUC with a stratified bootstrap 95% interval and its chance level (the
  holdout fail rate); recall at 5% and 10% false-alarm rates, both with the threshold set on
  the training period ("forward") and set in hindsight on the holdout (upper bound).
- **Leakage gap:** the chosen configuration on 20 random stratified splits of the same size.
- **No changes after looking at the holdout.** If the holdout disagrees with the selection,
  the report says so instead of switching models.

## Consequences

- **The headline is the gap, not the score.** The chosen model reaches PR-AUC 0.065 on the
  holdout against 0.055 for chance (interval includes chance); the same model on a random
  split scores 0.177, 2.7x higher. That is the finding: forward in time, SECOM's sensors
  barely predict fails, and a random split would have hidden it.
- **Winner's curse is visible:** the selected configuration scored 0.129 in walk-forward CV
  and halved on the holdout; the logistic baseline did better on the holdout (0.081) and is
  reported, not adopted.
- **Thresholds don't transfer:** a threshold set for 10% false alarms in training gave 3.6%
  on the holdout, because the score distribution drifts with the process. A deployment
  would recalibrate on recent runs or alarm on the top k% each week.
- **Comparable with nothing published:** published SECOM numbers use random folds. The
  random-split column is the bridge.
- **Small-sample caveat stays in every report:** 26 holdout fails; a different boundary
  would move the numbers.
