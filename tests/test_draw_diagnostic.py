from __future__ import annotations

from datetime import date, timedelta
import hashlib

import pytest

from kini_engine.ledger import write_prediction_ledger
from scripts.analyze_draw_oos import (
    analyze,
    paired_block_bootstrap,
    validate_snapshot_alignment,
)

MODES = ("dc", "ensemble")


def _probabilities(px: float) -> dict[str, float]:
    return {"1": (1.0 - px) * 0.55, "X": px, "2": (1.0 - px) * 0.45}


def _fixture_row(index: int, snapshot: str, outcome: str = "X") -> dict:
    snapshot_date = date.fromisoformat(snapshot)
    fixture_date = snapshot_date + timedelta(days=1)
    probabilities = {"dc": _probabilities(0.30), "ensemble": _probabilities(0.28)}
    return {
        "fixture_id": hashlib.sha256(f"fixture-{index}".encode()).hexdigest(),
        "forecast_index": index,
        "forecast_as_of_date": snapshot,
        "fixture_date": fixture_date.isoformat(),
        "fixture_date_raw": fixture_date.isoformat(),
        "market_snapshot_date": snapshot,
        "training_cutoff_date": (snapshot_date - timedelta(days=1)).isoformat(),
        "model_fit_cutoff_date": (snapshot_date - timedelta(days=1)).isoformat(),
        "training_match_count": 300,
        "model_fit_match_count": 300,
        "model_fit_count_for_snapshot": 1,
        "training_history_sha256": hashlib.sha256(
            f"history-{snapshot}".encode()
        ).hexdigest(),
        "home": f"Home {index}",
        "away": f"Away {index}",
        "actual_result": outcome,
        "model_probabilities": probabilities,
        "model_signs": {mode: max(p, key=p.get) for mode, p in probabilities.items()},
        "market_eligible": True,
        "market_probabilities": _probabilities(0.32),
        "lae_eligible": False,
        "lae_probabilities": None,
        "bet365_probabilities": None,
        "competition": "la-liga",
        "season_label": "2025/26",
    }


def _ledger(tmp_path, rows):
    manifest = {
        "schema_version": 1,
        "dataset_sha256": "a" * 64,
        "code_revision": "test-revision",
        "generated_at_utc": "2026-11-18T12:00:00+00:00",
        "forecast_count": len(rows),
        "model_modes": list(MODES),
        "forecast_start_date": min(r["forecast_as_of_date"] for r in rows),
        "forecast_end_date": max(r["forecast_as_of_date"] for r in rows),
    }
    path = tmp_path / "snapshot-ledger.jsonl"
    write_prediction_ledger(path, manifest, rows)
    return manifest, path


def test_snapshot_alignment_accepts_only_pre_snapshot_training(tmp_path):
    rows = [
        _fixture_row(1, "2026-01-09"),
        _fixture_row(2, "2026-02-06", "1"),
    ]
    manifest, path = _ledger(tmp_path, rows)
    from kini_engine.ledger import read_prediction_ledger

    loaded_manifest, loaded_rows = read_prediction_ledger(path)
    result = validate_snapshot_alignment(loaded_manifest, loaded_rows)
    assert result["n"] == 2
    assert result["snapshot_dates"] == 2
    assert manifest["forecast_count"] == 2


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("market_snapshot_date", "2026-01-11", "date order"),
        ("training_cutoff_date", "2026-01-09", "training data"),
        ("model_fit_cutoff_date", "2026-01-09", "training data"),
    ],
)
def test_snapshot_alignment_rejects_temporal_leakage(tmp_path, field, value, message):
    row = _fixture_row(1, "2026-01-09")
    manifest, path = _ledger(tmp_path, [row])
    from kini_engine.ledger import read_prediction_ledger

    loaded_manifest, loaded_rows = read_prediction_ledger(path)
    loaded_rows[0][field] = value
    with pytest.raises(ValueError, match=message):
        validate_snapshot_alignment(loaded_manifest, loaded_rows)

def test_paired_market_benchmark_uses_same_snapshot_fixture_rows(tmp_path):
    rows = [
        _fixture_row(1, "2026-01-09", "X"),
        _fixture_row(2, "2026-01-09", "1"),
        _fixture_row(3, "2026-02-06", "X"),
        _fixture_row(4, "2026-02-06", "2"),
    ]
    manifest, path = _ledger(tmp_path, rows)
    from kini_engine.ledger import read_prediction_ledger

    loaded_manifest, loaded_rows = read_prediction_ledger(path)
    report = analyze(loaded_manifest, loaded_rows, bins=5, bootstrap_samples=100)
    assert report["sample"]["n"] == 4
    assert report["sample"]["draws"] == 2
    assert report["market"]["n"] == 4
    for mode in MODES:
        paired = report["models"][mode]["paired_market"]
        assert paired["n"] == 4
        assert paired["bootstrap"]["blocks"] == 2
        assert len(paired["bootstrap"]["delta_brier_model_minus_market_ci95"]) == 2


def test_block_bootstrap_is_reproducible_and_paired():
    model = __import__("numpy").array([0.2, 0.3, 0.4, 0.5])
    market = __import__("numpy").array([0.25, 0.25, 0.35, 0.45])
    outcomes = __import__("numpy").array([0.0, 1.0, 0.0, 1.0])
    months = __import__("numpy").array(["2026-01", "2026-01", "2026-02", "2026-02"])
    first = paired_block_bootstrap(model, market, outcomes, months, 100, 77)
    second = paired_block_bootstrap(model, market, outcomes, months, 100, 77)
    assert first == second
    assert first["blocks"] == 2
    assert first["replicates"] == 100
