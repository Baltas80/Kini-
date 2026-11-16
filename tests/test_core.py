import sys
from datetime import datetime, timedelta
from itertools import combinations
from types import SimpleNamespace

import numpy as np
import pytest

from kini_engine.core import (
    LAE_SOURCE_ID,
    DixonColes,
    DixonColesFitError,
    FeatureModel,
    KiniEngine,
    Match,
    TicketOptimizer,
    _date_num,
    context_adjust,
    score_grid,
    surprise_signal,
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


def verified_lae_detail(**overrides):
    detail = {
        "lae_source": LAE_SOURCE_ID,
        "fixture_identity_status": "verified",
        "lae_captured_at": "2025-04-01T09:00:00+02:00",
        "kickoff_evidence_checked_at_utc": "2025-04-01T06:30:00+00:00",
        "kickoff_evidence_url": "https://www.uefa.com/test-schedule/",
        "kickoff_source": "UEFA test schedule",
        "kickoff_at": "2025-04-01T20:00:00+02:00",
    }
    detail.update(overrides)
    return detail


def test_fit_predict():
    e = KiniEngine().fit(sample())
    p = e.predict(Match(datetime(2025, 4, 1), "A", "D"))
    assert abs(sum(p.probabilities.values()) - 1.0) < 1e-9
    assert p.sign in {"1", "X", "2"}
    dc = e.predict(Match(datetime(2025, 4, 1), "A", "D"), mode="dc")
    assert abs(sum(dc.probabilities.values()) - 1.0) < 1e-9


def test_dixon_coles_fit_status_and_explicit_untrained_fallback():
    model = DixonColes().fit(sample()[:11])

    assert model.fitted is False
    assert model.fit_status == "insufficient_history"
    assert model.n_training_matches == 11
    with pytest.raises(ValueError, match="Dixon-Coles model is not fitted"):
        model.predict("A", "B")

    fallback, _ = model.predict(
        "A", "B", allow_untrained_fallback=True
    )
    assert abs(sum(fallback.values()) - 1.0) < 1e-9
    assert model.fitted is False


def test_engine_does_not_mark_insufficient_dixon_coles_as_fitted():
    engine = KiniEngine().fit(sample()[:11])

    assert engine.fitted is False
    assert engine.model_diagnostics()["dixon_coles"]["status"] == "insufficient_history"
    with pytest.raises(ValueError, match="Dixon-Coles model is not available"):
        engine.predict(
            Match(datetime(2025, 4, 1), "A", "B"),
            mode="dc",
        )


def test_dixon_coles_unseen_team_fallback_is_reported():
    engine = KiniEngine().fit(sample())
    prediction = engine.predict(
        Match(datetime(2025, 4, 1), "New Club", "A"),
        mode="dc",
    )

    assert any("cold-start fallback" in reason for reason in prediction.reasons)


def test_market_mode_is_independent_of_dixon_coles_fit():
    engine = KiniEngine().fit(sample()[:11])
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "D",
        market={"1": 0.50, "X": 0.25, "2": 0.25},
        detail={
            "market_temporal_status": "schedule_compatible",
            "market_pre_match_eligible": True,
        },
    )

    prediction = engine.predict(fixture, mode="market")

    assert prediction.probabilities == fixture.market
    assert engine.fitted is False


def test_dixon_coles_optimizer_failure_does_not_block_independent_ml(monkeypatch):
    from penaltyblog.models import DixonColesGoalModel

    def fail_fit(self, *args, **kwargs):
        raise ValueError("forced optimizer failure")

    monkeypatch.setattr(DixonColesGoalModel, "fit", fail_fit)
    engine = KiniEngine(enable_ml=True).fit(sample())

    assert engine.fitted is False
    assert engine.dc.fit_status == "fit_failed"
    assert "forced optimizer failure" in engine.dc.fit_error

    monkeypatch.setattr(
        engine.ml,
        "fit_predict_proba",
        lambda training, current, feature_history=None: np.asarray(
            [0.40, 0.35, 0.25], dtype=float
        ),
    )
    prediction = engine.predict(
        Match(datetime(2025, 4, 1), "A", "D"),
        mode="ml",
    )
    assert prediction.probabilities == {"1": 0.40, "X": 0.35, "2": 0.25}

    with pytest.raises(ValueError, match="Dixon-Coles model is not available"):
        engine.predict(
            Match(datetime(2025, 4, 1), "A", "D"),
            mode="dc",
        )


