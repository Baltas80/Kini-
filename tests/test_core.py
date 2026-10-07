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
    dc = e.predict(Match(datetime(2025, 4, 1), "A", "D"), mode="dc")
    assert abs(sum(dc.probabilities.values()) - 1.0) < 1e-9


def test_optimizer_budget():
    p = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    t = TicketOptimizer().optimize(p, budget=8)
    assert t["column_count"] <= 8


def test_dixon_coles_uses_full_history():
    data = sample()
    e1 = KiniEngine().fit(data[:20])
    e2 = KiniEngine().fit(data[:80])
    p1 = e1.predict(Match(datetime(2025, 4, 1), "A", "D"), mode="dc").probabilities
    p2 = e2.predict(Match(datetime(2025, 4, 1), "A", "D"), mode="dc").probabilities
    assert max(abs(p1[s] - p2[s]) for s in ("1", "X", "2")) > 1e-6


def test_optimizer_returns_exact_column_count():
    p = [{"1": 0.50, "X": 0.30, "2": 0.20} for _ in range(14)]
    t = TicketOptimizer().optimize(p, budget=8)
    assert t["column_count"] == 8
    assert len(t["columns"]) == 8
    assert all(len(column) == 14 for column in t["columns"])


def test_date_num_accepts_football_data_format():
    assert _date_num("01/02/2021") < _date_num("02/02/2021")
