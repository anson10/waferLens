"""Trains, evaluates and registers the SECOM fail model; writes its results to the database
and docs/secom_model.md.

    python -m waferlens.ml     (or: make secom-model; needs make secom and the MLflow server)
"""

from __future__ import annotations

from pathlib import Path

from waferlens.config import get_settings
from waferlens.db.session import get_engine
from waferlens.ml import secom
from waferlens.ml.experiment import run_experiment
from waferlens.ml.report import render
from waferlens.ml.store import write_results

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "secom_model.md"


def main() -> None:
    engine = get_engine()
    exp = run_experiment(secom.load(engine), get_settings().mlflow_tracking_uri)
    written = write_results(engine, exp)
    OUTPUT.write_text(render(exp))
    print(f"registered secom-fail-predictor {exp.model_version}: holdout PR-AUC "
          f"{exp.chosen.scores.pr_auc:.3f} (chance {exp.chosen.scores.prevalence:.3f}); "
          f"{written['scores']} scores; wrote {OUTPUT.relative_to(ROOT)}")  # fmt: skip


if __name__ == "__main__":
    main()