def test_dixon_coles_fit_rejects_unset_library_fitted_flag(monkeypatch):
    from penaltyblog.models import DixonColesGoalModel

    monkeypatch.setattr(
        DixonColesGoalModel,
        "fit",
        lambda self, *args, **kwargs: None,
    )
    engine = KiniEngine().fit(sample())

    assert engine.dc.fitted is False
    assert engine.dc.fit_status == "fit_failed"
    assert "model.fitted=True" in engine.dc.fit_error
    with pytest.raises(ValueError, match="Dixon-Coles model is not available"):
        engine.predict(
            Match(datetime(2025, 4, 1), "A", "D"),
            mode="dc",
        )


@pytest.mark.parametrize("forecast_index", [78, 79])
def test_engine_rejects_same_day_or_future_dixon_coles_training_results(forecast_index):
    history = sample()
    engine = KiniEngine().fit(history)
    current = Match(history[forecast_index].date, "A", "D")

    with pytest.raises(
        ValueError,
        match="Dixon-Coles training history.*strictly before forecast date",
    ):
        engine.predict(current, mode="dc")


def test_feature_model_rejects_same_day_or_future_training_labels():
    history = sample()
    current = Match(history[-1].date, "A", "D")

    with pytest.raises(
        ValueError,
        match="ML training history.*strictly before forecast date",
    ):
        FeatureModel().fit_predict_proba(history, current)


def test_engine_allows_unplayed_same_day_rows_in_training_snapshot():
    history = sample()
    forecast_day = history[-1].date
    training = history[:-1] + [Match(forecast_day, "C", "D")]
    engine = KiniEngine().fit(training)

    prediction = engine.predict(Match(forecast_day, "A", "B"), mode="dc")

    assert abs(sum(prediction.probabilities.values()) - 1.0) < 1e-9


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



def test_context_and_surprise_signals_ignore_same_day_and_future_results():
    current = Match(datetime(2025, 4, 1), "A", "B")
    prior = [
        Match(datetime(2025, 3, 1) + timedelta(days=index), "A", "B", 2, 0, "1")
        for index in range(5)
    ]
    contaminated = prior + [
        Match(datetime(2025, 4, 1), "A", "B", 0, 8, "2"),
        Match(datetime(2025, 4, 2), "B", "A", 8, 0, "1"),
        Match(datetime(2025, 4, 3), "C", "A", 8, 0, "1"),
    ]
    base = {"1": 1 / 3, "X": 1 / 3, "2": 1 / 3}
    model = {"1": 0.90, "X": 0.05, "2": 0.05}
    lae = {"1": 0.05, "X": 0.05, "2": 0.90}

    baseline_adjusted = context_adjust(base, current, prior)
    contaminated_adjusted = context_adjust(base, current, contaminated)
    assert contaminated_adjusted == baseline_adjusted

    baseline_signal = surprise_signal(model, lae, None, current, prior)
    contaminated_signal = surprise_signal(model, lae, None, current, contaminated)
    assert contaminated_signal == baseline_signal


def test_surprise_signal_rejects_unverified_external_reference_vectors():
    current = Match(datetime(2025, 4, 1), "A", "B")
    model = {"1": 0.80, "X": 0.10, "2": 0.10}
    opposing_reference = {"1": 0.05, "X": 0.05, "2": 0.90}

    assert surprise_signal(model, opposing_reference, opposing_reference, current, []) is None


