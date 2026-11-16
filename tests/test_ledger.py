from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from kini_engine.ledger import write_prediction_ledger


def _manifest(forecast_count: int = 1) -> dict[str, object]:
    return {
        "schema_version": 1,
        "code_revision": "a" * 40,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_sha256": "b" * 64,
        "forecast_count": forecast_count,
        "model_modes": ["dc"],
        "run_config": {"min_train_matches": 12},
    }


def _forecast_row() -> dict[str, object]:
    return {
        "forecast_index": 1,
        "fixture_id": "c" * 64,
        "forecast_as_of_date": "2025-01-02",
        "training_cutoff_date": "2025-01-01",
        "model_fit_cutoff_date": "2025-01-01",
        "training_match_count": 12,
        "model_fit_match_count": 12,
        "home": "Home",
        "away": "Away",
        "actual_result": "1",
        "model_probabilities": {"dc": {"1": 0.5, "X": 0.3, "2": 0.2}},
        "market_eligible": False,
        "market_probabilities": None,
        "lae_eligible": False,
        "lae_probabilities": None,
        "bet365_probabilities": None,
    }


def test_write_prediction_ledger_is_jsonl_and_refuses_overwrite(tmp_path):
    target = tmp_path / "run" / "prediction-ledger.jsonl"
    row = _forecast_row()

    count = write_prediction_ledger(target, _manifest(), [row])

    assert count == 1
    records = [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    assert records[0]["record_type"] == "run_manifest"
    assert records[1]["record_type"] == "forecast"
    assert records[1]["fixture_id"] == row["fixture_id"]
    with pytest.raises(FileExistsError):
        write_prediction_ledger(target, _manifest(), [row])


def test_prediction_ledger_rejects_non_prior_training_cutoff(tmp_path):
    row = _forecast_row()
    row["training_cutoff_date"] = "2025-01-02"

    with pytest.raises(ValueError, match="training_cutoff_date must precede"):
        write_prediction_ledger(tmp_path / "ledger.jsonl", _manifest(), [row])


def test_prediction_ledger_rejects_invalid_probability_vector(tmp_path):
    row = _forecast_row()
    row["model_probabilities"] = {"dc": {"1": 0.5, "X": 0.3, "2": 0.3}}

    with pytest.raises(ValueError, match="invalid probability vector"):
        write_prediction_ledger(tmp_path / "ledger.jsonl", _manifest(), [row])


def test_prediction_ledger_rejects_duplicate_fixture_ids(tmp_path):
    first = _forecast_row()
    second = {**_forecast_row(), "forecast_index": 2}

    with pytest.raises(ValueError, match="duplicate fixture_id"):
        write_prediction_ledger(
            tmp_path / "ledger.jsonl",
            _manifest(forecast_count=2),
            [first, second],
        )
