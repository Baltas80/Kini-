from __future__ import annotations

import math
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import pytest

from kini_engine import coupons
from kini_engine.core import SIGNS, Match, TicketOptimizer
from scripts.backtest_coupons import validate_coupon_backtest_acceptance


def _fixture_rows() -> list[dict[str, object]]:
    rows = []
    for number in range(1, 16):
        home_goals = 4 if number == 15 else (1 if number % 3 else 0)
        away_goals = 0 if number == 15 else (0 if number % 3 else 1)
        result = coupons._result_from_score(home_goals, away_goals)
        kickoff = datetime(2020, 12, 12, 14, 0, tzinfo=coupons.SPAIN_TIMEZONE)
        kickoff += timedelta(hours=number - 1)
        rows.append(
            {
                "number": number,
                "kickoff_at": kickoff.isoformat(),
                "home": f"Home {number}",
                "away": f"Away {number}",
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result": result,
                "pleno_home_category": coupons._pleno_category(home_goals)
                if number == 15
                else None,
                "pleno_away_category": coupons._pleno_category(away_goals)
                if number == 15
                else None,
            }
        )
    return rows


def _coupon_html(rows: list[dict[str, object]]) -> str:
    body = []
    for row in rows:
        number = int(row["number"])
        sign = (
            f"{row['pleno_home_category']} - {row['pleno_away_category']}"
            if number == 15
            else str(row["result"])
        )
        kickoff = datetime.fromisoformat(str(row["kickoff_at"])).strftime(
            "%d/%m/%Y, %H:%M"
        )
        body.append(
            "<tr>"
            f"<td>{number}</td><td>{kickoff}</td>"
            f"<td><a href='/team/home-{number}'>{row['home']}</a>"
            f"<a href='/score/{number}'>{row['home_goals']} {row['away_goals']}</a>"
            f"<a href='/team/away-{number}'>{row['away']}</a></td>"
            f"<td>{sign}</td></tr>"
        )
    return (
        "<html><body><h1>Jornada 21</h1><div>Fecha 13/12/2020, 22:57</div>"
        "<table><thead><tr><th>#</th><th>Fecha</th><th>Encuentro</th><th>Signo</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></body></html>"
    )


def _official_html(rows: list[dict[str, object]]) -> str:
    def ul(values: list[str]) -> str:
        return "<ul>" + "".join(f"<li>{value}</li>" for value in values) + "</ul>"

    main = rows[:14]
    groups = [
        [str(index) for index in range(1, 15)],
        [str(row["home"]) for row in main],
        [str(row["away"]) for row in main],
        [f"{row['home_goals']}-{row['away_goals']}" for row in main],
        [str(row["result"]) for row in main],
    ]
    pleno = rows[14]
    pleno_values = [
        "15",
        str(pleno["home"]),
        str(pleno["away"]),
        f"{pleno['home_goals']}-{pleno['away_goals']}",
        f"{pleno['pleno_home_category']} - {pleno['pleno_away_category']}",
    ]
    return (
        "<html><body>"
        + "".join(ul(group) for group in groups)
        + ul(pleno_values)
        + "</body></html>"
    )


def _verified_coupon() -> dict[str, object]:
    rows = _fixture_rows()
    coupon = coupons.parse_historicoquiniela_coupon_html(
        _coupon_html(rows),
        season="2020-2021",
        jornada=21,
        source_url="https://www.historicoquiniela.com/historico/2020-2021/21",
        source_sha256="a" * 64,
        retrieved_at_utc="2026-11-16T20:00:00+00:00",
    )
    return coupons.verify_coupon_against_selae(
        coupon,
        _official_html(rows),
        official_url="https://www.loteriasyapuestas.es/example",
        official_sha256="b" * 64,
    )


def test_parse_historical_coupon_and_common_cutoff() -> None:
    coupon = _verified_coupon()
    assert coupon["official_main_matches_verified"] is True
    assert coupon["official_pleno_verified"] is True
    assert len(coupon["fixtures"]) == 15
    assert coupon["training_cutoff_date"] == "2020-12-11"
    assert coupon["first_kickoff_at"].startswith("2020-12-12T14:00:00")
    assert coupon["source_date"] == "2020-12-13"
    assert coupon["source_date_label_at"] == "2020-12-13T22:57:00+01:00"
    assert "result_published_at" not in coupon
    coupons.validate_coupon_record(coupon)


