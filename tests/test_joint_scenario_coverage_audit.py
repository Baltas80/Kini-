from itertools import product

import pytest

from scripts.audit_joint_scenario_coverage import audit_report


def sample_report():
    vectors = [{"1": 0.8, "X": 0.15, "2": 0.05} for _ in range(14)]
    vectors[0] = {"1": 0.55, "X": 0.35, "2": 0.10}
    vectors[1] = {"1": 0.55, "X": 0.35, "2": 0.10}
    selected = [{"1", "X"}, {"1", "X"}] + [{"1"} for _ in range(12)]
    columns = [list(column) for column in product(*[sorted(s) for s in selected])]
    mass = 0.9 * 0.9 * (0.8**12)
    actual = ["1", "X"] + ["1"] * 12
    model = {
        "status": "success",
        "probabilities": vectors,
        "columns": columns,
        "independent_14_coverage_estimate": mass,
    }
    return {
        "schema_version": 3,
        "coupons": [
            {
                "coupon_id": "sample",
                "actual_main_results": actual,
                "models": {
                    mode: model for mode in ("dc", "ml", "ensemble_dc_ml")
                },
            }
        ],
    }, mass


def test_audit_matches_exact_expanded_column_probability_mass_and_realized_scenario():
    report, expected_mass = sample_report()
    audited = audit_report(report)

    for model in audited["models"].values():
        assert model["coupon_count"] == 1
        assert model["observed_covered_coupons"] == 1
        assert model["expected_covered_coupons_under_independence"] == pytest.approx(
            expected_mass
        )
        assert model[
            "probability_zero_covered_under_independent_coupon_assumption"
        ] == pytest.approx(1 - expected_mass)


def test_audit_rejects_non_cartesian_or_duplicate_direct_system():
    report, _ = sample_report()
    columns = report["coupons"][0]["models"]["dc"]["columns"]
    columns.pop()
    with pytest.raises(ValueError, match="complete Cartesian multiple"):
        audit_report(report)

    report, _ = sample_report()
    columns = report["coupons"][0]["models"]["dc"]["columns"]
    columns.append(columns[0])
    with pytest.raises(ValueError, match="duplicate columns"):
        audit_report(report)


def test_audit_rejects_bad_probability_contract():
    report, _ = sample_report()
    report["coupons"][0]["models"]["dc"]["probabilities"][0]["1"] = 0.90
    with pytest.raises(ValueError, match="sum is"):
        audit_report(report)


def test_audit_rejects_stored_estimate_drift():
    report, _ = sample_report()
    report["coupons"][0]["models"]["dc"]["independent_14_coverage_estimate"] += 0.01
    with pytest.raises(ValueError, match="does not match stored independent estimate"):
        audit_report(report)
