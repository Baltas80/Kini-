from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from kini_engine.fixture_reconciliation import (
    FixtureReconciliationError,
    load_draw_records,
    load_fixture_crosswalk,
    load_historical_fixture_index,
    reconcile_draws,
)
from kini_engine.team_identity import TeamIdentityRegistry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "kini_engine" / "data" / "team_identity_registry.json"
HISTORICAL_PATH = ROOT / "tests" / "fixtures" / "historical_selae_subset.csv"
HISTORICAL_INDEX = load_historical_fixture_index(HISTORICAL_PATH)
SELAE_URL = (
    "https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/"
    "la-quiniela-premios-y-ganadores-del-08-de-noviembre-de-2026"
)
MALAGA_EVIDENCE_URL = (
    "https://www.malagacf.com/noticias/"
    "malagaracing-sabado-7-de-noviembre-a-las-1400"
)
CHECKED_AT = "2026-11-15T09:24:10Z"
HISTORICAL_COLUMNS = [
    "Div",
    "Date",
    "Time",
    "HomeTeam",
    "AwayTeam",
    "FTHG",
    "FTAG",
    "FTR",
    "Season",
    "SourceURL",
]
HISTORICAL_SOURCE_URL = (
    "https://www.football-data.co.uk/mmz4281/2627/SP1.csv"
)


def _team(name: str, marker: str = "M") -> dict[str, str]:
    return {
        "name": name,
        "category_marker": marker,
        "display_name": f"{name} ({marker})",
    }


def _played_fixture(
    position: int,
    home_name: str,
    away_name: str,
    home_goals: int,
    away_goals: int,
    marker: str = "M",
) -> dict[str, object]:
    sign = "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"
    return {
        "position": position,
        "home": _team(home_name, marker),
        "away": _team(away_name, marker),
        "home_display_name": f"{home_name} ({marker})",
        "away_display_name": f"{away_name} ({marker})",
        "score_raw": f"{home_goals}-{away_goals}",
        "score_status": "played",
        "sign_determination": "score",
        "home_goals": home_goals,
        "away_goals": away_goals,
        "sign": sign,
    }


def make_draw() -> dict[str, object]:
    fixtures: list[dict[str, object]] = [
        {
            "position": 1,
            "home": _team("Málaga"),
            "away": _team("Racing de Santander"),
            "score_raw": "1-2",
            "reported_score_raw": "1-2",
            "score_status": "played",
            "sign_determination": "score",
            "home_goals": 1,
            "away_goals": 2,
            "sign": "2",
        }
    ]
    for position in range(2, 15):
        fixtures.append(
            {
                "position": position,
                "home": _team(f"Equipo {position}"),
                "away": _team(f"Rival {position}"),
                "score_raw": None,
                "reported_score_raw": "0-0",
                "score_status": "not_played",
                "sign_determination": "public_draw",
                "home_goals": None,
                "away_goals": None,
                "sign": "1",
                "sign_evidence_url": "https://www.loteriasyapuestas.es/aviso.pdf",
                "sign_evidence_checked_at_utc": CHECKED_AT,
                "status_reason": "Synthetic non-played fixture for a deterministic test.",
            }
        )
    return {
        "schema_version": 2,
        "provider": "SELAE",
        "record_type": "completed_quiniela_draw",
        "draw_date": "2026-11-08",
        "source_url": SELAE_URL,
        "raw_sha256": "a" * 64,
        "fixture_count": 14,
        "fixtures": fixtures,
    }