def test_official_reconciliation_rejects_wrong_fixture_order() -> None:
    rows = _fixture_rows()
    coupon = coupons.parse_historicoquiniela_coupon_html(
        _coupon_html(rows),
        season="2020-2021",
        jornada=21,
        source_url="https://www.historicoquiniela.com/historico/2020-2021/21",
        source_sha256="a" * 64,
        retrieved_at_utc="2026-11-16T20:00:00+00:00",
    )
    official_rows = rows.copy()
    official_rows[0], official_rows[1] = official_rows[1], official_rows[0]
    result = coupons.verify_coupon_against_selae(
        coupon,
        _official_html(official_rows),
        official_url="https://www.loteriasyapuestas.es/example",
        official_sha256="b" * 64,
    )
    assert result["official_main_matches_verified"] is False
    with pytest.raises(ValueError, match="not verified"):
        coupons.validate_coupon_record(result)


def test_journey_extraction_and_official_url() -> None:
    index = (
        "<html><a href='/historico/2020-2021/21'>Jornada 21</a>"
        "<a href='https://www.historicoquiniela.com/historico/2020-2021/22'>Jornada 22</a></html>"
    )
    assert coupons.extract_historical_journeys(index, season="2020-2021") == [21, 22]
    url = coupons.selae_result_url("2020-12-13")
    assert url.endswith("la-quiniela-resultados-del-13-de-diciembre-de-2020")


def test_coupon_jsonl_round_trip_is_immutable(tmp_path: Path) -> None:
    coupon = _verified_coupon()
    target = tmp_path / "coupons.jsonl"
    manifest = {"source": "test", "coupon_count": 1}
    assert coupons.write_coupon_jsonl(target, [coupon], manifest) == 1
    loaded_manifest, loaded = coupons.read_coupon_jsonl(target)
    assert loaded_manifest["coupon_count"] == 1
    assert loaded[0]["coupon_id"] == coupon["coupon_id"]
    with pytest.raises(FileExistsError):
        coupons.write_coupon_jsonl(target, [coupon], manifest)


def test_coupon_backtest_uses_only_results_before_first_kickoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coupon = _verified_coupon()
    cutoff_history = [
        Match(datetime(2020, 1, 1) + timedelta(days=index), "H", "A", 1, 0, "1")
        for index in range(300)
    ]
    same_day = Match(datetime(2020, 12, 12), "SameDay", "Opponent", 3, 0, "1")
    captured: dict[str, int] = {}

    class FakeDC:
        fitted = True
        n_training_matches = 300
        fit_error = None
        fit_status = "fitted"

        def pleno15_probs(
            self, home: str, away: str, **kwargs: object
        ) -> list[dict[str, object]]:
            return [
                {"home_goals": "M", "away_goals": "0", "probability": 0.2},
                {"home_goals": "1", "away_goals": "0", "probability": 0.1},
            ]

    class FakeEngine:
        def __init__(self, enable_ml: bool = False) -> None:
            assert enable_ml is True
            self.dc = FakeDC()
            self.optimizer = TicketOptimizer()

        def fit(self, history: list[Match]) -> FakeEngine:
            captured["history_count"] = len(history)
            return self

        def predict(self, fixture: Match, mode: str = "ensemble") -> SimpleNamespace:
            values = {
                "dc": {"1": 0.6, "X": 0.25, "2": 0.15},
                "ml": {"1": 0.4, "X": 0.3, "2": 0.3},
                "ensemble_dc_ml": {"1": 0.5, "X": 0.3, "2": 0.2},
            }[mode]
            return SimpleNamespace(probabilities=values)

    monkeypatch.setattr(coupons, "KiniEngine", FakeEngine)
    result = coupons.evaluate_coupon(
        coupon,
        cutoff_history + [same_day],
        budget=8,
        min_history_matches=300,
    )
    assert captured["history_count"] == 300
    assert result["training_cutoff_date"] == "2020-12-11"
    assert result["pleno_prediction"]["model"] == "dixon_coles"
    assert (
        result["pleno_prediction"]["selection_method"]
        == "max_aggregated_category_pair_probability"
    )
    assert result["pleno_prediction"]["training_match_count"] == 300
    assert result["models"]["dc"]["status"] == "success"
    assert result["models"]["dc"]["n_predictions"] == 14
    assert result["models"]["dc"]["cost_eur"] > 0
    assert result["models"]["dc"]["total_bets"] <= 31_104
    assert (
        len(result["models"]["dc"]["columns"]) == result["models"]["dc"]["column_count"]
    )
    assert result["models"]["dc"]["total_bets"] == (
        result["models"]["dc"]["column_count"]
        * result["models"]["dc"]["pleno15_multiplier"]
    )
    assert result["models"]["dc"]["cost_eur"] == pytest.approx(
        result["models"]["dc"]["total_bets"]
        * result["models"]["dc"]["price_per_bet_eur"]
    )
    assert result["actual_main_results"] == [
        fixture["result"] for fixture in coupon["fixtures"][:14]
    ]