def test_surprise_signal_uses_verified_match_lae_not_external_override():
    model = {"1": 0.80, "X": 0.10, "2": 0.10}
    verified_lae = {"1": 0.05, "X": 0.05, "2": 0.90}
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        lae=verified_lae,
        detail=verified_lae_detail(),
    )

    signal = surprise_signal(model, model, None, fixture, [])

    assert signal is not None
    assert signal["reference"] == "LAE"
    assert signal["score"] == pytest.approx(1.0)


def test_market_surprise_requires_valid_match_attached_probabilities():
    model = {"1": 0.80, "X": 0.10, "2": 0.10}
    opposing_reference = {"1": 0.05, "X": 0.05, "2": 0.90}
    unverified = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        market=opposing_reference,
    )
    assert unverified.has_temporally_eligible_market is False
    assert surprise_signal(model, None, opposing_reference, unverified, []) is None

    invalid = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        market={"1": 0.80, "X": 0.10, "2": 0.05},
        detail={
            "market_temporal_status": "schedule_compatible",
            "market_pre_match_eligible": True,
        },
    )
    assert invalid.has_temporally_eligible_market is False
    assert surprise_signal(model, None, opposing_reference, invalid, []) is None


def test_surprise_signal_uses_verified_match_market_not_external_override():
    model = {"1": 0.80, "X": 0.10, "2": 0.10}
    verified_market = {"1": 0.05, "X": 0.05, "2": 0.90}
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        market=verified_market,
        detail={
            "market_temporal_status": "schedule_compatible",
            "market_pre_match_eligible": True,
        },
    )

    signal = surprise_signal(model, None, model, fixture, [])

    assert signal is not None
    assert signal["reference"] == "mercado"
    assert signal["score"] == pytest.approx(1.0)


def test_dc_forecast_does_not_train_optional_ml_model():
    class ExplodingML:
        def fit_predict_proba(self, history, current):
            raise AssertionError("ML must not run for a DC-only forecast")

    engine = KiniEngine(enable_ml=True)
    engine.ml = ExplodingML()
    prediction = engine.predict(Match(datetime(2025, 4, 1), "A", "D"), mode="dc")

    assert set(prediction.probabilities) == {"1", "X", "2"}
    assert abs(sum(prediction.probabilities.values()) - 1.0) < 1e-9



def test_ensemble_ignores_lae_without_capture_provenance():
    engine = KiniEngine()
    engine.dc.predict = lambda home, away: (
        {"1": 0.80, "X": 0.10, "2": 0.10},
        [],
    )
    unverified = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        lae={"1": 0.05, "X": 0.05, "2": 0.90},
    )
    without_lae = Match(datetime(2025, 4, 1), "A", "B")

    prediction = engine.predict(unverified, mode="ensemble")
    baseline = engine.predict(without_lae, mode="ensemble")

    assert prediction.probabilities == pytest.approx(baseline.probabilities)
    assert prediction.surprise is None
    assert unverified.has_temporally_eligible_lae is False


def test_lae_mode_and_ensemble_accept_timezone_verified_pre_match_input():
    engine = KiniEngine()
    engine.dc.predict = lambda home, away: (
        {"1": 0.80, "X": 0.10, "2": 0.10},
        [],
    )
    lae = {"1": 0.05, "X": 0.05, "2": 0.90}
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        lae=lae,
        detail=verified_lae_detail(kickoff_at="2025-04-01T09:00:00+01:00"),
    )

    assert fixture.has_temporally_eligible_lae is True
    direct = engine.predict(fixture, mode="lae")
    ensemble = engine.predict(fixture, mode="ensemble")

    assert direct.probabilities == pytest.approx(lae)
    assert ensemble.probabilities != pytest.approx(
        engine.predict(Match(datetime(2025, 4, 1), "A", "B")).probabilities
    )
    assert ensemble.surprise is not None
    assert ensemble.surprise["reference"] == "LAE"