def make_entry(**changes: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "draw_date": "2026-11-08",
        "position": 1,
        "football_data_date": "2026-11-07",
        "home_selae_display_name": "Málaga (M)",
        "away_selae_display_name": "Racing de Santander (M)",
        "home_football_data_name": "Malaga",
        "away_football_data_name": "Santander",
        "competition_id": "SP1",
        "season": "2627",
        "gender": "men",
        "kickoff_at": "2026-11-07T14:00:00+01:00",
        "source_fixture_id": MALAGA_EVIDENCE_URL,
        "schedule_source": "Málaga CF official website",
        "evidence_url": MALAGA_EVIDENCE_URL,
        "evidence_checked_at_utc": CHECKED_AT,
    }
    entry.update(changes)
    return entry


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def make_crosswalk_file(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    return write_json(
        tmp_path / "crosswalk.json",
        {"schema_version": 1, "provider": "SELAE", "entries": entries},
    )


def load_fixture_crosswalk_from_entries(
    entries: list[dict[str, object]],
) -> dict[tuple[str, int], dict[str, object]]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "crosswalk.json"
        write_json(
            path,
            {"schema_version": 1, "provider": "SELAE", "entries": entries},
        )
        return load_fixture_crosswalk(path)


def load_fixture_crosswalk_from_entry(
    entry: dict[str, object],
) -> dict[tuple[str, int], dict[str, object]]:
    return load_fixture_crosswalk_from_entries([entry])


def _validated_fixtures() -> list[dict[str, object]]:
    from kini_engine.fixture_reconciliation import _validate_draw

    _, fixtures = _validate_draw(make_draw(), "test draw")
    return fixtures


def _draw_with_fixtures(fixtures: list[dict[str, object]]) -> dict[str, object]:
    return {
        "draw_date": "2026-11-08",
        "source_url": SELAE_URL,
        "raw_sha256": "a" * 64,
        "fixtures": fixtures,
    }


def _write_historical_csv(
    tmp_path: Path,
    rows: list[dict[str, str]],
) -> Path:
    path = tmp_path / "historical.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _historical_row(
    home: str = "Malaga",
    away: str = "Santander",
    match_date: str = "07/11/2026",
    home_goals: str = "1",
    away_goals: str = "2",
    result: str = "A",
) -> dict[str, str]:
    return {
        "Div": "SP1",
        "Date": match_date,
        "Time": "13:00",
        "HomeTeam": home,
        "AwayTeam": away,
        "FTHG": home_goals,
        "FTAG": away_goals,
        "FTR": result,
        "Season": "2627",
        "SourceURL": HISTORICAL_SOURCE_URL,
    }


def test_reconciles_verified_fixture_and_excludes_non_played_public_draws():
    registry = TeamIdentityRegistry.from_path(REGISTRY_PATH)
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        load_fixture_crosswalk_from_entry(make_entry()),
        registry,
        HISTORICAL_INDEX,
    )

    assert report["success"] is True
    assert report["coupon_fixture_count"] == 14
    assert report["played_fixture_count"] == 1
    assert report["eligible_fixture_count"] == 1
    assert report["excluded_not_played_count"] == 13
    assert report["unresolved_count"] == 0
    assert len(report["historical_dataset_sha256"]) == 64
    resolved = report["resolved_fixtures"][0]
    assert resolved["home_team_id"] == "team:es:malaga"
    assert resolved["away_team_id"] == "team:es:santander"
    assert resolved["target_1x2"] == "2"
    assert resolved["home_goals"] == 1
    assert resolved["away_goals"] == 2
    assert resolved["training_label_eligible"] is True


def test_missing_crosswalk_is_reported_not_guessed():
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        {},
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["success"] is False
    assert report["eligible_fixture_count"] == 0
    assert report["unresolved_count"] == 1
    assert report["unresolved_fixtures"][0]["reason"] == "missing_verified_crosswalk"


def test_crosswalk_rejects_naive_kickoff_timestamp(tmp_path: Path):
    entry = make_entry(kickoff_at="2026-11-07T14:00:00")
    path = make_crosswalk_file(tmp_path, [entry])

    with pytest.raises(FixtureReconciliationError, match="kickoff_at must include"):
        load_fixture_crosswalk(path)


def test_crosswalk_rejects_non_utc_evidence_check_timestamp(tmp_path: Path):
    entry = make_entry(evidence_checked_at_utc="2026-11-15T10:00:00+01:00")
    path = make_crosswalk_file(tmp_path, [entry])

    with pytest.raises(FixtureReconciliationError, match="must be UTC"):
        load_fixture_crosswalk(path)


def test_crosswalk_rejects_duplicate_coupon_key(tmp_path: Path):
    path = make_crosswalk_file(
        tmp_path,
        [make_entry(), make_entry(source_fixture_id="https://example.org/other")],
    )

    with pytest.raises(FixtureReconciliationError, match="duplicate crosswalk fixture key"):
        load_fixture_crosswalk(path)


def test_crosswalk_rejects_duplicate_source_fixture_id(tmp_path: Path):
    second = make_entry(draw_date="2026-11-09", position=2)
    path = make_crosswalk_file(tmp_path, [make_entry(), second])

    with pytest.raises(FixtureReconciliationError, match="duplicate source_fixture_id"):
        load_fixture_crosswalk(path)


