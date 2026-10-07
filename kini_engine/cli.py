from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backtest import walk_forward
from .dataio import load_matches_csv, validate_matches


def load_csv(path: str):
    matches = load_matches_csv(path)
    validate_matches(matches)
    return matches


def main() -> None:
    ap = argparse.ArgumentParser(prog="kini")
    ap.add_argument("command", choices=("backtest",))
    ap.add_argument("csv")
    ap.add_argument("--min-train", type=int, default=80)
    args = ap.parse_args()
    matches = load_csv(args.csv)
    if args.command == "backtest":
        print(json.dumps(walk_forward(matches, min_train=args.min_train)["metrics"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
