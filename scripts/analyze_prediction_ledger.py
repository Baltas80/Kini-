from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from kini_engine.diagnostics import analyze_prediction_rows
from kini_engine.ledger import read_prediction_ledger


def _load_results(path: Path, ledger_path: Path) -> tuple[dict[str, Any], str]:
    try:
        results = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read backtest results JSON: {path}") from exc

    ledger_metadata = results.get("forecast_ledger")
    if not isinstance(ledger_metadata, dict):
        raise TypeError("backtest results do not contain forecast_ledger metadata")
    expected_hash = ledger_metadata.get("sha256")
    if not isinstance(expected_hash, str):
        raise TypeError("backtest results do not contain the ledger SHA-256")
    if ledger_metadata.get("rows") != results.get("n_total"):
        raise ValueError("backtest result and ledger forecast counts disagree")
    if (
        ledger_metadata.get("path")
        and Path(ledger_metadata["path"]).name != ledger_path.name
    ):
        raise ValueError("backtest results point to a different ledger filename")
    return results, expected_hash


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze archived out-of-sample Quiniela prediction errors."
    )
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--results-json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-segment-n", type=int, default=100)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args()

    try:
        expected_hash = None
        results = None
        if args.results_json is not None:
            results, expected_hash = _load_results(args.results_json, args.ledger)
        manifest, rows = read_prediction_ledger(
            args.ledger,
            expected_sha256=expected_hash,
        )
        if results is not None:
            total = int(results.get("n_total", 0))
            if total != len(rows):
                raise ValueError("backtest and ledger row counts disagree")
            for mode in manifest["model_modes"]:
                model_n = int(results.get(mode, {}).get("n", 0))
                if model_n != len(rows):
                    raise ValueError(
                        f"{mode} backtest count {model_n} does not match ledger rows {len(rows)}"
                    )
            market_n = int(results.get("market", {}).get("n", 0))
            ledger_market_n = sum(row["market_eligible"] for row in rows)
            if market_n != ledger_market_n:
                raise ValueError(
                    f"market metrics count {market_n} does not match eligible ledger rows {ledger_market_n}"
                )

        report = analyze_prediction_rows(
            manifest,
            rows,
            min_segment_n=args.min_segment_n,
            bootstrap_samples=args.bootstrap_samples,
        )
        report["source"]["ledger_sha256"] = hashlib.sha256(
            args.ledger.read_bytes()
        ).hexdigest()
        serialized = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized + "\n", encoding="utf-8")
        print(
            "PREDICTION_DIAGNOSTICS_OK: "
            f"{len(rows)} fixtures, {len(manifest['model_modes'])} models, "
            f"{sum(row['market_eligible'] for row in rows)} market-eligible"
        )
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
