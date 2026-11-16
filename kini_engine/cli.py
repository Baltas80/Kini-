from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

from .backtest import compare_walk_forward, walk_forward
from .dataio import load_matches_csv, validate_matches
from .ledger import write_prediction_ledger


def load_csv(path: str):
    matches = load_matches_csv(path)
    validate_matches(matches)
    return matches


def main() -> None:
    ap = argparse.ArgumentParser(prog="kini")
    ap.add_argument("command", choices=("backtest", "compare"))
    ap.add_argument("csv")
    ap.add_argument("--min-train", type=int, default=80)
    ap.add_argument("--refit-every", type=int, default=1)
    ap.add_argument("--ledger-jsonl", type=Path)
    ap.add_argument("--include-forecast-rows", action="store_true")
    args = ap.parse_args()
    matches = load_csv(args.csv)
    if args.command == "backtest":
        if args.ledger_jsonl is not None or args.include_forecast_rows:
            ap.error("forecast ledger options are available only for the compare command")
        result = walk_forward(matches, min_train=args.min_train, refit_every=args.refit_every)
        output = result["metrics"]
    else:
        result = compare_walk_forward(
            matches, min_train=args.min_train, refit_every=args.refit_every
        )
        forecast_rows = result.pop("forecast_rows", [])
        if args.ledger_jsonl is not None:
            dataset_path = Path(args.csv)
            dataset_bytes = dataset_path.read_bytes()
            profile_path = dataset_path.with_name(
                f"{dataset_path.stem}.profile.json"
            )
            profile_bytes = profile_path.read_bytes() if profile_path.is_file() else None
            model_modes = (
                sorted(forecast_rows[0].get("model_probabilities", {}))
                if forecast_rows
                else []
            )
            manifest = {
                "schema_version": 1,
                "run_id": os.getenv("GITHUB_RUN_ID"),
                "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
                "workflow_event": os.getenv("GITHUB_EVENT_NAME"),
                "code_revision": (
                    os.getenv("KINI_CODE_REVISION")
                    or os.getenv("GITHUB_SHA")
                    or "unknown"
                ),
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "python_version": platform.python_version(),
                "dataset_path": str(dataset_path),
                "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
                "dataset_size_bytes": len(dataset_bytes),
                "dataset_rows": len(matches),
                "dataset_profile_path": (
                    str(profile_path) if profile_bytes is not None else None
                ),
                "dataset_profile_sha256": (
                    hashlib.sha256(profile_bytes).hexdigest()
                    if profile_bytes is not None
                    else None
                ),
                "forecast_start_date": result.get("test_start_date"),
                "forecast_end_date": result.get("test_end_date"),
                "forecast_count": len(forecast_rows),
                "model_modes": model_modes,
                "run_config": result.get("run_config", {}),
            }
            ledger_rows = write_prediction_ledger(
                args.ledger_jsonl, manifest, forecast_rows
            )
            ledger_sha256 = hashlib.sha256(
                args.ledger_jsonl.read_bytes()
            ).hexdigest()
            result["forecast_ledger"] = {
                "schema_version": 1,
                "path": str(args.ledger_jsonl),
                "rows": ledger_rows,
                "sha256": ledger_sha256,
            }
        elif args.include_forecast_rows:
            result["forecast_rows"] = forecast_rows
        else:
            result["forecast_ledger"] = {
                "schema_version": result.get("forecast_ledger_schema_version", 1),
                "rows_available": len(forecast_rows),
                "persisted": False,
            }
        output = result
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