@pytest.mark.parametrize(
    "detail",
    [
        {},
        verified_lae_detail(lae_captured_at="2025-04-01T09:00:00"),
        verified_lae_detail(lae_captured_at="2025-04-01T21:00:00+02:00"),
        verified_lae_detail(lae_captured_at="2025-04-01T20:00:00+02:00"),
        verified_lae_detail(kickoff_evidence_checked_at_utc=None),
        verified_lae_detail(
            kickoff_evidence_checked_at_utc="2025-03-31T06:00:00+00:00"
        ),
        verified_lae_detail(fixture_identity_status="unverified"),
        verified_lae_detail(lae_source="untrusted-source"),
        verified_lae_detail(kickoff_evidence_url="http://www.uefa.com/test-schedule/"),
    ],
)
def test_lae_requires_fresh_verified_schedule_evidence_and_timezone_aware_capture_before_kickoff(
    detail,
):
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        lae={"1": 0.4, "X": 0.3, "2": 0.3},
        detail=detail,
    )
    assert fixture.has_temporally_eligible_lae is False


def test_lae_rejects_invalid_probability_contract():
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        lae={"1": 0.4, "X": 0.3, "2": 0.2},
        detail=verified_lae_detail(),
    )
    assert fixture.has_temporally_eligible_lae is False


def test_lae_mode_rejects_unverified_input():
    engine = KiniEngine()
    fixture = Match(
        datetime(2025, 4, 1),
        "A",
        "B",
        lae={"1": 0.4, "X": 0.3, "2": 0.3},
    )
    with pytest.raises(ValueError, match="not temporally verified"):
        engine.predict(fixture, mode="lae")


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


def test_feature_model_incremental_training_rows_match_reference_builder():
    history = sample()
    history[1] = Match(
        history[0].date,
        history[1].home,
        history[1].away,
        history[1].home_goals,
        history[1].away_goals,
        history[1].result,
    )
    shuffled = history[::2] + history[1::2]
    model = FeatureModel()

    rows, outcomes = model._training_rows(shuffled)
    ordered = sorted(
        shuffled,
        key=lambda match: (match.date.date().isoformat(), _date_num(match.date)),
    )
    expected_rows = [model._features(shuffled, match) for match in ordered]
    expected_outcomes = [match.outcome() for match in ordered]

    assert np.vstack(rows) == pytest.approx(np.vstack(expected_rows))
    assert outcomes == expected_outcomes


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
    model = FeatureModel()
    rows, outcomes = model._training_rows(history)
    expected = model._features(history, history[1])

    assert len(rows) == len(outcomes) == 80
    assert np.array_equal(rows[1], expected)
    assert first not in [
        match
        for match in history
        if match.home_goals is not None
        and match.away_goals is not None
        and _date_num(match.date) < _date_num(history[1].date)
    ]


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

    predictions = [valid.copy() for _ in range(14)]
    predictions[0]["1"] = True
    with pytest.raises(TypeError, match="invalid probability"):
        TicketOptimizer().optimize(predictions, budget=8)

    predictions = [valid.copy() for _ in range(14)]
    predictions[0] = None
    with pytest.raises(TypeError, match="probabilities must be a mapping"):
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
    with pytest.raises(TypeError, match="positive integer"):
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

def test_optimizer_exposes_independence_estimate_without_renaming_legacy_field():
    predictions = [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)]
    result = TicketOptimizer().optimize(predictions, budget=2)

    assert result["coverage_assumption"] == "independent_matches"
    assert result["coverage_method"] == "product_of_marginal_selected_sign_masses"
    assert result["independent_coverage_estimate"] == pytest.approx(
        result["joint_coverage"]
    )


def test_joint_scenario_coverage_checks_complete_columns_exactly():
    columns = [["1"] * 14, ["2"] * 14]
    scenarios = [["1"] * 14, ["2"] * 14, ["1"] * 13 + ["2"]]

    result = TicketOptimizer.evaluate_joint_scenario_coverage(columns, scenarios)

    assert result["scenario_count"] == 3
    assert result["covered_scenarios"] == 2
    assert result["uncovered_scenarios"] == 1
    assert result["scenario_joint_coverage"] == pytest.approx(2 / 3)
    assert result["coverage_basis"] == "caller_supplied_joint_scenarios"
    assert result["scope"] == "14_main_matches_only"


