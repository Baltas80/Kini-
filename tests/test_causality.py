from __future__ import annotations

import pytest

from kini_engine.causality import (
    CausalityViolation,
    assert_available_at,
    assert_causal_history,
    assert_causal_match,
)
from kini_engine.core import KiniEngine, Match
from kini_engine.snapshots import SnapshotObservation, build_snapshot


CUTOFF = "2025-01-01T10:00:00Z"


def make_observation(observation_id: str, captured_at: str, payload: dict) -> SnapshotObservation:
    return SnapshotObservation.from_dict(
        {
            "observation_id": observation_id,
            "match_id": "fixture-1",
            "source_id": "market",
            "source_record_id": observation_id,
            "captured_at": captured_at,
            "payload_hash": f"hash-{observation_id}",
            "payload": payload,
        }
    )


def test_available_at_rule_allows_data_at_cutoff():
    assert_available_at(CUTOFF, CUTOFF, subject="snapshot")


def test_available_at_rule_rejects_future_data():
    with pytest.raises(CausalityViolation, match="future information blocked"):
        assert_available_at("2025-01-01T10:00:01Z", CUTOFF, subject="market")


def test_causal_match_requires_kickoff_strictly_before_cutoff():
    match = Match(CUTOFF, "A", "B", 1, 0, "1")
    with pytest.raises(CausalityViolation, match="future information blocked"):
        assert_causal_match(match, CUTOFF)


def test_causal_history_rejects_a_future_match_even_when_mixed_into_history():
    history = [
        Match("2025-01-01T09:00:00Z", "A", "B", 1, 0, "1"),
        Match("2025-01-01T10:01:00Z", "C", "D", 0, 1, "2"),
    ]
    with pytest.raises(CausalityViolation, match="future information blocked"):
        assert_causal_history(history, CUTOFF)


def test_prediction_aborts_before_model_when_future_history_is_injected(monkeypatch):
    engine = KiniEngine()
    engine.fit(
        [
            Match("2025-01-01T09:00:00Z", "A", "B", 1, 0, "1"),
            Match("2025-01-01T10:01:00Z", "C", "D", 0, 1, "2"),
        ]
    )

    def model_must_not_run(*args, **kwargs):
        raise AssertionError("prediction reached model execution with future history")

    monkeypatch.setattr(engine, "_predict_one", model_must_not_run)
    target = Match("2025-01-01T11:00:00Z", "A", "C")

    with pytest.raises(CausalityViolation, match="future information blocked"):
        engine.predict(target, information_at=CUTOFF)


def test_future_snapshot_observation_cannot_change_the_snapshot():
    past = make_observation(
        "past",
        "2025-01-01T09:30:00Z",
        {"home_probability": 0.50},
    )
    future = make_observation(
        "future",
        "2025-01-01T10:30:00Z",
        {"home_probability": 0.99, "attack": "poisoned"},
    )

    clean = build_snapshot([past], information_at=CUTOFF)
    poisoned = build_snapshot([past, future], information_at=CUTOFF)

    assert poisoned == clean
    assert poisoned.observation_count == 1
    assert poisoned.for_match("fixture-1") == (past,)


def test_causal_match_rejects_non_finished_canonical_match():
    class CanonicalMatch:
        date = "2025-01-01T09:00:00Z"
        status = "scheduled"

    with pytest.raises(CausalityViolation, match="not finished"):
        assert_causal_match(CanonicalMatch(), CUTOFF)
