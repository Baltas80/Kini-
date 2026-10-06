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


def test_dixon_coles_loss_uses_all_observations(monkeypatch):
    from math import exp, log
    from types import SimpleNamespace
    from scipy.stats import poisson
    from kini_engine.core import DixonColes, _dc_tau

    captured = {}

    def fake_minimize(fun, x0, **kwargs):
        captured["loss"] = fun(x0)
        return SimpleNamespace(success=True, x=x0)

    monkeypatch.setattr("kini_engine.core.minimize", fake_minimize)
    data = sample()
    DixonColes(decay=1.0).fit(data)

    expected = 0.0
    lh, la, rho = exp(0.15), exp(-0.1), -0.05
    for m in data:
        tau = max(_dc_tau(m.home_goals, m.away_goals, lh, la, rho), 1e-9)
        expected -= poisson.logpmf(m.home_goals, lh)
        expected -= poisson.logpmf(m.away_goals, la)
        expected -= log(tau)

    assert abs(captured["loss"] - expected) < 1e-9


def test_dixon_coles_fit_is_successful():
    from kini_engine.core import DixonColes
    model = DixonColes(decay=0.995).fit(sample())
    assert model.fitted
    assert model.teams
    assert set(model.attack) == set(model.teams)
    assert set(model.defence) == set(model.teams)


def test_engine_defaults_to_core_only():
    e = KiniEngine().fit(sample())
    assert e.ml is None
    assert e.enable_ml is False
    assert e.enable_context is False


def test_date_parser_accepts_historical_formats():
    from kini_engine.core import DixonColes
    model = DixonColes()
    assert model._date_num("01/02/2025") > 0
    assert model._date_num("01/02/25") > 0
    assert model._date_num("2025/02/01") > 0


def test_unplayed_fixtures_do_not_break_context_features():
    history = sample() + [Match("30/03/2025", "A", "B")]
    e = KiniEngine(enable_context=True).fit(history)
    prediction = e.predict(Match("31/03/2025", "A", "B"))
    assert abs(sum(prediction.probabilities.values()) - 1.0) < 1e-9
