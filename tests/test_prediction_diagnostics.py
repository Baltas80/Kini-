from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from kini_engine.diagnostics import analyze_prediction_rows
from kini_engine.ledger import read_prediction_ledger, write_prediction_ledger


def _manifest(forecast_count: int = 3) -> dict[str, object]:
    return {
        "schema_version": 1,
        "code_revision": "a" * 40,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_sha256": "b" * 64,
        "forecast_count": forecast_count,
        "forecast_start_date": "2025-01-02",
        "forecast_end_date": "2025-01-04",
        "model_modes": ["dc", "ml"],
        "run_config": {},
    }


def _row(index: int, actual: str) -> dict[str, object]:
    vectors = {
        "dc": {"1": 0.6, "X": 0.25, "2": 0.15},
        "ml": {"1": 0.2, "X": 0.55, "2": 0.25},
    }
    signs = {"dc": "1", "ml": "X"}
    if index == 2:
        vectors = {
            "dc": {"1": 0.4, "X": 0.35, "2": 0.25},
            "ml": {"1": 0.3, "X": 0.45, "2": 0.25},
        }
        signs = {"dc": "1", "ml": "X"}
    elif index == 3:
        vectors = {
            "dc": {"1": 0.3, "X": 0.25, "2": 0.45},
            "ml": {"1": 0.2, "X": 0.25, "2": 0.55},
        }
        signs = {"dc": "2", "ml": "2"}
    market = (
        {"1": 0.55, "X": 0.25, "2": 0.20}
        if index != 2
        else None
    )
    return {
        "forecast_index": index,
        "fixture_id": f"{index:064x}",
        "forecast_as_of_date": f"2025-01-0{index + 1}",
        "training_cutoff_date": f"2025-01-0{index}",
        "model_fit_cutoff_date": f"2025-01-0{index}",
        "training_match_count": 20 + index,
        "model_fit_match_count": 20 + index,
        "home": f"Home {index}",
        "away": f"Away {index}",
        "actual_result": actual,
        "competition": "segunda",
        "season_label": "2024/25",
        "model_probabilities": vectors,
        "model_signs": signs,
        "market_eligible": market is not None,
        "market_probabilities": market,
        "lae_eligible": False,
        "lae_probabilities": None,
        "bet365_probabilities": None,
    }


def test_read_prediction_ledger_checks_hash_and_manifest(tmp_path):
    target = tmp_path / "ledger.jsonl"
    rows = [_row(1, "1"), _row(2, "X"), _row(3, "2")]
    write_prediction_ledger(target, _manifest(), rows)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()

    manifest, loaded = read_prediction_ledger(target, expected_sha256=digest)

    assert manifest["forecast_count"] == 3
    assert len(loaded) == 3
    assert loaded[1]["actual_result"] == "X"
    with pytest.raises(ValueError, match="SHA-256"):
        read_prediction_ledger(target, expected_sha256="c" * 64)


def test_read_prediction_ledger_rejects_blank_lines_and_wrong_record_types(tmp_path):
    target = tmp_path / "ledger.jsonl"
    target.write_text('{"record_type":"run_manifest"}\n\n', encoding="utf-8")

    with pytest.raises(ValueError, match="blank JSONL"):
        read_prediction_ledger(target)


def test_draw_diagnostics_distinguish_top_sign_from_probability(tmp_path):
    target = tmp_path / "ledger.jsonl"
    rows = [_row(1, "1"), _row(2, "X"), _row(3, "2")]
    write_prediction_ledger(target, _manifest(), rows)
    manifest, loaded = read_prediction_ledger(target)

    report = analyze_prediction_rows(manifest, loaded, min_segment_n=2)

    dc_x = report["overall"]["dc"]["classwise"]["X"]
    ml_x = report["overall"]["ml"]["classwise"]["X"]
    assert report["overall"]["dc"]["n"] == 3
    assert dc_x["actual_count"] == 1
    assert dc_x["predicted_count"] == 0
    assert dc_x["recall"] == 0.0
    assert dc_x["mean_probability"] == pytest.approx((0.25 + 0.35 + 0.25) / 3)
    assert ml_x["actual_count"] == 1
    assert ml_x["predicted_count"] == 2
    assert ml_x["true_positive"] == 1
    assert ml_x["precision"] == pytest.approx(0.5)
    assert ml_x["recall"] == 1.0
    assert report["overall"]["dc"]["top_two_candidate_coverage"]["empirical_coverage"] == 1.0
    assert report["overall"]["dc"]["top_two_candidate_coverage"]["draw_coverage"] == 1.0
    assert report["market_common_sample"]["n"] == 2
    assert len(report["segments"]["groups"]) == 1
    assert report["segments"]["groups"][0]["n"] == 3


def test_diagnostics_reject_invalid_segment_threshold():
    with pytest.raises(ValueError, match="min_segment_n"):
        analyze_prediction_rows(_manifest(), [_row(1, "1")], min_segment_n=0)
