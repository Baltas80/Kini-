from datetime import datetime, timezone

import pytest

from kini_engine.causality import CausalityViolation, assert_available_at, assert_causal_history, assert_causal_match
from kini_engine.core import Match


def test_available_at_rule_allows_data_at_cutoff():
    assert_available_at("2025-01-01T10:00:00Z", "2025-01-01T10:00:00Z", subject="snapshot")


def test_available_at_rule_rejects_future_data():
    with pytest.raises(CausalityViolation, match="future information blocked"):
        assert_available_at("2025-01-01T10:00:01Z", "2025-01-01T10:00:00Z", subject="market")


def test_causal_match_requires_kickoff_strictly_before_cutoff():
    match = Match("2025-01-01T10:00:00Z", "A", "B", 1, 0, "1")
    with pytest.raises(CausalityViolation):
        assert_causal_match(match, "2025-01-01T10:00:00Z")


def test_causal_history_rejects_a_future_match_even_when_mixed_into_history():
    history = [
        Match("2025-01-01T09:00:00Z", "A", "B", 1, 0, "1"),
        Match("2025-01-01T10:01:00Z", "C", "D", 0, 1, "2"),
    ]
    with pytest.raises(CausalityViolation, match="future information blocked"):
        assert_causal_history(history, "2025-01-01T10:00:00Z")


def test_causal_match_rejects_non_finished_canonical_match():
    class CanonicalMatch:
        date = "2025-01-01T09:00:00Z"
        status = "scheduled"

    with pytest.raises(CausalityViolation, match="not finished"):
        assert_causal_match(CanonicalMatch(), "2025-01-01T10:00:00Z")
