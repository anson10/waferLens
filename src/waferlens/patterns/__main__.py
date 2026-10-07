"""Scores every sorted wafer with FabEye, then writes docs/fabeye_eval.md.

python -m waferlens.patterns     (or: make fabeye-report; needs make up and a loaded fab)
"""

from __future__ import annotations

from pathlib import Path

from waferlens.config import get_settings
from waferlens.db.session import get_engine
from waferlens.patterns.evaluate import evaluate, reference_numbers
from waferlens.patterns.fabeye import FabEye
from waferlens.patterns.report import render
from waferlens.patterns.score import score_wafers

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "fabeye_eval.md"


def main() -> None:
    settings = get_settings()
    client = FabEye(settings.fabeye_url, settings.fabeye_api_key)
    engine = get_engine()
    report = score_wafers(engine, client)
    ev = evaluate(engine, reference_numbers(client.calibration()))
    OUTPUT.write_text(render(ev, report.model))
    print(f"scored {report.wafers:,} wafers in {report.seconds}s; macro-F1 {ev.macro_f1:.3f}, "
          f"coverage {ev.coverage:.1%}; wrote {OUTPUT.relative_to(ROOT)}")  # fmt: skip


if __name__ == "__main__":
    main()
