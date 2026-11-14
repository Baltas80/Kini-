from datetime import datetime, timedelta

from kini_engine.core import KiniEngine, Match, TicketOptimizer, _date_num, context_adjust


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



def test_h2h_counts_current_home_team_wins_regardless_of_historical_venue():
    current = Match(datetime(2025, 4, 1), "A", "B")
    history = [
        Match(datetime(2024, 1, i), "B", "A", 0, 1, "2")
        for i in range(1, 6)
    ]
    adjusted, reasons = context_adjust({"1": 1 / 3, "X": 1 / 3, "2": 1 / 3}, current, history)

    assert adjusted["1"] > adjusted["2"]
    assert "histórico H2H incorporado con peso limitado" in reasons



def test_dc_forecast_does_not_train_optional_ml_model():
    class ExplodingML:
        def fit_predict_proba(self, history, current):
            raise AssertionError("ML must not run for a DC-only forecast")

    engine = KiniEngine(enable_ml=True)
    engine.ml = ExplodingML()
    prediction = engine.predict(Match(datetime(2025, 4, 1), "A", "D"), mode="dc")

    assert set(prediction.probabilities) == {"1", "X", "2"}
    assert abs(sum(prediction.probabilities.values()) - 1.0) < 1e-9



def test_feature_model_uses_2d_inference_and_caches_fit_per_history(monkeypatch):
    class FakeXGBClassifier:
        fit_calls = 0

        def __init__(self, **kwargs):
            self.classes_ = np.array([0, 1, 2])

        def fit(self, features, labels):
            assert features.ndim == 2
            assert features.shape == (80, 15)
            assert labels.shape == (80,)
            type(self).fit_calls += 1
            return self

        def predict_proba(self, features):
            assert features.ndim == 2
            assert features.shape == (1, 15)
            return np.array([[0.55, 0.25, 0.20]])

    monkeypatch.setitem(sys.modules, "xgboost", SimpleNamespace(XGBClassifier=FakeXGBClassifier))
    history = sample()
    model = FeatureModel()
    current = Match(datetime(2025, 4, 1), "A", "D")

    first = model.fit_predict_proba(history, current)
    second = model.fit_predict_proba(history, current)

    assert first is not None and second is not None
    assert np.allclose(first, [0.55, 0.25, 0.20])
    assert np.allclose(second, first)
    assert FakeXGBClassifier.fit_calls == 1

    model.fit_predict_proba(list(history), current)
    assert FakeXGBClassifier.fit_calls == 2
