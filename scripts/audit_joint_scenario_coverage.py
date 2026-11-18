"""Audit realized 14-match joint scenarios against direct Quiniela systems."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SIGNS = ("1", "X", "2")
MODE_KEYS = ("dc", "ml", "ensemble_dc_ml")
PROBABILITY_SUM_TOLERANCE = 1e-6


def _validate_probability_vector(vector: Any, index: int) -> dict[str, float]:
    if not isinstance(vector, dict) or set(vector) != set(SIGNS):
        raise ValueError(f"match {index}: probabilities must have exactly 1/X/2 keys")
    values: dict[str, float] = {}
    for sign in SIGNS:
        raw = vector[sign]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError(f"match {index}: probability for {sign} must be numeric")
        value = float(raw)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"match {index}: probability for {sign} is invalid")
        values[sign] = value
    total = math.fsum(values.values())
    if not math.isclose(
        total, 1.0, rel_tol=0.0, abs_tol=PROBABILITY_SUM_TOLERANCE
    ):
        raise ValueError(f"match {index}: probability vector sum is {total:.8g}")
    return values


def _validate_scenario(scenario: Any, name: str) -> tuple[str, ...]:
    if not isinstance(scenario, list) or len(scenario) != 14:
        raise ValueError(f"{name} must contain exactly 14 signs")
    if any(not isinstance(sign, str) or sign not in SIGNS for sign in scenario):
        raise ValueError(f"{name} contains an invalid 1/X/2 sign")
    return tuple(scenario)


def _validate_direct_system(columns: Any) -> list[tuple[str, ...]]:
    if not isinstance(columns, list) or not columns:
        raise ValueError("direct columns must be a non-empty list")
    parsed = [
        _validate_scenario(column, f"column {i}")
        for i, column in enumerate(columns, 1)
    ]
    if len(set(parsed)) != len(parsed):
        raise ValueError("direct system contains duplicate columns")
    selected = [{column[i] for column in parsed} for i in range(14)]
    widths = [len(signs) for signs in selected]
    if any(width not in (1, 2, 3) for width in widths):
        raise ValueError("direct system has an invalid sign width")
    expected_count = math.prod(widths)
    if expected_count != len(parsed):
        raise ValueError("direct system is not a complete Cartesian multiple")
    if any(
        sign not in selected[position]
        for column in parsed
        for position, sign in enumerate(column)
    ):
        raise ValueError("direct system contains signs outside its selected sets")
    return parsed


def _scenario_probability(
    vectors: list[dict[str, float]], scenario: tuple[str, ...]
) -> float:
    return math.prod(vectors[index][sign] for index, sign in enumerate(scenario))


def audit_report(
    report: dict[str, Any], source_sha256: str | None = None
) -> dict[str, Any]:
    coupons = report.get("coupons")
    if not isinstance(coupons, list) or not coupons:
        raise ValueError("backtest report must contain a non-empty coupons list")
    per_model: dict[str, list[dict[str, Any]]] = {mode: [] for mode in MODE_KEYS}

    for coupon_index, coupon in enumerate(coupons, 1):
        if not isinstance(coupon, dict):
            raise TypeError(f"coupon {coupon_index} must be an object")
        coupon_id = coupon.get("coupon_id")
        if not isinstance(coupon_id, str) or not coupon_id:
            raise ValueError(f"coupon {coupon_index} has no coupon_id")
        actual = _validate_scenario(
            coupon.get("actual_main_results"), f"{coupon_id} actual results"
        )
        models = coupon.get("models")
        if not isinstance(models, dict):
            raise TypeError(f"{coupon_id}: models must be an object")

        for mode in MODE_KEYS:
            model = models.get(mode)
            if not isinstance(model, dict) or model.get("status") != "success":
                raise ValueError(
                    f"{coupon_id} {mode}: model evaluation is not successful"
                )
            vectors_raw = model.get("probabilities")
            if not isinstance(vectors_raw, list) or len(vectors_raw) != 14:
                raise ValueError(f"{coupon_id} {mode}: expected 14 probability vectors")
            vectors = [
                _validate_probability_vector(vector, i)
                for i, vector in enumerate(vectors_raw, 1)
            ]
            columns = _validate_direct_system(model.get("columns"))
            column_mass = math.fsum(
                _scenario_probability(vectors, column) for column in columns
            )
            if (
                not math.isfinite(column_mass)
                or column_mass < 0.0
                or column_mass > 1.0 + 2e-5
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: calculated direct-system mass is invalid"
                )

            saved_mass = model.get("independent_14_coverage_estimate")
            if isinstance(saved_mass, bool) or not isinstance(saved_mass, (int, float)):
                raise TypeError(
                    f"{coupon_id} {mode}: independent coverage estimate is not numeric"
                )
            saved_mass = float(saved_mass)
            if (
                not math.isfinite(saved_mass)
                or not 0.0 <= saved_mass <= 1.0 + 2e-5
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: independent coverage estimate is invalid"
                )
            if not math.isclose(
                column_mass, saved_mass, rel_tol=1e-6, abs_tol=1e-12
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: expanded-column probability mass "
                    f"{column_mass:.12g} does not match stored independent estimate "
                    f"{saved_mass:.12g}"
                )

            covered = actual in set(columns)
            actual_scenario_probability = _scenario_probability(vectors, actual)
            per_model[mode].append(
                {
                    "coupon_id": coupon_id,
                    "ticket_column_count": len(columns),
                    "independent_coverage_estimate": column_mass,
                    "actual_scenario_covered": covered,
                    "actual_scenario_probability_independence": (
                        actual_scenario_probability
                    ),
                }
            )

    summaries: dict[str, dict[str, Any]] = {}
    for mode, rows in per_model.items():
        estimates = [row["independent_coverage_estimate"] for row in rows]
        observed = sum(row["actual_scenario_covered"] for row in rows)
        expected = math.fsum(estimates)
        zero_probability = math.prod(1.0 - estimate for estimate in estimates)
        summaries[mode] = {
            "coupon_count": len(rows),
            "observed_covered_coupons": observed,
            "observed_coverage_rate": observed / len(rows),
            "expected_covered_coupons_under_independence": expected,
            "mean_independent_coverage_estimate": expected / len(rows),
            "probability_zero_covered_under_independent_coupon_assumption": (
                zero_probability
            ),
            "coverage_basis": "sum_of_probabilities_of_expanded_direct_columns",
        }

    return {
        "schema_version": 1,
        "coupon_backtest_schema_version": report.get("schema_version"),
        "coupon_count": len(coupons),
        "source_sha256": source_sha256,
        "scope": (
            "selected_historical_coupons; descriptive mechanics audit, "
            "not a representative benchmark"
        ),
        "independence_assumptions": [
            (
                "match outcomes are treated as independent within a coupon "
                "when calculating coverage mass"
            ),
            (
                "coupon coverage events are treated as independent when calculating "
                "the probability of zero covered coupons"
            ),
        ],
        "models": summaries,
        "rows": per_model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path, help="coupon-backtest JSON artifact"
    )
    parser.add_argument("--output", type=Path, help="optional JSON output file")
    args = parser.parse_args()
    raw = args.input.read_bytes()
    report = json.loads(raw)
    audited = audit_report(report, hashlib.sha256(raw).hexdigest())
    encoded = json.dumps(audited, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
