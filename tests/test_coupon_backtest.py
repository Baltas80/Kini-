from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from kini_engine import coupons
from kini_engine.core import Match, TicketOptimizer


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
                "pleno_home_category": coupons._pleno_category(home_goals) if number == 15 else None,
                "pleno_away_category": coupons._pleno_category(away_goals) if number == 15 else None,
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
        kickoff = datetime.fromisoformat(str(row["kickoff_at"])).strftime("%d/%m/%Y, %H:%M")
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
    return "<html><body>" + "".join(ul(group) for group in groups) + ul(pleno_values) + "</body></html>"


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

        def pleno15_probs(self, home: str, away: str, **kwargs: object) -> list[dict[str, object]]:
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
    assert result["models"]["dc"]["status"] == "success"
    assert result["models"]["dc"]["n_predictions"] == 14
    assert result["models"]["dc"]["cost_eur"] > 0
    assert result["models"]["dc"]["total_bets"] <= 31_104



def test_coupon_batch_does_not_swallow_unexpected_programming_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_error(*args: object, **kwargs: object) -> None:
        raise AttributeError("unexpected programming defect")

    monkeypatch.setattr(coupons, "evaluate_coupon", unexpected_error)
    with pytest.raises(AttributeError, match="unexpected programming defect"):
        coupons.evaluate_coupon_batch([{"coupon_id": "2020-2021:21"}], [])
