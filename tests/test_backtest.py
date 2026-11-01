from datetime import datetime, timedelta

import kini_engine.backtest as backtest
from kini_engine.backtest import multiclass_metrics
from kini_engine.core import Match


def test_metrics_are_bounded():
    rows = [
        ({"1": 0.7, "X": 0.2, "2": 0.1}, "1"),
        ({"1": 0.2, "X": 0.6, "2": 0.2}, "2"),
        ({"1": 0.1, "X": 0.2, "2": 0.7}, "X"),
    ]
    m = multiclass_metrics(rows)
    assert m["n"] == 3
    assert 0.0 <= m["accuracy"] <= 1.0
    assert m["brier"] >= 0.0
    assert m["logloss"] >= 0.0
    assert m["rps"] >= 0.0
    assert 0.0 <= m["ece"] <= 1.0


def test_walk_forward_keeps_same_day_fixtures_out_of_training(monkeypatch):
    fitted_sizes = []
    prediction_training_sizes = []

    class FakeEngine:
        def __init__(self):
            self.dc = type("DC", (), {"decay": 0.995})()
            self.history = []

        def fit(self, history):
            self.history = list(history)
            fitted_sizes.append(len(self.history))
            return self

        def predict(self, match):
            prediction_training_sizes.append(len(self.history))
            return type("Prediction", (), {
                "probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}
            })()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    day1 = datetime(2025, 1, 1)
    day2 = datetime(2025, 1, 2)
    matches = [
        Match(day1, f"H{i}", f"A{i}", 1, 0, "1")
        for i in range(12)
    ] + [
        Match(day2, "H12", "A12", 1, 0, "1"),
        Match(day2, "H13", "A13", 0, 0, "X"),
    ]

    result = backtest.walk_forward(matches, min_train=12)

    assert result["metrics"]["n"] == 2
    assert fitted_sizes == [12]
    assert prediction_training_sizes == [12, 12]


def test_walk_forward_refit_interval_counts_dates(monkeypatch):
    fitted_sizes = []

    class FakeEngine:
        def __init__(self):
            self.dc = type("DC", (), {"decay": 0.995})()
            self.history = []

        def fit(self, history):
            self.history = list(history)
            fitted_sizes.append(len(history))
            return self

        def predict(self, match):
            return type("Prediction", (), {
                "probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}
            })()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    start = datetime(2025, 1, 1)
    matches = [Match(start, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    for day in range(1, 4):
        matches.append(Match(start + timedelta(days=day), f"H{day}", f"A{day}", 1, 0, "1"))

    backtest.walk_forward(matches, min_train=12, refit_every=2)

    # First forecast date fits, second reuses that fit, third refits.
    assert fitted_sizes == [12, 14]
