from datetime import datetime, timedelta
from itertools import combinations
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from kini_engine.core import (
    DixonColes,
    FeatureModel,
    KiniEngine,
    Match,
    TicketOptimizer,
    _date_num,
    context_adjust,
    score_grid,
)


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
    assert t["cost_eur"] == round(t["column_count"] * 0.75, 2)
    assert t["budget_unit"] == "columns"


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
    assert t["cost_eur"] == 6.0


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



def test_model_only_ensemble_excludes_market_and_lae():
    class FakeML:
        def fit_predict_proba(self, training_history, current, feature_history=None):
            return np.asarray([0.60, 0.20, 0.20])

    engine = KiniEngine(enable_ml=True)
    engine.dc.predict = lambda home, away: (
        {"1": 0.80, "X": 0.10, "2": 0.10},
        [],
    )
    engine.ml = FakeML()
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        market={"1": 0.01, "X": 0.01, "2": 0.98},
        lae={"1": 0.01, "X": 0.98, "2": 0.01},
    )

    prediction = engine.predict(fixture, mode="ensemble_dc_ml")

    # Relative weights 0.58:0.17, normalized over model probabilities only.
    expected = {
        "1": (0.58 * 0.80 + 0.17 * 0.60) / 0.75,
        "X": (0.58 * 0.10 + 0.17 * 0.20) / 0.75,
        "2": (0.58 * 0.10 + 0.17 * 0.20) / 0.75,
    }
    assert prediction.probabilities == pytest.approx(expected)
    assert sum(prediction.probabilities.values()) == pytest.approx(1.0)


def test_ensemble_ignores_temporally_ineligible_market_and_surprise_reference():
    engine = KiniEngine()
    engine.dc.predict = lambda home, away: (
        {"1": 0.80, "X": 0.10, "2": 0.10},
        [],
    )
    raw_market = {"1": 0.01, "X": 0.01, "2": 0.98}
    ineligible = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        market=raw_market,
        detail={
            "market_temporal_status": "ambiguous",
            "market_pre_match_eligible": False,
        },
    )
    no_market = Match(datetime(2025, 4, 1), "A", "B")

    with_market = engine.predict(ineligible, mode="ensemble")
    without_market = engine.predict(no_market, mode="ensemble")

    assert with_market.probabilities == pytest.approx(without_market.probabilities)
    assert with_market.surprise is None
    assert ineligible.has_temporally_eligible_market is False


def test_market_mode_rejects_temporally_ineligible_odds():
    engine = KiniEngine()
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        market={"1": 0.4, "X": 0.3, "2": 0.3},
        detail={
            "market_temporal_status": "ambiguous",
            "market_pre_match_eligible": False,
        },
    )

    with pytest.raises(ValueError, match="not temporally eligible"):
        engine.predict(fixture, mode="market")


def test_ensemble_uses_schedule_screened_market():
    engine = KiniEngine()
    engine.dc.predict = lambda home, away: (
        {"1": 0.80, "X": 0.10, "2": 0.10},
        [],
    )
    eligible = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        market={"1": 0.01, "X": 0.01, "2": 0.98},
        detail={
            "market_temporal_status": "schedule_compatible",
            "market_pre_match_eligible": True,
        },
    )
    without_market = Match(datetime(2025, 4, 1), "A", "B")

    with_market = engine.predict(eligible, mode="ensemble")
    without_market_prediction = engine.predict(without_market, mode="ensemble")

    assert with_market.probabilities != pytest.approx(without_market_prediction.probabilities)
    assert eligible.has_temporally_eligible_market is True


def test_feature_model_ignores_same_day_future_and_unverified_standings():
    history = sample()
    current = Match(
        datetime(2025, 4, 1),
        "A",
        "D",
        detail={
            "clasificacion_local_pos": 1,
            "clasificacion_visitante_pos": 20,
        },
    )
    model = FeatureModel()
    baseline = model._features(history, current)

    contaminated_history = history + [
        Match(datetime(2025, 4, 1), "A", "D", 9, 0, "1"),
        Match(datetime(2025, 4, 2), "A", "D", 0, 9, "2"),
    ]
    observed = model._features(contaminated_history, current)

    assert baseline.shape == (12,)
    assert np.array_equal(observed, baseline)


