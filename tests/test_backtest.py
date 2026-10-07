from kini_engine.backtest import multiclass_metrics
from kini_engine.core import SIGNS


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
