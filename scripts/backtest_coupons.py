from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from kini_engine.coupon_identity import canonicalize_coupon
from kini_engine.coupons import evaluate_coupon_batch, read_coupon_jsonl
from kini_engine.dataio import load_matches_csv, validate_matches


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run coupon-level evaluation from one common pre-first-kickoff cutoff."
    )
    parser.add_argument("historical_csv", type=Path)
    parser.add_argument("coupons_jsonl", type=Path)
    parser.add_argument("--budget", type=int, default=8)
    parser.add_argument("--min-history", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite existing output: {args.output}")

    matches = load_matches_csv(args.historical_csv)
    validate_matches(matches)
    coupon_manifest, coupons = read_coupon_jsonl(args.coupons_jsonl)
    resolved_coupons = []
    reconciliations = {}
    for coupon in coupons:
        resolved, reconciliation = canonicalize_coupon(coupon, matches)
        resolved_coupons.append(resolved)
        reconciliations[coupon["coupon_id"]] = reconciliation
    result = evaluate_coupon_batch(
        resolved_coupons,
        matches,
        budget=args.budget,
        min_history_matches=args.min_history,
    )
    for coupon_result in result["coupons"]:
        coupon_id = coupon_result.get("coupon_id")
        if coupon_id in reconciliations and coupon_result.get("status") != "failed":
            coupon_result["fixture_reconciliation"] = reconciliations[coupon_id]
            coupon_result["fixture_reconciliation_count"] = len(reconciliations[coupon_id])
    result["source"] = {
        "historical_dataset": str(args.historical_csv),
        "historical_dataset_sha256": hashlib.sha256(args.historical_csv.read_bytes()).hexdigest(),
        "historical_dataset_rows": len(matches),
        "coupon_archive": str(args.coupons_jsonl),
        "coupon_archive_sha256": hashlib.sha256(args.coupons_jsonl.read_bytes()).hexdigest(),
        "coupon_archive_manifest": coupon_manifest,
        "code_revision": os.getenv("KINI_CODE_REVISION") or os.getenv("GITHUB_SHA") or "unknown",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
    }
    dc_count = result["summary"]["models"]["dc"]["evaluated_coupons"]
    if dc_count != len(coupons):
        raise SystemExit(
            f"COUPON_BACKTEST_REJECTED: Dixon-Coles evaluated {dc_count}/{len(coupons)} coupons"
        )
    atomic_json(args.output, result)
    print(
        f"COUPON_BACKTEST_OK: {len(coupons)} coupons, "
        f"{len(coupons) * 15} fixtures, budget={args.budget} columns"
    )


if __name__ == "__main__":
    main()
