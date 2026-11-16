from datetime import datetime, timedelta

import numpy as np

from kini_engine import backtest
from kini_engine.backtest import multiclass_metrics
from kini_engine.core import LAE_SOURCE_ID, Match


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
            return type(
                "Prediction", (), {"probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}}
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    day1 = datetime(2025, 1, 1)
    day2 = datetime(2025, 1, 2)
    matches = [Match(day1, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)] + [
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
            return type(
                "Prediction", (), {"probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}}
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    start = datetime(2025, 1, 1)
    matches = [Match(start, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    for day in range(1, 4):
        matches.append(
            Match(start + timedelta(days=day), f"H{day}", f"A{day}", 1, 0, "1")
        )

    backtest.walk_forward(matches, min_train=12, refit_every=2)

    # First forecast date fits, second reuses that fit, third refits.
    assert fitted_sizes == [12, 14]


def test_football_data_snapshot_date_uses_documented_collection_days():
    expected = {
        "2025-01-06": None,
        "2025-01-07": None,
        "2025-01-08": "2025-01-07",
        "2025-01-09": "2025-01-07",
        "2025-01-10": None,
        "2025-01-11": "2025-01-10",
        "2025-01-12": "2025-01-10",
    }
    for fixture_date, snapshot_date in expected.items():
        assert backtest._football_data_snapshot_date(fixture_date) == snapshot_date


def test_market_baseline_uses_only_schedule_screened_rows():
    matches = [
        Match(
            datetime(2025, 1, 3),
            "Ambiguous",
            "A",
            1,
            0,
            "1",
            market={"1": 0.99, "X": 0.005, "2": 0.005},
            detail={
                "market_temporal_status": "ambiguous",
                "market_pre_match_eligible": False,
            },
        ),
        Match(
            datetime(2025, 1, 4),
            "Eligible",
            "B",
            0,
            1,
            "2",
            market={"1": 0.20, "X": 0.30, "2": 0.50},
            detail={
                "market_temporal_status": "schedule_compatible",
                "market_pre_match_eligible": True,
            },
        ),
    ]

    baseline = backtest.baseline_probabilities(matches, source="market")

    assert baseline[0][0] == {"1": 1 / 3, "X": 1 / 3, "2": 1 / 3}
    assert baseline[1][0] == {"1": 0.20, "X": 0.30, "2": 0.50}


def test_lae_baseline_uses_only_temporally_verified_source_vectors():
    valid_lae = {"1": 0.20, "X": 0.30, "2": 0.50}
    unverified_lae = {"1": 0.99, "X": 0.005, "2": 0.005}
    invalid_lae = {"1": 0.40, "X": 0.30, "2": 0.20}
    date = datetime(2025, 1, 3)
    verified_detail = {
        "lae_source": LAE_SOURCE_ID,
        "fixture_identity_status": "verified",
        "lae_captured_at": "2025-01-03T09:00:00+00:00",
        "kickoff_evidence_checked_at_utc": "2025-01-03T08:30:00+00:00",
        "kickoff_evidence_url": "https://www.uefa.com/test-schedule/",
        "kickoff_at": "2025-01-03T20:00:00+00:00",
    }
    matches = [
        Match(date, "Unverified", "A", 1, 0, "1", lae=unverified_lae),
        Match(
            date,
            "Verified",
            "B",
            0,
            1,
            "2",
            lae=valid_lae,
            detail=verified_detail,
        ),
        Match(
            date,
            "Invalid",
            "C",
            0,
            0,
            "X",
            lae=invalid_lae,
            detail=verified_detail,
        ),
    ]

    baseline = backtest.baseline_probabilities(matches, source="lae")

    uniform = {"1": 1 / 3, "X": 1 / 3, "2": 1 / 3}
    assert baseline[0][0] == uniform
    assert baseline[1][0] == valid_lae
    assert baseline[2][0] == uniform


def test_compare_reports_market_metrics_on_same_fixture_sample(monkeypatch):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()
            self.history = []

        def fit(self, history):
            self.history = list(history)
            return self

        def predict(self, match, mode="ensemble", history=None):
            return type(
                "Prediction", (), {"probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}}
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    day1 = datetime(2025, 1, 1)
    day2 = datetime(2025, 1, 2)
    matches = [Match(day1, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)] + [
        Match(
            day2,
            "H12",
            "A12",
            1,
            0,
            "1",
            market={"1": 0.4, "X": 0.3, "2": 0.3},
            detail={
                "market_temporal_status": "schedule_compatible",
                "market_pre_match_eligible": True,
            },
        ),
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
    matches = [Match(day1, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)] + [
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


def test_classwise_one_vs_rest_calibration_reports_reliability_bins():
    rows = [
        ({"1": 0.8, "X": 0.1, "2": 0.1}, "1"),
        ({"1": 0.2, "X": 0.7, "2": 0.1}, "X"),
    ]

    metrics = multiclass_metrics(rows, calibration_bins=2)
    home = metrics["classwise_calibration"]["1"]
    draw = metrics["classwise_calibration"]["X"]

    assert home["n"] == 2
    assert home["prevalence"] == 0.5
    assert home["mean_probability"] == 0.5
    assert abs(home["brier"] - 0.04) < 1e-12
    assert abs(home["logloss"] - 0.2231435513) < 1e-9
    assert abs(home["ece"] - 0.2) < 1e-12
    assert sum(item["count"] for item in home["bins"]) == 2
    assert draw["prevalence"] == 0.5
    assert abs(draw["ece"] - 0.2) < 1e-12


def test_empty_metrics_expose_empty_classwise_calibration():
    metrics = multiclass_metrics([])

    assert metrics["n"] == 0
    assert set(metrics["classwise_calibration"]) == {"1", "X", "2"}
    for diagnostics in metrics["classwise_calibration"].values():
        assert diagnostics["n"] == 0
        assert diagnostics["prevalence"] is None
        assert diagnostics["mean_probability"] is None
        assert diagnostics["ece"] is None
        assert diagnostics["bins"] == []


def test_compare_reports_out_of_sample_classwise_calibration_by_season(monkeypatch):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()
            self.history = []

        def fit(self, history):
            self.history = list(history)
            return self

        def predict(self, match, mode="ensemble", history=None):
            return type(
                "Prediction", (), {"probabilities": {"1": 0.6, "X": 0.25, "2": 0.15}}
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    training_day = datetime(2024, 6, 30)
    matches = [Match(training_day, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    matches.extend(
        [
            Match(
                datetime(2024, 7, 1),
                "H12",
                "A12",
                1,
                0,
                "1",
                market={"1": 0.5, "X": 0.3, "2": 0.2},
                detail={
                    "market_temporal_status": "schedule_compatible",
                    "market_pre_match_eligible": True,
                },
            ),
            Match(
                datetime(2025, 7, 1),
                "H13",
                "A13",
                0,
                0,
                "X",
                market={"1": 0.4, "X": 0.35, "2": 0.25},
                detail={
                    "market_temporal_status": "schedule_compatible",
                    "market_pre_match_eligible": True,
                },
            ),
        ]
    )

    result = backtest.compare_walk_forward(matches, min_train=12)

    dc_seasons = result["temporal_classwise_calibration"]["dc"]
    assert set(dc_seasons) == {"2024/25", "2025/26"}
    assert dc_seasons["2024/25"]["n"] == 1
    assert dc_seasons["2025/26"]["n"] == 1
    assert dc_seasons["2024/25"]["classes"]["1"]["prevalence"] == 1.0
    assert dc_seasons["2025/26"]["classes"]["X"]["prevalence"] == 1.0

    common = result["temporal_common_sample_calibration"]["dc"]
    assert common["model"]["2024/25"]["n"] == 1
    assert common["market"]["2024/25"]["n"] == 1
    assert common["model"]["2025/26"]["n"] == 1
    assert common["market"]["2025/26"]["n"] == 1


def test_multiclass_calibrator_is_identity_until_history_is_sufficient():
    probabilities = {"1": 0.5, "X": 0.3, "2": 0.2}
    history = [(probabilities, "1"), (probabilities, "X")]

    calibrator = backtest.fit_multiclass_calibrator(
        history,
        min_history=3,
        window=3,
        min_class_count=1,
    )

    assert calibrator["fitted"] is False
    assert calibrator["reason"] == "insufficient_history"
    assert (
        backtest.apply_multiclass_calibrator(probabilities, calibrator) == probabilities
    )


def test_prequential_multiclass_calibrator_improves_biased_holdout_logloss():
    rng = np.random.default_rng(123)
    n = 1200
    signs = ("1", "X", "2")
    true_probabilities = rng.dirichlet([4.0, 2.5, 2.5], size=n)
    outcomes = np.asarray(
        [rng.choice(3, p=probability) for probability in true_probabilities]
    )

    # Simulate a stable class-prior and sharpness distortion.
    logits = 1.15 * np.log(true_probabilities) + np.asarray([-0.18, 0.04, 0.14])
    logits -= logits.max(axis=1, keepdims=True)
    raw_probabilities = np.exp(logits)
    raw_probabilities /= raw_probabilities.sum(axis=1, keepdims=True)

    training_rows = [
        (
            dict(zip(signs, map(float, raw_probabilities[index]))),
            signs[int(outcomes[index])],
        )
        for index in range(700)
    ]
    holdout_rows = [
        (
            dict(zip(signs, map(float, raw_probabilities[index]))),
            signs[int(outcomes[index])],
        )
        for index in range(700, n)
    ]

    calibrator = backtest.fit_multiclass_calibrator(
        training_rows,
        min_history=700,
        window=700,
        regularization=0.05,
        min_class_count=20,
    )
    assert calibrator["fitted"] is True
    assert calibrator["n_train"] == 700

    raw_logloss = multiclass_metrics(holdout_rows)["logloss"]
    calibrated_rows = [
        (
            backtest.apply_multiclass_calibrator(probabilities, calibrator),
            outcome,
        )
        for probabilities, outcome in holdout_rows
    ]
    calibrated_logloss = multiclass_metrics(calibrated_rows)["logloss"]

    assert calibrated_logloss < raw_logloss
    for probabilities, _ in calibrated_rows:
        assert abs(sum(probabilities.values()) - 1.0) < 1e-12
        assert all(0.0 <= value <= 1.0 for value in probabilities.values())


def test_compare_fits_calibrator_only_from_completed_prior_dates(monkeypatch):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()

        def fit(self, history):
            return self

        def predict(self, match, mode="ensemble", history=None):
            return type(
                "Prediction", (), {"probabilities": {"1": 0.50, "X": 0.30, "2": 0.20}}
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    start = datetime(2025, 1, 1)
    matches = [Match(start, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    matches.extend(
        [
            Match(datetime(2025, 1, 2), "H12", "A12", 1, 0, "1"),
            Match(datetime(2025, 1, 2), "H13", "A13", 0, 0, "X"),
            Match(datetime(2025, 1, 2), "H14", "A14", 0, 1, "2"),
            Match(datetime(2025, 1, 3), "H15", "A15", 1, 0, "1"),
            Match(datetime(2025, 1, 3), "H16", "A16", 0, 0, "X"),
            Match(datetime(2025, 1, 4), "H17", "A17", 0, 1, "2"),
        ]
    )

    result = backtest.compare_walk_forward(
        matches,
        min_train=12,
        calibration_min_history=3,
        calibration_window=10,
        calibration_refit_every=1,
        calibration_regularization=0.05,
        calibration_min_class_count=1,
        adaptive_min_history=1,
        adaptive_window=10,
    )

    summary = result["prequential_calibration"]["models"]["dc"]
    # The final fit is made before 4 January: it can see only the three
    # forecasts from 2 January and two from 3 January, never 4 January's result.
    assert summary["last_fit"]["fit_date"] == "2025-01-04"
    assert summary["last_fit"]["n_train"] == 5
    assert summary["n"] == 3
    assert (
        result["prequential_calibration"]["same_calendar_day_outcomes_excluded"] is True
    )


def test_compare_excludes_ambiguous_and_unknown_market_rows_from_strict_sample(
    monkeypatch,
):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()

        def fit(self, history):
            return self

        def predict(self, match, mode="ensemble", history=None):
            return type(
                "Prediction", (), {"probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}}
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    training_day = datetime(2025, 1, 1)
    forecast_day = datetime(2025, 1, 2)
    training = [Match(training_day, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    market = {"1": 0.4, "X": 0.3, "2": 0.3}
    fixtures = [
        Match(
            forecast_day,
            "Eligible",
            "A",
            1,
            0,
            "1",
            market=market,
            detail={
                "market_temporal_status": "schedule_compatible",
                "market_pre_match_eligible": True,
                "kickoff_time": "20:00",
            },
        ),
        Match(
            forecast_day,
            "Ambiguous",
            "B",
            0,
            0,
            "X",
            market=market,
            detail={
                "market_temporal_status": "ambiguous",
                "market_pre_match_eligible": False,
                "kickoff_time": "16:30",
            },
        ),
        Match(
            forecast_day,
            "Unknown",
            "C",
            0,
            1,
            "2",
            market=market,
            detail={
                "market_temporal_status": "unknown",
                "market_pre_match_eligible": False,
            },
        ),
    ]

    result = backtest.compare_walk_forward(training + fixtures, min_train=12)

    assert result["market"]["n"] == 1
    assert result["market_unfiltered_snapshot"]["n"] == 3
    assert result["market_temporal_audit"]["n_with_odds"] == 3
    assert result["market_temporal_audit"]["n_schedule_eligible"] == 1
    assert result["market_temporal_audit"]["n_excluded"] == 2
    assert result["market_temporal_audit"]["status_counts"] == {
        "ambiguous": 1,
        "schedule_compatible": 1,
        "unknown": 1,
    }
    assert result["common_sample"]["dc"]["market"]["n"] == 1


def test_compare_builds_a_conservative_common_information_time_market_sample(
    monkeypatch,
):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()

        def fit(self, history):
            return self

        def predict(self, match, mode="ensemble", history=None):
            probabilities = {
                "dc": {"1": 0.6, "X": 0.25, "2": 0.15},
                "ml": {"1": 0.4, "X": 0.35, "2": 0.25},
                "ensemble": {"1": 0.52, "X": 0.28, "2": 0.20},
                "ensemble_dc_ml": {"1": 0.5, "X": 0.3, "2": 0.2},
            }
            return type("Prediction", (), {"probabilities": probabilities[mode]})()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    start = datetime(2025, 1, 1)
    training = [Match(start, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    eligible = {
        "market_temporal_status": "schedule_compatible",
        "market_pre_match_eligible": True,
    }
    market = {"1": 0.45, "X": 0.30, "2": 0.25}
    bet365 = {"1": 0.50, "X": 0.28, "2": 0.22}
    matches = training + [
        Match(datetime(2025, 1, 3), "Friday", "A", 1, 0, "1"),
        Match(
            datetime(2025, 1, 4),
            "Saturday",
            "A",
            1,
            0,
            "1",
            market=market,
            detail={**eligible},
        ),
        Match(
            datetime(2025, 1, 8),
            "Wednesday",
            "A",
            0,
            0,
            "X",
            market=market,
            detail={
                **eligible,
                "market_bookmaker_probabilities": {"bet365": bet365},
            },
        ),
        Match(
            datetime(2025, 1, 9),
            "Thursday",
            "A",
            0,
            1,
            "2",
            market=market,
            detail={
                **eligible,
                "market_bookmaker_probabilities": {"bet365": bet365},
            },
        ),
    ]

    result = backtest.compare_walk_forward(matches, min_train=12)
    rows_by_home = {row["home"]: row for row in result["forecast_rows"]}
    strict = result["strict_common_time_market"]
    strict_bet365 = result["strict_common_time_bet365"]

    assert rows_by_home["Saturday"]["market_snapshot_date"] == "2025-01-03"
    assert rows_by_home["Saturday"]["strict_common_time_eligible"] is False
    assert (
        rows_by_home["Saturday"]["strict_common_time_exclusion_reason"]
        == "training_cutoff_not_before_snapshot"
    )
    assert rows_by_home["Wednesday"]["market_snapshot_date"] == "2025-01-07"
    assert rows_by_home["Wednesday"]["strict_common_time_eligible"] is True
    assert rows_by_home["Wednesday"]["strict_common_time_exclusion_reason"] is None
    assert rows_by_home["Thursday"]["market_snapshot_date"] == "2025-01-07"
    assert rows_by_home["Thursday"]["strict_common_time_eligible"] is False
    assert strict["n_schedule_eligible"] == 3
    assert strict["n_common_time_eligible"] == 1
    assert strict["n_excluded_from_common_time_sample"] == 2
    assert strict["exclusion_reason_counts"] == {
        "training_cutoff_not_before_snapshot": 2
    }
    assert strict["market"]["n"] == 1
    for mode in (
        "dc",
        "ml",
        "ensemble",
        "ensemble_dc_ml",
        "ensemble_dc_ml_adaptive",
    ):
        assert strict["common_sample"][mode]["n"] == 1
        assert strict["common_sample"][mode]["model"]["n"] == 1
        assert strict["common_sample"][mode]["market"]["n"] == 1

    assert strict_bet365["n_schedule_eligible"] == 2
    assert strict_bet365["n_common_time_eligible"] == 1
    assert strict_bet365["metrics"]["n"] == 1
    for mode in (
        "dc",
        "ml",
        "ensemble",
        "ensemble_dc_ml",
        "ensemble_dc_ml_adaptive",
    ):
        sample = strict_bet365["common_sample"][mode]
        assert sample["n"] == 1
        assert sample["model"]["n"] == 1
        assert sample["market_consensus"]["n"] == 1
        assert sample["bet365"]["n"] == 1


def test_compare_reports_unseen_team_cold_start_fallbacks_per_model(monkeypatch):
    class FakeDC:
        decay = 0.995

        @staticmethod
        def prediction_source(home, away):
            return (
                "unseen_team_fallback" if "New Club" in {home, away} else "dixon_coles"
            )

    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = FakeDC()
            self.history = []

        def fit(self, history):
            self.history = list(history)
            return self

        def predict(self, match, mode="ensemble", history=None):
            return type(
                "Prediction", (), {"probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}}
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    training_day = datetime(2025, 1, 1)
    forecast_day = datetime(2025, 1, 2)
    training = [Match(training_day, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    fixtures = [
        Match(
            forecast_day,
            "New Club",
            "A",
            1,
            0,
            "1",
            detail={"League": "la-liga", "Season": "2627"},
        ),
        Match(
            forecast_day,
            "Known Club",
            "B",
            0,
            0,
            "X",
            detail={"League": "la-liga", "Season": "2627"},
        ),
        Match(
            forecast_day,
            "New Club",
            "C",
            1,
            0,
            "1",
            detail={"League": "segunda", "Season": "2627"},
        ),
        Match(
            forecast_day,
            "Known Club",
            "D",
            0,
            0,
            "X",
            detail={"League": "segunda", "Season": "2627"},
        ),
    ]

    result = backtest.compare_walk_forward(
        training + fixtures,
        min_train=12,
    )

    summaries = result["cold_start_fallbacks"]["models"]
    expected_seasons = [
        {
            "league": "la-liga",
            "season_code": "2627",
            "season_label": "2026/27",
            "n_predictions": 2,
            "count": 1,
            "rate": 0.5,
        },
        {
            "league": "segunda",
            "season_code": "2627",
            "season_label": "2026/27",
            "n_predictions": 2,
            "count": 1,
            "rate": 0.5,
        },
    ]
    expected_examples = [
        {"date": "2025-01-02", "home": "New Club", "away": "A"},
        {"date": "2025-01-02", "home": "New Club", "away": "C"},
    ]

    for mode in ("dc", "ensemble", "ensemble_dc_ml", "ensemble_dc_ml_adaptive"):
        assert summaries[mode]["n_predictions"] == 4
        assert summaries[mode]["count"] == 2
        assert summaries[mode]["rate"] == 0.5
        assert summaries[mode]["examples"] == expected_examples
        assert summaries[mode]["by_season"] == expected_seasons

    assert summaries["ml"]["n_predictions"] == 4
    assert summaries["ml"]["count"] == 0
    assert summaries["ml"]["rate"] == 0.0
    assert summaries["ml"]["examples"] == []
    assert summaries["ml"]["by_season"] == [
        {**season, "count": 0, "rate": 0.0} for season in expected_seasons
    ]


def test_season_identity_uses_source_codes_and_keeps_missing_metadata_explicit():
    match = Match(
        datetime(2025, 1, 1),
        "A",
        "B",
        detail={"League": "la-liga", "Season": "2021"},
    )
    assert backtest._season_identity(match) == ("la-liga", "2021", "2020/21")

    unknown = Match(datetime(2025, 1, 1), "A", "B")
    assert backtest._season_identity(unknown) == ("unknown", "unknown", "unknown")


def test_compare_reports_bet365_on_its_exact_common_fixture_sample(monkeypatch):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()

        def fit(self, history):
            return self

        def predict(self, match, mode="ensemble", history=None):
            return type(
                "Prediction",
                (),
                {"probabilities": {"1": 0.5, "X": 0.3, "2": 0.2}},
            )()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    training_day = datetime(2025, 1, 1)
    forecast_day = datetime(2025, 1, 2)
    training = [Match(training_day, f"H{i}", f"A{i}", 1, 0, "1") for i in range(12)]
    consensus = {"1": 0.45, "X": 0.30, "2": 0.25}
    bet365_a = {"1": 0.50, "X": 0.28, "2": 0.22}
    bet365_b = {"1": 0.35, "X": 0.33, "2": 0.32}
    eligible = {
        "market_temporal_status": "schedule_compatible",
        "market_pre_match_eligible": True,
    }
    matches = training + [
        Match(
            forecast_day,
            "B365 One",
            "A",
            1,
            0,
            "1",
            market=consensus,
            detail={**eligible, "market_bookmaker_probabilities": {"bet365": bet365_a}},
        ),
        Match(
            forecast_day,
            "No B365",
            "B",
            0,
            0,
            "X",
            market=consensus,
            detail=eligible,
        ),
        Match(
            forecast_day,
            "B365 Ambiguous",
            "C",
            0,
            1,
            "2",
            market=consensus,
            detail={
                "market_temporal_status": "ambiguous",
                "market_pre_match_eligible": False,
                "market_bookmaker_probabilities": {"bet365": bet365_b},
            },
        ),
        Match(
            forecast_day,
            "B365 Two",
            "D",
            0,
            0,
            "X",
            market=consensus,
            detail={**eligible, "market_bookmaker_probabilities": {"bet365": bet365_b}},
        ),
        Match(
            forecast_day,
            "Malformed B365",
            "E",
            2,
            0,
            "1",
            market=consensus,
            detail={
                **eligible,
                "market_bookmaker_probabilities": {
                    "bet365": {"1": 0.6, "X": 0.2, "2": 0.3}
                },
            },
        ),
    ]

    result = backtest.compare_walk_forward(matches, min_train=12)
    benchmark = result["bookmaker_benchmarks"]["bet365"]

    assert benchmark["n_with_odds"] == 3
    assert benchmark["n_schedule_eligible"] == 2
    assert benchmark["n_excluded"] == 1
    assert benchmark["status_counts"] == {
        "ambiguous": 1,
        "schedule_compatible": 2,
    }
    assert benchmark["metrics"]["n"] == 2
    for mode in (
        "dc",
        "ml",
        "ensemble",
        "ensemble_dc_ml",
        "ensemble_dc_ml_adaptive",
    ):
        sample = benchmark["common_sample"][mode]
        assert sample["n"] == 2
        assert sample["model"]["n"] == 2
        assert sample["market_consensus"]["n"] == 2
        assert sample["bet365"]["n"] == 2


def test_compare_exports_fixture_level_forecast_rows(monkeypatch):
    class FakeEngine:
        def __init__(self, enable_ml=False):
            self.dc = type("DC", (), {"decay": 0.995})()

        def fit(self, history):
            return self

        def predict(self, match, mode="ensemble", history=None):
            vectors = {
                "dc": {"1": 0.6, "X": 0.25, "2": 0.15},
                "ml": {"1": 0.4, "X": 0.35, "2": 0.25},
                "ensemble": {"1": 0.52, "X": 0.28, "2": 0.20},
                "ensemble_dc_ml": {"1": 0.5, "X": 0.3, "2": 0.2},
            }
            return type("Prediction", (), {"probabilities": vectors[mode]})()

    monkeypatch.setattr(backtest, "KiniEngine", FakeEngine)
    training_day = datetime(2025, 1, 1)
    forecast_day = datetime(2025, 1, 2)
    training = [
        Match(
            training_day,
            f"Home {index}",
            f"Away {index}",
            1,
            0,
            "1",
            detail={
                "League": "la-liga",
                "Season": "2526",
                "Div": "SP1",
                "SourceURL": "https://www.football-data.co.uk/mmz4281/2526/SP1.csv",
            },
        )
        for index in range(12)
    ]
    eligible_market = {
        "market_temporal_status": "schedule_compatible",
        "market_pre_match_eligible": True,
    }
    market_vector = {"1": 0.45, "X": 0.3, "2": 0.25}
    fixtures = [
        Match(
            forecast_day,
            "Home A",
            "Away A",
            1,
            0,
            "1",
            market=market_vector,
            detail={
                **eligible_market,
                "League": "la-liga",
                "Season": "2526",
                "Div": "SP1",
                "SourceURL": "https://www.football-data.co.uk/mmz4281/2526/SP1.csv",
            },
        ),
        Match(
            forecast_day,
            "Home B",
            "Away B",
            0,
            0,
            "X",
            detail={
                "League": "la-liga",
                "Season": "2526",
                "Div": "SP1",
                "SourceURL": "https://www.football-data.co.uk/mmz4281/2526/SP1.csv",
            },
        ),
    ]

    result = backtest.compare_walk_forward(training + fixtures, min_train=12)
    rows = result["forecast_rows"]

    assert result["n_total"] == 2
    assert len(rows) == 2
    assert len({row["fixture_id"] for row in rows}) == 2
    assert [row["forecast_index"] for row in rows] == [1, 2]
    for row, actual in zip(rows, ("1", "X")):
        assert row["actual_result"] == actual
        assert row["forecast_as_of_date"] == "2025-01-02"
        assert row["training_cutoff_date"] == "2025-01-01"
        assert row["model_fit_cutoff_date"] == "2025-01-01"
        assert row["training_match_count"] == 12
        assert row["model_fit_match_count"] == 12
        assert set(row["model_probabilities"]) == {
            "dc",
            "ml",
            "ensemble",
            "ensemble_dc_ml",
            "ensemble_dc_ml_adaptive",
        }
        for vector in row["model_probabilities"].values():
            assert abs(sum(vector.values()) - 1.0) < 1e-9

    assert rows[0]["market_eligible"] is True
    assert rows[0]["market_probabilities"] == market_vector
    assert rows[1]["market_eligible"] is False
    assert rows[1]["market_probabilities"] is None