def test_joint_scenario_coverage_supports_explicit_weights_and_effective_sample_size():
    columns = [["1"] * 14, ["2"] * 14]
    scenarios = [["1"] * 14, ["X"] * 14, ["2"] * 14]

    result = TicketOptimizer.evaluate_joint_scenario_coverage(
        columns,
        scenarios,
        weights=[7, 2, 1],
    )

    assert result["scenario_weighting"] == "explicit"
    assert result["scenario_joint_coverage"] == pytest.approx(0.8)
    assert result["scenario_weight_sum"] == pytest.approx(10.0)
    assert result["covered_scenario_weight"] == pytest.approx(8.0)
    assert result["effective_sample_size"] == pytest.approx(100 / 54)


def test_joint_scenario_coverage_rejects_malformed_columns_and_scenarios():
    with pytest.raises(ValueError, match="exactly 14 signs"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            [["1"] * 13],
            [["1"] * 14],
        )

    with pytest.raises(ValueError, match="invalid 1/X/2 sign"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            [["1"] * 13 + ["A"]],
            [["1"] * 14],
        )

    with pytest.raises(ValueError, match="exactly 14 signs"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            [["1"] * 14],
            [["1"] * 13],
        )

    with pytest.raises(ValueError, match="invalid 1/X/2 sign"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            [["1"] * 14],
            [["1"] * 13 + ["A"]],
        )


def test_joint_scenario_coverage_rejects_invalid_weights():
    columns = [["1"] * 14]
    scenarios = [["1"] * 14, ["2"] * 14]

    with pytest.raises(ValueError, match="weights length"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            columns,
            scenarios,
            weights=[1],
        )

    with pytest.raises(ValueError, match="finite and non-negative"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            columns,
            scenarios,
            weights=[1, -1],
        )

    with pytest.raises(ValueError, match="finite and non-negative"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            columns,
            scenarios,
            weights=[1, float("nan")],
        )

    with pytest.raises(TypeError, match="finite non-negative number"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            columns,
            scenarios,
            weights=[1, True],
        )

    with pytest.raises(ValueError, match="positive total"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            columns,
            scenarios,
            weights=[0, 0],
        )


def test_joint_scenario_coverage_deduplicates_columns_but_keeps_scenario_frequency():
    column = ["1"] * 14
    result = TicketOptimizer.evaluate_joint_scenario_coverage(
        [column, column],
        [column, column, ["2"] * 14],
    )

    assert result["ticket_column_count"] == 2
    assert result["unique_ticket_column_count"] == 1
    assert result["duplicate_ticket_columns"] == 1
    assert result["scenario_count"] == 3
    assert result["unique_scenario_count"] == 2
    assert result["covered_scenarios"] == 2
    assert result["scenario_joint_coverage"] == pytest.approx(2 / 3)

def test_joint_scenario_coverage_scales_extreme_finite_weights_safely():
    columns = [["1"] * 14]
    scenarios = [["1"] * 14, ["2"] * 14]

    for weights in ([1e-300, 1e-300], [1e200, 1e200]):
        result = TicketOptimizer.evaluate_joint_scenario_coverage(
            columns,
            scenarios,
            weights=weights,
        )
        assert result["scenario_joint_coverage"] == pytest.approx(0.5)
        assert result["effective_sample_size"] == pytest.approx(2.0)

    with pytest.raises(ValueError, match="finite positive total"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            columns,
            scenarios,
            weights=[1e308, 1e308],
        )


def test_joint_scenario_coverage_rejects_non_string_outcomes():
    with pytest.raises(ValueError, match="invalid 1/X/2 sign"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            [[1] * 14],
            [["1"] * 14],
        )

    with pytest.raises(ValueError, match="invalid 1/X/2 sign"):
        TicketOptimizer.evaluate_joint_scenario_coverage(
            [["1"] * 14],
            [["1"] * 13 + [2]],
        )

