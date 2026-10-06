from datetime import datetime, timedelta

from kini_engine.core import KiniEngine, Match, TicketOptimizer


def sample():
    teams = ["A", "B", "C", "D"]
    out = []
    base = datetime(2025, 1, 1)
    for i in range(80):
        h, a = teams[i % 4], teams[(i + 1) % 4]
        hg = (i * 3) % 4
        ag = (i + 1) % 3
        out.append(Match(base + timedelta(days=i), h, a, hg, ag, "1" if hg > ag else ("2" if ag > hg else "X")))
    return out


def test_fit_predict():
    e = KiniEngine().fit(sample())
    p = e.predict(Match(datetime(2025, 4, 1), "A", "D"))
    assert abs(sum(p.probabilities.values()) - 1.0) < 1e-9
    assert p.sign in {"1", "X", "2"}


def test_optimizer_budget():
    p = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    t = TicketOptimizer().optimize(p, budget=8)
    assert t["column_count"] <= 8


def test_optimizer_exact_budget_one():
    p = [{"1": 0.7, "X": 0.2, "2": 0.1} for _ in range(14)]
    t = TicketOptimizer().optimize(p, budget=1)
    assert t["column_count"] == 1
    assert t["joint_coverage"] == 0.7 ** 14
    assert all(set(col) == {"1"} for col in t["columns"])


def test_optimizer_chooses_best_double():
    p = [{"1": 0.45, "X": 0.4, "2": 0.15}] + [{"1": 0.7, "X": 0.2, "2": 0.1} for _ in range(13)]
    t = TicketOptimizer().optimize(p, budget=2)
    assert t["column_count"] == 2
    assert t["shape"].count(2) == 1
    assert set(t["columns"][0][0:1] + t["columns"][1][0:1]) == {"1", "X"}


def test_elo_is_causal_and_normalized():
    from kini_engine.core import EloModel, Match
    e = EloModel().fit(sample())
    p = e.predict("A", "D")
    assert abs(sum(p.values()) - 1.0) < 1e-9
    assert set(p) == {"1", "X", "2"}


def test_walk_forward_metrics_include_calibration():
    from kini_engine.backtest import walk_forward_baseline
    result = walk_forward_baseline(sample(), min_train=20)
    assert result["metrics"]["n"] == 60
    assert all(k in result["metrics"] for k in ("rps", "ece", "logloss", "brier"))
