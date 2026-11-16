from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from kini_engine.coupon_identity import canonicalize_coupon
from kini_engine.core import SIGNS
from kini_engine.coupons import evaluate_coupon_batch, read_coupon_jsonl
from kini_engine.dataio import load_matches_csv, validate_matches


OFFICIAL_QUINIELA_BET_PRICE_EUR = 0.75
MINIMUM_QUINIELA_BETS = 2
MAXIMUM_QUINIELA_BETS = 31_104


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


def validate_coupon_backtest_acceptance(
    result: dict[str, object],
    expected_coupon_ids: list[str],
    *,
    budget: int,
    min_history_matches: int,
) -> None:
    """Fail closed unless every coupon, model and direct-ticket expansion is auditable."""
    if result.get("schema_version") != 2:
        raise ValueError("unsupported coupon backtest result schema")
    if not expected_coupon_ids or len(set(expected_coupon_ids)) != len(
        expected_coupon_ids
    ):
        raise ValueError("expected coupon IDs must be non-empty and unique")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError("coupon budget must be a positive integer")
    if (
        isinstance(min_history_matches, bool)
        or not isinstance(min_history_matches, int)
        or min_history_matches < 1
    ):
        raise ValueError("minimum history count must be a positive integer")

    coupons = result.get("coupons")
    if not isinstance(coupons, list):
        raise TypeError("coupon backtest result has no coupon list")
    actual_ids = [
        item.get("coupon_id") if isinstance(item, dict) else None for item in coupons
    ]
    if actual_ids != expected_coupon_ids:
        raise ValueError(
            "coupon result IDs/order do not match the verified input archive: "
            f"expected={expected_coupon_ids!r}, actual={actual_ids!r}"
        )

    summary = result.get("summary")
    config = result.get("config")
    if not isinstance(summary, dict) or not isinstance(config, dict):
        raise TypeError("coupon backtest summary/config is missing")
    if summary.get("coupon_count") != len(expected_coupon_ids):
        raise ValueError("coupon summary count does not match the verified archive")
    if config.get("budget_columns") != budget:
        raise ValueError("coupon result budget differs from the requested budget")
    if config.get("min_history_matches") != min_history_matches:
        raise ValueError(
            "coupon result minimum history differs from the requested value"
        )

    modes = ("dc", "ml", "ensemble_dc_ml")
    model_summary = summary.get("models")
    if not isinstance(model_summary, dict):
        raise TypeError("coupon model summary is missing")
    for mode in modes:
        aggregate = model_summary.get(mode)
        if not isinstance(aggregate, dict):
            raise TypeError(f"{mode}: aggregate model summary is missing")
        evaluated = aggregate.get("evaluated_coupons")
        failed = aggregate.get("failed_coupons")
        if evaluated != len(expected_coupon_ids) or failed != 0:
            raise ValueError(
                f"{mode}: evaluated {evaluated!r}/{len(expected_coupon_ids)} coupons "
                f"with {failed!r} failures"
            )

    categories = {"0", "1", "2", "M"}
    for coupon in coupons:
        coupon_id = coupon["coupon_id"]
        if coupon.get("status") == "failed":
            raise ValueError(
                f"{coupon_id}: coupon evaluation failed: {coupon.get('error')}"
            )
        if coupon.get("official_main_matches_verified") is not True:
            raise ValueError(
                f"{coupon_id}: 14 main results are not verified against SELAE"
            )
        if coupon.get("official_pleno_verified") is not True:
            raise ValueError(f"{coupon_id}: Pleno al 15 is not verified against SELAE")
        if coupon.get("fixture_reconciliation_count") != 15:
            raise ValueError(
                f"{coupon_id}: all 15 fixtures are not canonically reconciled"
            )
        reconciliation = coupon.get("fixture_reconciliation")
        if (
            not isinstance(reconciliation, list)
            or len(reconciliation) != 15
            or any(not isinstance(item, dict) for item in reconciliation)
            or [item.get("number") for item in reconciliation] != list(range(1, 16))
        ):
            raise ValueError(
                f"{coupon_id}: canonical fixture reconciliation evidence is incomplete"
            )

        actual_main_results = coupon.get("actual_main_results")
        if (
            not isinstance(actual_main_results, list)
            or len(actual_main_results) != 14
            or any(
                not isinstance(sign, str) or sign not in SIGNS
                for sign in actual_main_results
            )
        ):
            raise ValueError(
                f"{coupon_id}: 14 actual main results are missing or invalid"
            )
        for index, (sign, evidence) in enumerate(
            zip(actual_main_results, reconciliation[:14], strict=True), start=1
        ):
            if evidence.get("result") != sign:
                raise ValueError(
                    f"{coupon_id}: actual result {index} conflicts with reconciliation"
                )
            home_goals = evidence.get("home_goals")
            away_goals = evidence.get("away_goals")
            if (
                isinstance(home_goals, bool)
                or isinstance(away_goals, bool)
                or not isinstance(home_goals, int)
                or not isinstance(away_goals, int)
                or home_goals < 0
                or away_goals < 0
            ):
                raise ValueError(
                    f"{coupon_id}: fixture {index} has invalid reconciled scores"
                )
            expected_sign = (
                "1"
                if home_goals > away_goals
                else ("2" if away_goals > home_goals else "X")
            )
            if expected_sign != sign:
                raise ValueError(
                    f"{coupon_id}: actual result {index} conflicts with reconciled score"
                )

        actual_pleno_categories = coupon.get("actual_pleno_categories")
        actual_pleno_home = (
            actual_pleno_categories.get("home")
            if isinstance(actual_pleno_categories, dict)
            else None
        )
        actual_pleno_away = (
            actual_pleno_categories.get("away")
            if isinstance(actual_pleno_categories, dict)
            else None
        )
        if (
            not isinstance(actual_pleno_categories, dict)
            or set(actual_pleno_categories) != {"home", "away"}
            or not isinstance(actual_pleno_home, str)
            or actual_pleno_home not in categories
            or not isinstance(actual_pleno_away, str)
            or actual_pleno_away not in categories
            or reconciliation[14].get("pleno_home_category") != actual_pleno_home
            or reconciliation[14].get("pleno_away_category") != actual_pleno_away
        ):
            raise ValueError(
                f"{coupon_id}: actual Pleno categories conflict with fixture reconciliation"
            )

        try:
            first_kickoff = datetime.fromisoformat(coupon["first_kickoff_at"])
            cutoff = date.fromisoformat(coupon["training_cutoff_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{coupon_id}: invalid common-cutoff metadata") from exc
        if first_kickoff.tzinfo is None or first_kickoff.utcoffset() is None:
            raise ValueError(f"{coupon_id}: first kickoff must be timezone-aware")
        if cutoff != first_kickoff.date() - timedelta(days=1):
            raise ValueError(
                f"{coupon_id}: training cutoff is not the previous local calendar day"
            )

        training_count = coupon.get("training_match_count")
        fit_count = coupon.get("model_fit_match_count")
        if (
            isinstance(training_count, bool)
            or not isinstance(training_count, int)
            or training_count < min_history_matches
            or fit_count != training_count
        ):
            raise ValueError(
                f"{coupon_id}: common training history is below minimum or inconsistent"
            )

        pleno = coupon.get("pleno_prediction")
        if not isinstance(pleno, dict) or pleno.get("model") != "dixon_coles":
            raise ValueError(f"{coupon_id}: Pleno prediction provenance is missing")
        if pleno.get("selection_method") != "max_aggregated_category_pair_probability":
            raise ValueError(f"{coupon_id}: Pleno selection method is not explicit")
        if (
            not isinstance(pleno.get("home_category"), str)
            or pleno.get("home_category") not in categories
            or not isinstance(pleno.get("away_category"), str)
            or pleno.get("away_category") not in categories
        ):
            raise ValueError(f"{coupon_id}: Pleno category is invalid")
        mass = pleno.get("probability_mass")
        if (
            isinstance(mass, bool)
            or not isinstance(mass, (int, float))
            or not math.isfinite(mass)
            or not 0.0 < mass <= 1.0
        ):
            raise ValueError(f"{coupon_id}: Pleno probability mass is invalid")
        if pleno.get("training_match_count") != training_count:
            raise ValueError(f"{coupon_id}: Pleno training provenance is inconsistent")

        model_results = coupon.get("models")
        if not isinstance(model_results, dict):
            raise TypeError(f"{coupon_id}: model results are missing")
        for mode in modes:
            model = model_results.get(mode)
            if not isinstance(model, dict) or model.get("status") != "success":
                raise ValueError(
                    f"{coupon_id} {mode}: model did not complete successfully"
                )
            if model.get("n_predictions") != 14:
                raise ValueError(f"{coupon_id} {mode}: expected 14 predictions")
            vectors = model.get("probabilities")
            if not isinstance(vectors, list) or len(vectors) != 14:
                raise ValueError(
                    f"{coupon_id} {mode}: probability vectors are incomplete"
                )
            for index, vector in enumerate(vectors, start=1):
                if not isinstance(vector, dict) or set(vector) != set(SIGNS):
                    raise ValueError(
                        f"{coupon_id} {mode} fixture {index}: malformed probability vector"
                    )
                values = [vector[sign] for sign in SIGNS]
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not 0.0 <= value <= 1.0
                    for value in values
                ) or not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-6):
                    raise ValueError(
                        f"{coupon_id} {mode} fixture {index}: invalid 1/X/2 probabilities"
                    )

            column_count = model.get("column_count")
            total_bets = model.get("total_bets")
            if (
                isinstance(column_count, bool)
                or not isinstance(column_count, int)
                or not 1 <= column_count <= budget
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: column count exceeds the requested budget"
                )
            if (
                isinstance(total_bets, bool)
                or not isinstance(total_bets, int)
                or not MINIMUM_QUINIELA_BETS <= total_bets <= MAXIMUM_QUINIELA_BETS
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: total bets violate SELAE's minimum or maximum"
                )

            double_count = model.get("double_count")
            triple_count = model.get("triple_count")
            for field, count in (
                ("double_count", double_count),
                ("triple_count", triple_count),
            ):
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or not 0 <= count <= 14
                ):
                    raise TypeError(f"{coupon_id} {mode}: invalid {field}")
            if double_count + triple_count > 14:
                raise ValueError(f"{coupon_id} {mode}: a fixture is double-counted")

            raw_columns = model.get("columns")
            if not isinstance(raw_columns, list) or len(raw_columns) != column_count:
                raise ValueError(
                    f"{coupon_id} {mode}: persisted direct columns do not match column_count"
                )
            columns = []
            for column_index, raw_column in enumerate(raw_columns, start=1):
                if (
                    not isinstance(raw_column, list)
                    or len(raw_column) != 14
                    or any(
                        not isinstance(sign, str) or sign not in SIGNS
                        for sign in raw_column
                    )
                ):
                    raise ValueError(
                        f"{coupon_id} {mode}: direct column {column_index} must contain exactly 14 valid signs"
                    )
                columns.append(tuple(raw_column))
            if len(set(columns)) != column_count:
                raise ValueError(f"{coupon_id} {mode}: duplicate direct columns")

            selected_by_fixture = [
                {column[index] for column in columns} for index in range(14)
            ]
            widths = [len(selected) for selected in selected_by_fixture]
            if any(width not in (1, 2, 3) for width in widths):
                raise ValueError(
                    f"{coupon_id} {mode}: every fixture must select one, two or three signs"
                )
            observed_doubles = sum(width == 2 for width in widths)
            observed_triples = sum(width == 3 for width in widths)
            expected_columns = (2**double_count) * (3**triple_count)
            if (
                observed_doubles != double_count
                or observed_triples != triple_count
                or column_count != expected_columns
                or column_count != math.prod(widths)
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: direct columns do not match the 2^d * 3^t multiple-system structure"
                )

            home_categories = model.get("pleno15_home_categories")
            away_categories = model.get("pleno15_away_categories")
            for field, values in (
                ("pleno15_home_categories", home_categories),
                ("pleno15_away_categories", away_categories),
            ):
                if (
                    not isinstance(values, list)
                    or not values
                    or any(
                        not isinstance(category, str) or category not in categories
                        for category in values
                    )
                    or len(set(values)) != len(values)
                ):
                    raise ValueError(f"{coupon_id} {mode}: invalid {field}")
            if (
                home_categories != [pleno["home_category"]]
                or away_categories != [pleno["away_category"]]
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: coupon backtest requires the single predicted Pleno pair"
                )
            pleno_multiplier = model.get("pleno15_multiplier")
            expected_multiplier = len(home_categories) * len(away_categories)
            if (
                isinstance(pleno_multiplier, bool)
                or not isinstance(pleno_multiplier, int)
                or pleno_multiplier != expected_multiplier
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: Pleno multiplier conflicts with selected categories"
                )
            minimum_total_bets = model.get("minimum_total_bets")
            maximum_total_bets = model.get("maximum_authorized_total_bets")
            if (
                minimum_total_bets != MINIMUM_QUINIELA_BETS
                or maximum_total_bets != MAXIMUM_QUINIELA_BETS
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: ticket minimum/maximum metadata differs from SELAE rules"
                )
            if total_bets < minimum_total_bets or total_bets > maximum_total_bets:
                raise ValueError(
                    f"{coupon_id} {mode}: total bets violate the recorded ticket bounds"
                )
            if total_bets != column_count * pleno_multiplier:
                raise ValueError(
                    f"{coupon_id} {mode}: total bets do not equal columns times Pleno multiplier"
                )

            price = model.get("price_per_bet_eur")
            cost = model.get("cost_eur")
            if (
                isinstance(price, bool)
                or not isinstance(price, (int, float))
                or not math.isfinite(price)
                or price <= 0
            ):
                raise ValueError(f"{coupon_id} {mode}: invalid price per bet")
            if (
                isinstance(cost, bool)
                or not isinstance(cost, (int, float))
                or not math.isfinite(cost)
                or cost <= 0
            ):
                raise ValueError(f"{coupon_id} {mode}: invalid ticket cost")
            if not math.isclose(
                price, OFFICIAL_QUINIELA_BET_PRICE_EUR, rel_tol=0.0, abs_tol=1e-12
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: price per bet differs from current SELAE price"
                )
            expected_cost = round(total_bets * price, 2)
            if not math.isclose(cost, expected_cost, rel_tol=0.0, abs_tol=0.005):
                raise ValueError(
                    f"{coupon_id} {mode}: ticket cost does not match total bets and price"
                )

            for field in ("single_sign_hits", "best_column_hits"):
                hits = model.get(field)
                if (
                    isinstance(hits, bool)
                    or not isinstance(hits, int)
                    or not 0 <= hits <= 14
                ):
                    raise ValueError(f"{coupon_id} {mode}: invalid {field}")
            for field in ("covered_14", "pleno_hit", "full_coupon_covered"):
                if not isinstance(model.get(field), bool):
                    raise TypeError(f"{coupon_id} {mode}: invalid {field}")

            actual_vector = tuple(actual_main_results)
            realized_coverage = actual_vector in set(columns)
            if model["covered_14"] != realized_coverage:
                raise ValueError(
                    f"{coupon_id} {mode}: covered_14 conflicts with persisted columns"
                )
            expected_best_hits = max(
                sum(sign == actual_vector[index] for index, sign in enumerate(column))
                for column in columns
            )
            if model["best_column_hits"] != expected_best_hits:
                raise ValueError(
                    f"{coupon_id} {mode}: best_column_hits conflicts with persisted columns"
                )
            expected_single_hits = sum(
                max(SIGNS, key=vectors[index].__getitem__) == actual_vector[index]
                for index in range(14)
            )
            if model["single_sign_hits"] != expected_single_hits:
                raise ValueError(
                    f"{coupon_id} {mode}: single_sign_hits conflicts with probabilities"
                )

            if (
                model.get("pleno_model") != pleno.get("model")
                or model.get("pleno_selected_home_category")
                != pleno.get("home_category")
                or model.get("pleno_selected_away_category")
                != pleno.get("away_category")
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: model Pleno selection conflicts with coupon provenance"
                )
            selected_mass = model.get("pleno_selected_probability_mass")
            if (
                isinstance(selected_mass, bool)
                or not isinstance(selected_mass, (int, float))
                or not math.isfinite(selected_mass)
                or not math.isclose(selected_mass, mass, rel_tol=0.0, abs_tol=1e-12)
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: selected Pleno probability mass is inconsistent"
                )
            if (
                pleno["home_category"] not in home_categories
                or pleno["away_category"] not in away_categories
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: selected Pleno categories are absent from the ticket"
                )
            expected_pleno_hit = (
                actual_pleno_home == pleno["home_category"]
                and actual_pleno_away == pleno["away_category"]
            )
            if model["pleno_hit"] != expected_pleno_hit:
                raise ValueError(
                    f"{coupon_id} {mode}: pleno_hit conflicts with actual and predicted categories"
                )
            if model["full_coupon_covered"] != (
                realized_coverage and expected_pleno_hit
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: full-coupon coverage is inconsistent"
                )

            coverage = model.get("independent_14_coverage_estimate")
            if (
                isinstance(coverage, bool)
                or not isinstance(coverage, (int, float))
                or not math.isfinite(coverage)
                or not 0.0 <= coverage <= 1.0
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: invalid independent coverage estimate"
                )
            expected_independent_coverage = math.prod(
                sum(vectors[index][sign] for sign in selected_by_fixture[index])
                for index in range(14)
            )
            if not math.isclose(
                coverage, expected_independent_coverage, rel_tol=1e-9, abs_tol=1e-12
            ):
                raise ValueError(
                    f"{coupon_id} {mode}: independent coverage estimate conflicts with probabilities and persisted columns"
                )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate coupons from one common pre-first-kickoff cutoff."
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
            coupon_result["fixture_reconciliation_count"] = len(
                reconciliations[coupon_id]
            )
    result["source"] = {
        "historical_dataset": str(args.historical_csv),
        "historical_dataset_sha256": hashlib.sha256(
            args.historical_csv.read_bytes()
        ).hexdigest(),
        "historical_dataset_rows": len(matches),
        "coupon_archive": str(args.coupons_jsonl),
        "coupon_archive_sha256": hashlib.sha256(
            args.coupons_jsonl.read_bytes()
        ).hexdigest(),
        "coupon_archive_manifest": coupon_manifest,
        "code_revision": os.getenv("KINI_CODE_REVISION")
        or os.getenv("GITHUB_SHA")
        or "unknown",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "python_version": platform.python_version(),
    }
    try:
        validate_coupon_backtest_acceptance(
            result,
            [coupon["coupon_id"] for coupon in coupons],
            budget=args.budget,
            min_history_matches=args.min_history,
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"COUPON_BACKTEST_REJECTED: {exc}") from exc
    atomic_json(args.output, result)
    print(
        f"COUPON_BACKTEST_OK: {len(coupons)} coupons, "
        f"{len(coupons) * 15} fixtures, budget={args.budget} columns"
    )


if __name__ == "__main__":
    main()