def test_coupon_batch_does_not_swallow_unexpected_programming_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_error(*args: object, **kwargs: object) -> None:
        raise AttributeError("unexpected programming defect")

    monkeypatch.setattr(coupons, "evaluate_coupon", unexpected_error)
    with pytest.raises(AttributeError, match="unexpected programming defect"):
        coupons.evaluate_coupon_batch([{"coupon_id": "2020-2021:21"}], [])


def _accepted_coupon_backtest_result() -> tuple[dict[str, object], list[str]]:
    coupon = _verified_coupon()
    coupon_id = str(coupon["coupon_id"])
    actual_main_results = [fixture["result"] for fixture in coupon["fixtures"][:14]]
    actual_pleno = {
        "home": coupon["fixtures"][14]["pleno_home_category"],
        "away": coupon["fixtures"][14]["pleno_away_category"],
    }

    selected_by_fixture = []
    for index, actual in enumerate(actual_main_results):
        if index < 3:
            selected_by_fixture.append(("1", "X"))
        elif index < 9:
            selected_by_fixture.append((actual,))
        else:
            selected_by_fixture.append(
                (next(sign for sign in SIGNS if sign != actual),)
            )
    columns = [
        list(prefix) + [selected[0] for selected in selected_by_fixture[3:]]
        for prefix in product(*selected_by_fixture[:3])
    ]

    vectors = []
    for index, actual in enumerate(actual_main_results):
        predicted = (
            actual if index < 7 else next(sign for sign in SIGNS if sign != actual)
        )
        ordered = [predicted] + [sign for sign in SIGNS if sign != predicted]
        vectors.append({ordered[0]: 0.6, ordered[1]: 0.25, ordered[2]: 0.15})

    selected_signs = [{column[index] for column in columns} for index in range(14)]
    independent_coverage = math.prod(
        sum(vectors[index][sign] for sign in selected_signs[index])
        for index in range(14)
    )
    actual_vector = tuple(actual_main_results)
    best_column_hits = max(
        sum(sign == actual_vector[index] for index, sign in enumerate(column))
        for column in columns
    )
    single_sign_hits = sum(
        max(SIGNS, key=vectors[index].__getitem__) == actual_vector[index]
        for index in range(14)
    )
    covered_14 = actual_vector in {tuple(column) for column in columns}

    model_result = {
        "status": "success",
        "n_predictions": 14,
        "probabilities": vectors,
        "columns": columns,
        "single_sign_hits": single_sign_hits,
        "best_column_hits": best_column_hits,
        "covered_14": covered_14,
        "pleno_hit": False,
        "full_coupon_covered": False,
        "column_count": 8,
        "total_bets": 8,
        "double_count": 3,
        "triple_count": 0,
        "minimum_total_bets": 2,
        "maximum_authorized_total_bets": 31_104,
        "pleno15_multiplier": 1,
        "pleno15_home_categories": ["0"],
        "pleno15_away_categories": ["M"],
        "price_per_bet_eur": 0.75,
        "cost_eur": 6.0,
        "independent_14_coverage_estimate": independent_coverage,
        "pleno_model": "dixon_coles",
        "pleno_selected_home_category": "0",
        "pleno_selected_away_category": "M",
        "pleno_selected_probability_mass": 0.2,
    }
    reconciliation = [
        {
            "number": fixture["number"],
            "home_goals": fixture["home_goals"],
            "away_goals": fixture["away_goals"],
            "result": fixture["result"],
            "pleno_home_category": fixture.get("pleno_home_category"),
            "pleno_away_category": fixture.get("pleno_away_category"),
        }
        for fixture in coupon["fixtures"]
    ]
    coupon_result = {
        "coupon_id": coupon_id,
        "official_main_matches_verified": True,
        "official_pleno_verified": True,
        "fixture_reconciliation_count": 15,
        "fixture_reconciliation": reconciliation,
        "actual_main_results": actual_main_results,
        "actual_pleno_categories": actual_pleno,
        "first_kickoff_at": coupon["first_kickoff_at"],
        "training_cutoff_date": coupon["training_cutoff_date"],
        "training_match_count": 303,
        "model_fit_match_count": 303,
        "pleno_prediction": {
            "model": "dixon_coles",
            "selection_method": "max_aggregated_category_pair_probability",
            "home_category": "0",
            "away_category": "M",
            "probability_mass": 0.2,
            "training_match_count": 303,
        },
        "models": {
            mode: {
                **model_result,
                "probabilities": [vector.copy() for vector in vectors],
                "columns": [column.copy() for column in columns],
            }
            for mode in ("dc", "ml", "ensemble_dc_ml")
        },
    }
    summary_models = {
        mode: {"evaluated_coupons": 1, "failed_coupons": 0}
        for mode in ("dc", "ml", "ensemble_dc_ml")
    }
    return (
        {
            "schema_version": 2,
            "config": {"budget_columns": 8, "min_history_matches": 300},
            "summary": {"coupon_count": 1, "models": summary_models},
            "coupons": [coupon_result],
        },
        [coupon_id],
    )