def test_feature_model_uses_2d_inference_and_caches_fit_per_history(monkeypatch):
    class FakeXGBClassifier:
        fit_calls = 0

        def __init__(self, **kwargs):
            self.classes_ = np.array([0, 1, 2])

        def fit(self, features, labels):
            assert features.ndim == 2
            assert features.shape == (80, 12)
            assert labels.shape == (80,)
            type(self).fit_calls += 1
            return self

        def predict_proba(self, features):
            assert features.ndim == 2
            assert features.shape == (1, 12)
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



def test_feature_model_training_rows_exclude_same_calendar_day_results(monkeypatch):
    class FakeXGBClassifier:
        def __init__(self, **kwargs):
            self.classes_ = np.array([0, 1, 2])

        def fit(self, features, labels):
            assert features.shape == (80, 12)
            return self

        def predict_proba(self, features):
            assert features.shape == (1, 12)
            return np.array([[0.4, 0.35, 0.25]])

    monkeypatch.setitem(sys.modules, "xgboost", SimpleNamespace(XGBClassifier=FakeXGBClassifier))
    history = sample()
    first = history[0]
    second = history[1]
    history[1] = Match(first.date, second.home, second.away, second.home_goals, second.away_goals, second.result)
    captured = {}
    model = FeatureModel()

    def capture_features(past, current):
        if current is history[1]:
            captured["past"] = list(past)
        return np.zeros(12, dtype=float)

    monkeypatch.setattr(model, "_features", capture_features)
    probabilities = model.fit_predict_proba(history, Match(datetime(2025, 4, 1), "A", "D"))

    assert probabilities is not None
    assert first not in captured["past"]


def test_feature_model_uses_latest_feature_history_without_refitting(monkeypatch):
    class FakeXGBClassifier:
        fit_calls = 0
        inference_first_feature = None

        def __init__(self, **kwargs):
            self.classes_ = np.array([0, 1, 2])

        def fit(self, features, labels):
            type(self).fit_calls += 1
            return self

        def predict_proba(self, features):
            type(self).inference_first_feature = float(features[0, 0])
            return np.array([[0.5, 0.3, 0.2]])

    monkeypatch.setitem(sys.modules, "xgboost", SimpleNamespace(XGBClassifier=FakeXGBClassifier))
    training_history = sample()
    feature_history = training_history + [Match(datetime(2025, 4, 1), "B", "D", 2, 0, "1")]
    model = FeatureModel()
    monkeypatch.setattr(
        model,
        "_features",
        lambda past, current: np.full(12, len(past), dtype=float),
    )

    model.fit_predict_proba(training_history, Match(datetime(2025, 4, 2), "A", "D"), feature_history)
    model.fit_predict_proba(training_history, Match(datetime(2025, 4, 3), "C", "A"), feature_history)

    assert FakeXGBClassifier.fit_calls == 1
    assert FakeXGBClassifier.inference_first_feature == len(feature_history)


def test_optimizer_rejects_missing_sign_probability():
    predictions = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    del predictions[6]["2"]

    with pytest.raises(ValueError, match="missing probability for sign"):
        TicketOptimizer().optimize(predictions, budget=8)


def test_optimizer_rejects_invalid_probability_distributions():
    import pytest

    valid = {"1": 0.5, "X": 0.3, "2": 0.2}
    predictions = [valid.copy() for _ in range(14)]
    predictions[4]["1"] = 0.8
    with pytest.raises(ValueError, match="must sum to 1"):
        TicketOptimizer().optimize(predictions, budget=8)

    predictions = [valid.copy() for _ in range(14)]
    predictions[2]["X"] = float("nan")
    with pytest.raises(ValueError, match="finite and in"):
        TicketOptimizer().optimize(predictions, budget=8)

    predictions = [valid.copy() for _ in range(14)]
    predictions[1]["2"] = -0.1
    with pytest.raises(ValueError, match="finite and in"):
        TicketOptimizer().optimize(predictions, budget=8)


def test_optimizer_enforces_selae_direct_double_triple_table():
    predictions = [{"1": 1 / 3, "X": 1 / 3, "2": 1 / 3} for _ in range(14)]
    result = TicketOptimizer().optimize(
        predictions,
        budget=TicketOptimizer.MAX_AUTHORIZED_COLUMNS,
    )

    assert result["double_count"] == 7
    assert result["triple_count"] == 5
    assert result["column_count"] == 31_104
    assert result["system_method"] == "multiple_direct"
    assert result["maximum_authorized_columns"] == 31_104
    assert result["pleno15_multiplier"] == 1
    assert result["cost_eur"] == 23_328.0