def test_coupon_name_mismatch_is_unresolved_without_fuzzy_matching():
    entry = make_entry(home_selae_display_name="Malaga (M)")
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        load_fixture_crosswalk_from_entry(entry),
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["success"] is False
    assert report["unresolved_fixtures"][0]["reason"] == "coupon_team_name_mismatch"


def test_unknown_football_data_alias_is_unresolved():
    crosswalk = load_fixture_crosswalk_from_entry(
        make_entry(home_football_data_name="Unknown Malaga FC")
    )
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["success"] is False
    assert report["unresolved_fixtures"][0]["reason"] == "unresolved_football_data_identity"
    assert report["unresolved_fixtures"][0]["sides"] == ["home"]


def test_gender_marker_must_agree_with_crosswalk():
    crosswalk = load_fixture_crosswalk_from_entry(make_entry(gender="women"))
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["success"] is False
    assert report["unresolved_fixtures"][0]["reason"] == "category_marker_gender_mismatch"


def test_non_played_fixture_cannot_be_reconciled_as_a_training_label():
    crosswalk = load_fixture_crosswalk_from_entries(
        [
            make_entry(),
            make_entry(position=2, source_fixture_id="fixture:non-played"),
        ]
    )
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["eligible_fixture_count"] == 1
    assert report["excluded_not_played_count"] == 13
    assert report["unused_crosswalk_entry_count"] == 1
    assert report["success"] is False
    assert report["resolved_fixtures"][0]["coupon_position"] == 1


