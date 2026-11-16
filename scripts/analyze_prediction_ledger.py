from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
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



def _validate_dataset_snapshot(
    manifest: dict[str, Any],
    dataset_path: Path,
    profile_path: Path,
) -> dict[str, Any]:
    """Verify the exact dataset/profile bytes used by the forecast-ledger run."""
    try:
        dataset_payload = dataset_path.read_bytes()
        profile_payload = profile_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read backtest dataset snapshot: {exc}") from exc

    expected_dataset_hash = manifest.get("dataset_sha256")
    expected_profile_hash = manifest.get("dataset_profile_sha256")
    if (
        not isinstance(expected_dataset_hash, str)
        or hashlib.sha256(dataset_payload).hexdigest() != expected_dataset_hash
    ):
        raise ValueError(
            "dataset CSV SHA-256 does not match prediction-ledger manifest"
        )
    if (
        not isinstance(expected_profile_hash, str)
        or hashlib.sha256(profile_payload).hexdigest() != expected_profile_hash
    ):
        raise ValueError(
            "dataset profile SHA-256 does not match prediction-ledger manifest"
        )

    expected_size = manifest.get("dataset_size_bytes")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size != len(dataset_payload)
    ):
        raise ValueError("dataset byte size does not match prediction-ledger manifest")

    expected_rows = manifest.get("dataset_rows")
    if (
        isinstance(expected_rows, bool)
        or not isinstance(expected_rows, int)
        or expected_rows <= 0
    ):
        raise ValueError("prediction-ledger manifest has an invalid dataset row count")
    if Path(str(manifest.get("dataset_path", ""))).name != dataset_path.name:
        raise ValueError(
            "dataset CSV filename does not match prediction-ledger manifest"
        )
    if Path(str(manifest.get("dataset_profile_path", ""))).name != profile_path.name:
        raise ValueError(
            "dataset profile filename does not match prediction-ledger manifest"
        )

    try:
        profile = json.loads(profile_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dataset profile is not valid UTF-8 JSON") from exc
    if not isinstance(profile, dict) or profile.get("integrity_passed") is not True:
        raise ValueError("dataset profile does not report successful integrity checks")
    for field in ("rows_after_complete_score_filter", "rows_after_deduplication"):
        if profile.get(field) != expected_rows:
            raise ValueError(
                f"dataset profile {field}={profile.get(field)!r} "
                f"does not match manifest row count {expected_rows}"
            )
    if not profile.get("source_urls") or not profile.get("source_cache_metadata"):
        raise ValueError("dataset profile is missing source/cache provenance")
    for field in (
        "rows_with_incomplete_scores",
        "invalid_result_labels",
        "score_result_mismatches",
        "conflicting_duplicate_fixtures",
    ):
        if int(profile.get(field, -1)) != 0:
            raise ValueError(
                f"dataset profile reports invalid {field}: {profile.get(field)!r}"
            )
    invalid_dates = int(
        profile.get("date_coverage", {}).get("invalid_or_missing_with_teams", -1)
    )
    if invalid_dates != 0:
        raise ValueError("dataset profile reports invalid or missing fixture dates")

    required_columns = {
        "Date",
        "HomeTeam",
        "AwayTeam",
        "FTHG",
        "FTAG",
        "League",
        "Season",
    }
    seen_fixtures: set[tuple[str, str, str, str, str]] = set()
    row_count = 0
    try:
        with dataset_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            missing = required_columns - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"dataset CSV is missing columns: {sorted(missing)}")
            for row_number, row in enumerate(reader, start=2):
                if any(
                    not str(row.get(field, "")).strip() for field in required_columns
                ):
                    raise ValueError(
                        f"dataset CSV row {row_number} has missing required values"
                    )
                try:
                    match_date = (
                        datetime.strptime(row["Date"], "%d/%m/%Y").date().isoformat()
                    )
                    home_goals = int(row["FTHG"])
                    away_goals = int(row["FTAG"])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"dataset CSV row {row_number} has invalid date/score"
                    ) from exc
                if home_goals < 0 or away_goals < 0:
                    raise ValueError(f"dataset CSV row {row_number} has negative goals")
                key = (
                    row["League"].strip().casefold(),
                    row["Season"].strip(),
                    match_date,
                    row["HomeTeam"].strip().casefold(),
                    row["AwayTeam"].strip().casefold(),
                )
                if key in seen_fixtures:
                    raise ValueError(
                        f"dataset CSV contains a duplicate fixture at row {row_number}"
                    )
                seen_fixtures.add(key)
                row_count += 1
    except csv.Error as exc:
        raise ValueError(f"dataset CSV cannot be parsed: {exc}") from exc

    if row_count != expected_rows:
        raise ValueError(
            f"dataset CSV has {row_count} rows; manifest expects {expected_rows}"
        )
    return {
        "dataset_sha256": expected_dataset_hash,
        "dataset_profile_sha256": expected_profile_hash,
        "dataset_rows": row_count,
        "dataset_size_bytes": len(dataset_payload),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze archived out-of-sample Quiniela prediction errors."
    )
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--results-json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dataset-csv", type=Path)
    parser.add_argument("--dataset-profile", type=Path)
    parser.add_argument("--min-segment-n", type=int, default=100)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    args = parser.parse_args()

    if (args.dataset_csv is None) != (args.dataset_profile is None):
        parser.error("--dataset-csv and --dataset-profile must be provided together")

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

        dataset_snapshot = None
        if args.dataset_csv is not None and args.dataset_profile is not None:
            dataset_snapshot = _validate_dataset_snapshot(
                manifest,
                args.dataset_csv,
                args.dataset_profile,
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
        if dataset_snapshot is not None:
            report["source"]["dataset_snapshot"] = dataset_snapshot
        serialized = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized + "\n", encoding="utf-8")
        print(
            "PREDICTION_DIAGNOSTICS_OK: "
            f"{len(rows)} fixtures, {len(manifest['model_modes'])} models, "
            f"{sum(row['market_eligible'] for row in rows)} market-eligible"
        )
        if dataset_snapshot is not None:
            print(
                "DATASET_SNAPSHOT_OK: "
                f"{dataset_snapshot['dataset_rows']} rows, "
                f"sha256={dataset_snapshot['dataset_sha256']}"
            )
    except (OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
