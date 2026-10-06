from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .backtest import benchmark, walk_forward
from .core import KiniEngine, Match


def load_csv(path: str) -> list[Match]:
    df = pd.read_csv(path)
    out = []
    for _, r in df.iterrows():
        out.append(Match(
            date=str(r.get("Date") or r.get("date") or ""),
            home=str(r["HomeTeam"]),
            away=str(r["AwayTeam"]),
            home_goals=int(r["FTHG"]) if pd.notna(r.get("FTHG")) else None,
            away_goals=int(r["FTAG"]) if pd.notna(r.get("FTAG")) else None,
            result=str(r["FTR"]) if pd.notna(r.get("FTR")) else None,
        ))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="kini")
    ap.add_argument("command", choices=("backtest", "benchmark"))
    ap.add_argument("csv")
    ap.add_argument("--min-train", type=int, default=80)
    args = ap.parse_args()
    matches = load_csv(args.csv)
    if args.command == "backtest":
        print(json.dumps(walk_forward(matches, min_train=args.min_train)["metrics"], indent=2, ensure_ascii=False))
    elif args.command == "benchmark":
        print(json.dumps(benchmark(matches, min_train=args.min_train), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