def test_duplicate_canonical_fixture_is_not_added_twice():
    fixtures = _validated_fixtures()
    duplicate = dict(fixtures[0])
    duplicate["position"] = 2
    fixtures[1] = duplicate
    crosswalk = load_fixture_crosswalk_from_entries(
        [
            make_entry(),
            make_entry(
                position=2,
                kickoff_at="2026-11-07T13:00:00Z",
                source_fixture_id="fixture:duplicate-copy",
            ),
        ]
    )
    report = reconcile_draws(
        [_draw_with_fixtures(fixtures)],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["eligible_fixture_count"] == 1
    assert report["unresolved_count"] == 1
    assert report["unresolved_fixtures"][0]["reason"] == "duplicate_canonical_fixture"


def test_draw_loader_rejects_a_played_score_sign_conflict(tmp_path: Path):
    draw = make_draw()
    draw["fixtures"][0]["sign"] = "X"
    path = tmp_path / "draws.jsonl"
    path.write_text(json.dumps(draw) + "\n", encoding="utf-8")

    with pytest.raises(FixtureReconciliationError, match="conflicts with its played score"):
        load_draw_records(path)


def test_draw_loader_rejects_duplicate_draw_dates(tmp_path: Path):
    draw = make_draw()
    path = tmp_path / "draws.jsonl"
    path.write_text(
        json.dumps(draw) + "\n" + json.dumps(draw) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(FixtureReconciliationError, match="duplicate SELAE draw date"):
        load_draw_records(path)


def test_crosswalk_entry_for_unknown_draw_is_reported_as_unused():
    crosswalk = load_fixture_crosswalk_from_entry(
        make_entry(draw_date="2026-11-09")
    )
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["unused_crosswalk_entry_count"] == 1
    assert report["success"] is False


def test_reconciliation_requires_exact_historical_fixture_date(tmp_path: Path):
    crosswalk = load_fixture_crosswalk_from_entry(
        make_entry(football_data_date="2026-11-08")
    )
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["success"] is False
    assert report["unresolved_fixtures"][0]["reason"] == "no_exact_historical_fixture_match"


def test_historical_score_mismatch_is_not_accepted(tmp_path: Path):
    path = _write_historical_csv(
        tmp_path,
        [_historical_row(home_goals="1", away_goals="1", result="D")],
    )
    index = load_historical_fixture_index(path)
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        load_fixture_crosswalk_from_entry(make_entry()),
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        index,
    )

    assert report["success"] is False
    assert report["unresolved_fixtures"][0]["reason"] == "historical_score_mismatch"


def test_duplicate_historical_rows_are_reported_as_ambiguous(tmp_path: Path):
    row = _historical_row()
    path = _write_historical_csv(tmp_path, [row, row])
    index = load_historical_fixture_index(path)
    report = reconcile_draws(
        [_draw_with_fixtures(_validated_fixtures())],
        load_fixture_crosswalk_from_entry(make_entry()),
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        index,
    )

    assert report["success"] is False
    assert report["unresolved_fixtures"][0]["reason"] == "ambiguous_historical_fixture_match"


def test_historical_loader_rejects_result_sign_conflict(tmp_path: Path):
    path = _write_historical_csv(
        tmp_path,
        [_historical_row(home_goals="2", away_goals="1", result="A")],
    )

    with pytest.raises(FixtureReconciliationError, match="FTR conflicts"):
        load_historical_fixture_index(path)


def _verified_mens_fixtures() -> list[dict[str, object]]:
    return [
        _played_fixture(1, "Málaga", "Racing de Santander", 1, 2),
        _played_fixture(2, "Osasuna", "Athletic Club", 1, 1),
        _played_fixture(3, "Valencia", "Real Madrid", 0, 3),
        _played_fixture(4, "Elche", "Betis", 0, 2),
        _played_fixture(5, "Real Sociedad", "Rayo Vallecano", 1, 0),
        _played_fixture(6, "Celta", "Levante", 0, 0),
        _played_fixture(7, "Villarreal", "Getafe", 2, 0),
        _played_fixture(8, "Cádiz", "R. Oviedo", 1, 2),
        _played_fixture(9, "Girona", "Almería", 0, 1),
        _played_fixture(10, "Sporting", "R. Valladolid", 1, 2),
    ]


def test_checked_in_crosswalk_reconciles_ten_verified_mens_fixtures():
    crosswalk = load_fixture_crosswalk(ROOT / "data" / "selae_fixture_crosswalk.json")
    report = reconcile_draws(
        [_draw_with_fixtures(_verified_mens_fixtures())],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["success"] is True
    assert report["eligible_fixture_count"] == 10
    assert report["unresolved_count"] == 0
    assert [row["home_team_id"] for row in report["resolved_fixtures"]] == [
        "team:es:malaga",
        "team:es:osasuna",
        "team:es:valencia",
        "team:es:elche",
        "team:es:sociedad",
        "team:es:celta",
        "team:es:villarreal",
        "team:es:cadiz",
        "team:es:girona",
        "team:es:sp-gijon",
    ]
    assert [row["away_team_id"] for row in report["resolved_fixtures"]] == [
        "team:es:santander",
        "team:es:ath-bilbao",
        "team:es:real-madrid",
        "team:es:betis",
        "team:es:vallecano",
        "team:es:levante",
        "team:es:getafe",
        "team:es:oviedo",
        "team:es:almeria",
        "team:es:valladolid",
    ]


def test_full_coupon_keeps_three_womens_fixtures_unresolved():
    fixtures = _verified_mens_fixtures()
    fixtures.extend(
        [
            _played_fixture(11, "Athletic Club", "Real Madrid", 1, 1, marker="F"),
            _played_fixture(12, "Logroño", "Sevilla", 2, 2, marker="F"),
            _played_fixture(13, "Eibar", "Real Sociedad", 1, 2, marker="F"),
            {
                "position": 14,
                "home": _team("Tenerife", "F"),
                "away": _team("Alavés", "F"),
                "home_display_name": "Tenerife (F)",
                "away_display_name": "Alavés (F)",
                "score_status": "not_played",
                "sign_determination": "public_draw",
                "home_goals": None,
                "away_goals": None,
                "sign": "1",
            },
        ]
    )
    crosswalk = load_fixture_crosswalk(ROOT / "data" / "selae_fixture_crosswalk.json")
    report = reconcile_draws(
        [_draw_with_fixtures(fixtures)],
        crosswalk,
        TeamIdentityRegistry.from_path(REGISTRY_PATH),
        HISTORICAL_INDEX,
    )

    assert report["coupon_fixture_count"] == 14
    assert report["played_fixture_count"] == 13
    assert report["eligible_fixture_count"] == 10
    assert report["excluded_not_played_count"] == 1
    assert report["unresolved_count"] == 3
    assert report["success"] is False
    assert all(
        fixture["reason"] == "missing_verified_crosswalk"
        for fixture in report["unresolved_fixtures"]
    )
