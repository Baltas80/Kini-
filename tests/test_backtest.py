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
    assert result["n_test"] == 2
    assert result["test_start_date"] == "2025-01-02"
    assert result["test_end_date"] == "2025-01-02"
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



def test_compare_reports_market_metrics_on_same_fixture_sample(monkeypatch):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()
            self.history = []

        def fit(self, history):
            self.history = list(history)
            return self

        def predict(self, match, mode="ensemble", history=None):
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
        Match(day2, "H12", "A12", 1, 0, "1", market={"1": 0.4, "X": 0.3, "2": 0.3}),
        Match(day2, "H13", "A13", 0, 0, "X"),
    ]

    result = backtest.compare_walk_forward(matches, min_train=12)

    for mode in ("dc", "ml", "ensemble", "ensemble_dc_ml", "ensemble_dc_ml_adaptive"):
        assert result["common_sample"][mode]["model"]["n"] == 1
        assert result["common_sample"][mode]["market"]["n"] == 1


def test_select_dc_ml_weight_uses_only_supplied_prior_oof_rows():
    default_weight = backtest.DEFAULT_DC_ML_WEIGHT
    assert backtest.select_dc_ml_weight([], min_history=2) == default_weight

    history = [
        (
            {"1": 0.90, "X": 0.05, "2": 0.05},
            {"1": 0.05, "X": 0.90, "2": 0.05},
            "1",
        )
        for _ in range(4)
    ]
    selected = backtest.select_dc_ml_weight(
        history,
        min_history=2,
        window=4,
        regularization=0.0,
    )
    assert selected == 1.0


def test_adaptive_weight_updates_only_after_complete_forecast_date(monkeypatch):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()
            self.history = []

        def fit(self, history):
            self.history = list(history)
            return self

        def predict(self, match, mode="ensemble", history=None):
            probabilities = (
                {"1": 0.90, "X": 0.05, "2": 0.05}
                if mode == "dc"
                else {"1": 0.05, "X": 0.90, "2": 0.05}
                if mode == "ml"
                else {"1": 0.50, "X": 0.30, "2": 0.20}
            )
            return type("Prediction", (), {"probabilities": probabilities})()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    day1 = datetime(2025, 1, 1)
    day2 = datetime(2025, 1, 2)
    day3 = datetime(2025, 1, 3)
    matches = [
        Match(day1, f"H{i}", f"A{i}", 1, 0, "1")
        for i in range(12)
    ] + [
        Match(day2, "H12", "A12", 1, 0, "1"),
        Match(day2, "H13", "A13", 2, 0, "1"),
        Match(day3, "H14", "A14", 1, 0, "1"),
    ]

    result = backtest.compare_walk_forward(
        matches,
        min_train=12,
        adaptive_min_history=1,
        adaptive_window=10,
        adaptive_regularization=0.0,
    )

    trace = result["adaptive_ensemble"]["weight_trace"]
    assert len(trace) == 2
    assert trace[0]["date"] == "2025-01-02"
    assert trace[0]["prior_oof_predictions"] == 0
    assert trace[0]["dc_weight"] == backtest.DEFAULT_DC_ML_WEIGHT
    assert trace[1]["date"] == "2025-01-03"
    assert trace[1]["prior_oof_predictions"] == 2
    assert trace[1]["dc_weight"] == 1.0
    assert result["ensemble_dc_ml_adaptive"]["n"] == 3
