from datetime import datetime, timedelta, timezone

import pytest

from kini_engine.backtest import baseline_walk_forward, multiclass_metrics
from kini_engine.baselines import ExpandingPriorBaseline, RecentPriorBaseline, UniformBaseline, baseline_suite
from kini_engine.causality import CausalityViolation
from kini_engine.core import Match


def sample_history(n=12):
    teams = ["A", "B", "C", "D"]
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    matches = []
    outcomes = ["1", "X", "2"]
    for i in range(n):
        outcome = outcomes[i % 3]
        if outcome == "1":
            hg, ag = 2, 0
        elif outcome == "X":
            hg, ag = 1, 1
        else:
            hg, ag = 0, 2
        matches.append(
            Match(
                base + timedelta(days=i),
                teams[i % 4],
                teams[(i + 1) % 4],
                hg,
                ag,
                outcome,
            )
        )
    return matches


def test_uniform_baseline_is_exactly_uniform():
    assert UniformBaseline().fit(sample_history()).predict_proba() == {
        "1": 1 / 3,
        "X": 1 / 3,
        "2": 1 / 3,
    }


def test_expanding_prior_uses_only_observed_history_with_laplace_smoothing():
    history = sample_history(3)
    probabilities = ExpandingPriorBaseline(alpha=1.0).fit(history).predict_proba()
    assert probabilities == {"1": 1 / 3, "X": 1 / 3, "2": 1 / 3}


def test_recent_prior_uses_only_the_configured_window():
    history = sample_history(6)
    probabilities = RecentPriorBaseline(window=2, alpha=1.0).fit(history).predict_proba()
    assert probabilities == {"1": 0.2, "X": 0.4, "2": 0.4}


def test_baseline_suite_returns_normalized_probabilities():
    suite = baseline_suite(sample_history(9), information_at="2025-01-10T00:00:00Z")
    assert set(suite) == {"uniform", "expanding_prior", "recent_prior"}
    for probabilities in suite.values():
        assert abs(sum(probabilities.values()) - 1.0) < 1e-12
        assert all(value > 0 for value in probabilities.values())


def test_baseline_suite_rejects_future_history():
    history = sample_history(5)
    history.append(
        Match(
            datetime(2025, 2, 1, tzinfo=timezone.utc),
            "A",
            "B",
            9,
            0,
            "1",
        )
    )
    with pytest.raises(CausalityViolation):
        baseline_suite(history, information_at="2025-01-06T00:00:00Z")


def test_baseline_walk_forward_is_causal_and_counts_all_test_rows():
    result = baseline_walk_forward(sample_history(12), min_train=3, recent_window=2)
    assert result["protocol"]["test_rows"] == 9
    for metrics in result["metrics"].values():
        assert metrics["n"] == 9


def test_empty_metric_sets_are_not_reported_as_valid_zero_scores():
    with pytest.raises(ValueError, match="empty evaluation set"):
        multiclass_metrics([])
