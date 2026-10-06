import pytest

from datetime import datetime, timedelta, timezone

from kini_engine.core import KiniEngine, Match, TicketOptimizer


def sample():
    teams = ["A", "B", "C", "D"]
    out = []
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(80):
        h, a = teams[i % 4], teams[(i + 1) % 4]
        hg = (i * 3) % 4
        ag = (i + 1) % 3
        out.append(Match(base + timedelta(days=i), h, a, hg, ag, "1" if hg > ag else ("2" if ag > hg else "X")))
    return out


def test_fit_predict():
    e = KiniEngine().fit(sample())
    p = e.predict(
        Match(datetime(2025, 4, 1, tzinfo=timezone.utc), "A", "D"),
        information_at="2025-03-31T23:59:59Z",
    )
    assert abs(sum(p.probabilities.values()) - 1.0) < 1e-9
    assert p.sign in {"1", "X", "2"}
    assert p.information_at == "2025-03-31T23:59:59Z"
    assert p.target_kickoff_at == "2025-04-01T00:00:00Z"


def test_optimizer_budget():
    p = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    t = TicketOptimizer().optimize(p, budget=8)
    assert t["column_count"] <= 8


def test_predict_rejects_future_history():
    engine = KiniEngine().fit(sample())
    with pytest.raises(ValueError, match="future information"):
        engine.predict(
            Match(datetime(2025, 4, 1, tzinfo=timezone.utc), "A", "D"),
            information_at="2025-01-15T00:00:00Z",
        )