def test_optimizer_rejects_budget_above_selae_direct_maximum():
    predictions = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    with pytest.raises(ValueError, match="authorized direct columns"):
        TicketOptimizer().optimize(
            predictions,
            budget=TicketOptimizer.MAX_AUTHORIZED_COLUMNS + 1,
        )


def test_optimizer_rejects_minimum_below_selae_minimum():
    with pytest.raises(ValueError, match="at least 2"):
        TicketOptimizer(minimum_columns=1)


def test_optimizer_rejects_boolean_budget():
    predictions = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    with pytest.raises(ValueError, match="positive integer"):
        TicketOptimizer().optimize(predictions, budget=True)


def test_optimizer_enforces_minimum_stake_and_price():
    predictions = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    with pytest.raises(ValueError, match="at least 2 columns"):
        TicketOptimizer().optimize(predictions, budget=1)

    result = TicketOptimizer().optimize(predictions, budget=2)
    assert result["column_count"] == 2
    assert result["minimum_columns"] == 2
    assert result["price_per_column_eur"] == 0.75
    assert result["cost_eur"] == 1.50

    custom = TicketOptimizer(price_per_column_eur=1.0).optimize(predictions, budget=2)
    assert custom["cost_eur"] == 2.0


def test_pleno15_aggregates_official_goal_categories():
    model = DixonColes()
    distribution = model.pleno15_probs("A", "B")

    assert len(distribution) == 16
    assert {row["home_goals"] for row in distribution} == {"0", "1", "2", "M"}
    assert {row["away_goals"] for row in distribution} == {"0", "1", "2", "M"}
    assert sum(row["probability"] for row in distribution) == pytest.approx(1.0)

    grid = score_grid(1.35, 1.05)
    expected_m_m = float(grid[3:, 3:].sum())
    observed_m_m = next(
        row["probability"]
        for row in distribution
        if row["home_goals"] == "M" and row["away_goals"] == "M"
    )
    assert observed_m_m == pytest.approx(expected_m_m)


def test_quiniela_returns_16_pleno15_categories():
    fixtures = [
        Match(datetime(2025, 1, 1), f"Home{i}", f"Away{i}")
        for i in range(15)
    ]
    result = KiniEngine(enable_ml=False).quiniela(fixtures, budget=2)
    assert len(result["pleno_al_15"]) == 16
    assert sum(row["probability"] for row in result["pleno_al_15"]) == pytest.approx(1.0)
    assert result["pleno_al_15_best"] == result["pleno_al_15"][0]
    assert result["full_coupon_coverage_assumption"] == (
        "independent_all_14_matches_and_pleno15"
    )
    assert result["estimated_full_coupon_coverage_independent"] == pytest.approx(
        result["ticket"]["joint_coverage"]
        * result["pleno_al_15_best"]["probability"]
    )
    assert 0.0 <= result["estimated_full_coupon_coverage_independent"] <= 1.0


def test_optimizer_matches_exhaustive_search_for_small_budget():
    predictions = [
        {
            "1": 0.40 + (index % 4) * 0.03,
            "X": 0.35 - (index % 3) * 0.02,
            "2": 0.25 - (index % 4) * 0.01,
        }
        for index in range(14)
    ]
    predictions = [
        {sign: value / sum(row.values()) for sign, value in row.items()}
        for row in predictions
    ]
    result = TicketOptimizer().optimize(predictions, budget=4)

    shapes = []
    for index in range(14):
        for count in (2, 3):
            shape = [1] * 14
            shape[index] = count
            shapes.append(shape)
    for first, second in combinations(range(14), 2):
        shape = [1] * 14
        shape[first] = shape[second] = 2
        shapes.append(shape)

    expected = 0.0
    for shape in shapes:
        covered = 1.0
        for row, count in zip(predictions, shape):
            top = sorted(row.values(), reverse=True)[:count]
            covered *= sum(top)
        expected = max(expected, covered)

    assert result["column_count"] <= 4
    assert result["joint_coverage"] == pytest.approx(expected)
    assert len(result["columns"]) == result["column_count"]
    assert result["coverage_assumption"] == "independent_matches"
