"""CLI: ``python -m waferlens.spc`` (needs the dbt marts: run ``make dbt`` first)."""

from __future__ import annotations

import argparse

from waferlens.spc.engine import SpcConfig, run_spc


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase I limits + Phase II SPC alarms.")
    parser.add_argument("--relearn", action="store_true", help="write new limit versions")
    parser.add_argument("--baseline-days", type=float, default=SpcConfig.baseline_days)
    args = parser.parse_args()
    report = run_spc(config=SpcConfig(baseline_days=args.baseline_days), relearn=args.relearn)
    print(
        f"SPC: {report.series} series ({report.skipped} skipped), limits {report.limits_new} new"
        f" / {report.limits_reused} reused, {sum(report.alarms.values()):,} alarms in"
        f" {report.seconds} s"
    )
    for chart, n in sorted(report.alarms.items()):
        print(f"  {chart:<6} {n:>8,}")


if __name__ == "__main__":
    main()
