from datetime import datetime, timedelta, timezone

import pytest

from kini_engine.backtest import walk_forward
from kini_engine.core import Match
from kini_engine.temporal import PredictionContext, parse_information_at


def test_information_at_is_normalized_to_utc():
    parsed = parse_information_at("2025-03-31T23:59:59+01:00")
    assert parsed == datetime(2025, 3, 31, 22, 59, 59, tzinfo=timezone.utc)


def test_naive_information_at_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_information_at(datetime(2025, 3, 31, 23, 59, 59))


def test_prediction_context_requires_information_before_kickoff():
    with pytest.raises(ValueError, match="strictly before"):
        PredictionContext.from_match(
            "2025-04-01T00:00:00Z",
            "2025-04-01T00:00:00Z",
        )


def test_prediction_context_exposes_replayable_boundary():
    context = PredictionContext.from_match(
        "2025-04-01T18:00:00+02:00",
        "2025-04-01T17:30:00+02:00",
    )
    assert context.to_dict() == {
        "information_at": "2025-04-01T15:30:00Z",
        "target_kickoff_at": "2025-04-01T16:00:00Z",
    }


def test_walk_forward_same_kickoff_is_causal():
    teams = ["A", "B", "C", "D"]
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    matches = []
    for i in range(40):
        h, a = teams[i % 4], teams[(i + 1) % 4]
        hg, ag = i % 3, (i + 1) % 2
        result = "1" if hg > ag else ("2" if ag > hg else "X")
        matches.append(Match(base + timedelta(days=i), h, a, hg, ag, result))

    kickoff = base + timedelta(days=42)
    matches.extend([
        Match(kickoff, "A", "B", 1, 0, "1"),
        Match(kickoff, "C", "D", 0, 1, "2"),
    ])

    result = walk_forward(matches, min_train=40, refit_every=100)
    assert result["metrics"]["n"] == 2
    assert all(
        row["information_at"] == "2025-02-11T23:59:59.999999Z"
        for row in result["rows"]
    )
