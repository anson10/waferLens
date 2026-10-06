"""CLI: ``python -m waferlens.simulate --profile demo --seed 42``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from waferlens.simulate.config import DEFAULT_CONFIG, load_config
from waferlens.simulate.run import simulate, write_parquet


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a fab and write Parquet files.")
    parser.add_argument("--profile", default="demo", help="dev | demo | stress")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, help="output directory (default data/<profile>)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.profile not in cfg.profiles:
        parser.error(f"unknown profile {args.profile}; choose from {sorted(cfg.profiles)}")
    result = simulate(cfg, args.profile, args.seed)
    out = args.out or Path("data") / args.profile
    write_parquet(result, out)
    print(json.dumps(result.summary, indent=2, default=str))
    print(f"wrote {len(result.tables)} tables to {out}/")


if __name__ == "__main__":
    main()