def test_coupon_backtest_acceptance_requires_all_models_and_valid_vectors() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    validate_coupon_backtest_acceptance(
        result,
        coupon_ids,
        budget=8,
        min_history_matches=300,
    )


@pytest.mark.parametrize("mode", ["dc", "ml", "ensemble_dc_ml"])
def test_coupon_backtest_acceptance_rejects_failed_model(mode: str) -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"][mode]["status"] = "failed"
    with pytest.raises(ValueError, match=mode):
        validate_coupon_backtest_acceptance(
            result,
            coupon_ids,
            budget=8,
            min_history_matches=300,
        )


def test_coupon_backtest_acceptance_rejects_invalid_probability_vector() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["ml"]["probabilities"][0]["X"] = 0.9
    with pytest.raises(ValueError, match="ml fixture 1"):
        validate_coupon_backtest_acceptance(
            result,
            coupon_ids,
            budget=8,
            min_history_matches=300,
        )


def test_coupon_backtest_acceptance_rejects_incomplete_model_aggregate() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["summary"]["models"]["ensemble_dc_ml"] = {
        "evaluated_coupons": 0,
        "failed_coupons": 1,
    }
    with pytest.raises(ValueError, match="ensemble_dc_ml"):
        validate_coupon_backtest_acceptance(
            result,
            coupon_ids,
            budget=8,
            min_history_matches=300,
        )


def test_coupon_backtest_acceptance_rejects_non_boolean_coverage_flag() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["covered_14"] = "false"
    with pytest.raises(TypeError, match="covered_14"):
        validate_coupon_backtest_acceptance(
            result,
            coupon_ids,
            budget=8,
            min_history_matches=300,
        )


def test_coupon_backtest_acceptance_rejects_missing_persisted_columns() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["columns"].pop()
    with pytest.raises(ValueError, match="persisted direct columns"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_rejects_incomplete_multiple_system() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["ml"]["double_count"] = 2
    with pytest.raises(ValueError, match="2\\^d \\* 3\\^t"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_rejects_duplicate_direct_columns() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    columns = result["coupons"][0]["models"]["ensemble_dc_ml"]["columns"]
    columns[-1] = columns[0].copy()
    with pytest.raises(ValueError, match="duplicate direct columns"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_rejects_pleno_multiplier_mismatch() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["pleno15_multiplier"] = 2
    with pytest.raises(ValueError, match="Pleno multiplier"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_rejects_total_bet_or_cost_mismatch() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["total_bets"] = 9
    with pytest.raises(ValueError, match="total bets do not equal"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )

    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["cost_eur"] = 6.01
    with pytest.raises(ValueError, match="ticket cost"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_recomputes_realized_coverage_and_hits() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["covered_14"] = True
    with pytest.raises(ValueError, match="covered_14"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )

    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["best_column_hits"] = 7
    with pytest.raises(ValueError, match="best_column_hits"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_rejects_actual_result_reconciliation_mismatch() -> (
    None
):
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["actual_main_results"][0] = "X"
    with pytest.raises(ValueError, match="actual result 1"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_recomputes_pleno_hit() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["pleno_hit"] = True
    with pytest.raises(ValueError, match="pleno_hit"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_enforces_selae_minimum_and_price() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["total_bets"] = 1
    with pytest.raises(ValueError, match="minimum or maximum"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )

    result, coupon_ids = _accepted_coupon_backtest_result()
    result["coupons"][0]["models"]["dc"]["price_per_bet_eur"] = 0.7
    result["coupons"][0]["models"]["dc"]["cost_eur"] = 5.6
    with pytest.raises(ValueError, match="current SELAE price"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )


def test_coupon_backtest_acceptance_rejects_unsupported_multi_pleno_ticket() -> None:
    result, coupon_ids = _accepted_coupon_backtest_result()
    model = result["coupons"][0]["models"]["dc"]
    model["pleno15_home_categories"] = ["0", "1"]
    model["pleno15_multiplier"] = 2
    model["total_bets"] = 16
    model["cost_eur"] = 12.0
    with pytest.raises(ValueError, match="single predicted Pleno pair"):
        validate_coupon_backtest_acceptance(
            result, coupon_ids, budget=8, min_history_matches=300
        )
