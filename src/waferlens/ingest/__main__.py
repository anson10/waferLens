"""CLI: ``python -m waferlens.ingest --data data/demo``."""

from __future__ import annotations

import argparse
from pathlib import Path

from waferlens.ingest.loader import load


def main() -> None:
    parser = argparse.ArgumentParser(description="Load simulator Parquet output into Postgres.")
    parser.add_argument("--data", type=Path, default=Path("data/demo"))
    parser.add_argument("--no-validate", action="store_true", help="skip data contracts")
    args = parser.parse_args()

    report = load(args.data, validate=not args.no_validate)
    width = max(len(k) for k in report.seconds)
    for step, seconds in report.seconds.items():
        rows = report.rows.get(step)
        print(f"  {step:<{width}}  {seconds:>7.2f} s" + (f"  {rows:>10,} rows" if rows else ""))
    print(f"loaded {report.total_rows:,} rows from {args.data} in {report.total_seconds:.1f} s")


if __name__ == "__main__":
    main()
