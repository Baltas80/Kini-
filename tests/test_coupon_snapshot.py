from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kini_engine.coupon_snapshot import (
    load_official_coupon_snapshot,
    verify_coupon_against_selae_snapshot,
)
from scripts.import_historical_coupons import (
    load_official_snapshot_for_journey,
)


def _records():
    fixtures = []
    official = []
    for number in range(1, 15):
        home = f"Home {number}"
        away = f"Away {number}"
        fixtures.append(
            {
                "number": number,
                "home": home,
                "away": away,
                "home_goals": 1,
                "away_goals": 0,
                "result": "1",
            }
        )
        official.append(dict(fixtures[-1]))
    pleno = {
        "number": 15,
        "home": "Celta",
        "away": "Cádiz",
        "home_goals": 4,
        "away_goals": 0,
        "pleno_home_category": "M",
        "pleno_away_category": "0",
    }
    coupon = {
        "coupon_id": "2020-2021:21",
        "source_date": "2020-12-13",
        "source_date_label_at": "2020-12-13T22:57:00+01:00",
        "fixtures": fixtures + [pleno],
    }
    snapshot = {
        "schema_version": 1,
        "source": "SELAE",
        "draw_date": "2020-12-13",
        "source_url": "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-13-de-diciembre-de-2020",
        "verified_at": "2026-11-16",
        "verification_method": "manual official page review",
        "snapshot_type": "normalized_json_extract_not_raw_html",
        "fixtures": official,
        "pleno": {
            "number": 15,
            "home": "Celta",
            "away": "Cádiz",
            "home_goals": 4,
            "away_goals": 0,
            "home_category": "M",
            "away_category": "0",
        },
    }
    return coupon, snapshot


def test_official_snapshot_verifies_all_main_matches_and_pleno() -> None:
    coupon, snapshot = _records()
    verified = verify_coupon_against_selae_snapshot(
        coupon, snapshot, snapshot_sha256="a" * 64
    )
    assert verified["official_main_matches_verified"] is True
    assert verified["official_pleno_verified"] is True
    assert (
        verified["official_result_snapshot_type"]
        == "normalized_json_extract_not_raw_html"
    )
    assert verified["official_result_sha256"] == "a" * 64


def test_official_snapshot_rejects_result_mismatch() -> None:
    coupon, snapshot = _records()
    snapshot["fixtures"][0]["home_goals"] = 0
    with pytest.raises(ValueError, match="snapshot reconciliation failed"):
        verify_coupon_against_selae_snapshot(coupon, snapshot, snapshot_sha256="a" * 64)


def test_snapshot_loader_hashes_exact_json_bytes(tmp_path: Path) -> None:
    _, snapshot = _records()
    path = tmp_path / "official.json"
    raw = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
    path.write_bytes(raw)
    loaded, digest = load_official_coupon_snapshot(path)
    assert loaded["source"] == "SELAE"
    import hashlib

    assert digest == hashlib.sha256(raw).hexdigest()


def test_official_snapshot_rejects_mismatched_source_draw_date() -> None:
    coupon, snapshot = _records()
    snapshot["draw_date"] = "2020-12-14"
    with pytest.raises(ValueError, match="does not match coupon source date"):
        verify_coupon_against_selae_snapshot(coupon, snapshot, snapshot_sha256="a" * 64)


def test_snapshot_directory_loads_exact_season_journey_file(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    snapshot = {"source": "SELAE", "draw_date": "2020-12-13"}
    raw = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    expected = snapshot_dir / "2020-2021-21.json"
    expected.write_bytes(raw)
    (snapshot_dir / "2020-2021-22.json").write_text(
        json.dumps({"source": "SELAE", "draw_date": "2020-12-20"}),
        encoding="utf-8",
    )

    loaded, digest, path = load_official_snapshot_for_journey(
        snapshot_dir,
        "2020-2021",
        21,
    )

    assert loaded == snapshot
    assert path == expected
    assert digest == hashlib.sha256(raw).hexdigest()


def test_snapshot_directory_rejects_missing_journey_snapshot(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="2020-2021 journey 22"):
        load_official_snapshot_for_journey(tmp_path, "2020-2021", 22)


def test_snapshot_directory_rejects_invalid_journey_number(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        load_official_snapshot_for_journey(tmp_path, "2020-2021", 0)


def test_snapshot_loader_rejects_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "official.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        load_official_coupon_snapshot(path)


def test_snapshot_directory_rejects_unsafe_season_slug(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="YYYY-YYYY"):
        load_official_snapshot_for_journey(tmp_path, "../2020-2021", 21)


def test_jornada_19_official_snapshot_matches_reviewed_selae_results() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "kini_engine"
        / "data"
        / "selae_official_coupon_results"
        / "2020-2021-19.json"
    )
    snapshot, digest = load_official_coupon_snapshot(path)

    expected = [
        ("Levante", "Getafe", 3, 0, "1"),
        ("Sevilla", "Real Madrid", 0, 1, "2"),
        ("At. Madrid", "Valladolid", 2, 0, "1"),
        ("Cádiz", "Barcelona", 2, 1, "1"),
        ("Granada", "Huesca", 3, 3, "X"),
        ("Osasuna", "Betis", 0, 2, "2"),
        ("Villarreal", "Elche", 0, 0, "X"),
        ("Alavés", "Real Sociedad", 0, 0, "X"),
        ("Alcorcón", "Almería", 0, 1, "2"),
        ("Espanyol", "Sporting", 2, 0, "1"),
        ("Mirandés", "Lugo", 0, 0, "X"),
        ("Rayo Vallecano", "Logroñés", 2, 1, "1"),
        ("Zaragoza", "Fuenlabrada", 1, 0, "1"),
        ("Sabadell", "R. Oviedo", 0, 1, "2"),
    ]
    actual = [
        (
            item["home"],
            item["away"],
            item["home_goals"],
            item["away_goals"],
            item["result"],
        )
        for item in snapshot["fixtures"]
    ]
    assert snapshot["draw_date"] == "2020-12-06"
    assert snapshot["source_url"] == (
        "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/"
        "la-quiniela-resultados-del-6-de-diciembre-de-2020"
    )
    supporting_sources = {
        item["role"]: item["url"] for item in snapshot["supporting_sources"]
    }
    assert supporting_sources["official_selae_result_page"] == snapshot["source_url"]
    assert supporting_sources["football_data_sp1_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2021/SP1.csv"
    )
    assert supporting_sources["football_data_sp2_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2021/SP2.csv"
    )
    assert actual == expected
    assert snapshot["pleno"] == {
        "number": 15,
        "home": "Eibar",
        "away": "Valencia",
        "home_goals": 0,
        "away_goals": 0,
        "home_category": "0",
        "away_category": "0",
    }
    assert snapshot["prize_distribution"]["categories"] == [
        {
            "category": "pleno_al_15",
            "winner_count": 0,
            "unit_prize_eur": None,
            "status": "rollover",
        },
        {
            "category": "14",
            "winner_count": 0,
            "unit_prize_eur": None,
            "status": "rollover",
        },
        {
            "category": "13",
            "winner_count": 37,
            "unit_prize_eur": 7077.29,
            "status": "awarded",
        },
        {
            "category": "12",
            "winner_count": 569,
            "unit_prize_eur": 460.21,
            "status": "awarded",
        },
        {
            "category": "11",
            "winner_count": 5240,
            "unit_prize_eur": 49.97,
            "status": "awarded",
        },
        {
            "category": "10",
            "winner_count": 31232,
            "unit_prize_eur": 10.06,
            "status": "awarded",
        },
    ]
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()

    coupon = {
        "coupon_id": "2020-2021:19",
        "source_date": "2020-12-06",
        "fixtures": [
            {
                "number": item["number"],
                "home": item["home"],
                "away": item["away"],
                "home_goals": item["home_goals"],
                "away_goals": item["away_goals"],
                "result": item["result"],
            }
            for item in snapshot["fixtures"]
        ]
        + [
            {
                "number": 15,
                "home": "Eibar",
                "away": "Valencia",
                "home_goals": 0,
                "away_goals": 0,
                "pleno_home_category": "0",
                "pleno_away_category": "0",
            }
        ],
    }
    verified = verify_coupon_against_selae_snapshot(
        coupon, snapshot, snapshot_sha256=digest
    )
    assert verified["official_main_matches_verified"] is True
    assert verified["official_pleno_verified"] is True


def test_jornada_22_official_snapshot_matches_reviewed_selae_results() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "kini_engine"
        / "data"
        / "selae_official_coupon_results"
        / "2020-2021-22.json"
    )
    snapshot, digest = load_official_coupon_snapshot(path)

    expected = [
        ("At. Madrid", "Elche", 3, 1, "1"),
        ("Barcelona", "Valencia", 2, 2, "X"),
        ("Levante", "Real Sociedad", 2, 1, "1"),
        ("Osasuna", "Villarreal", 1, 3, "2"),
        ("Sevilla", "Valladolid", 1, 1, "X"),
        ("Celta", "Alavés", 2, 0, "1"),
        ("Granada", "Betis", 2, 0, "1"),
        ("Cádiz", "Getafe", 0, 2, "2"),
        ("Mallorca", "Fuenlabrada", 2, 3, "2"),
        ("Zaragoza", "Lugo", 1, 0, "1"),
        ("Alcorcón", "Cartagena", 2, 1, "1"),
        ("Espanyol", "Almería", 2, 1, "1"),
        ("Rayo Vallecano", "Las Palmas", 2, 0, "1"),
        ("Málaga", "Logroñés", 0, 0, "X"),
    ]
    actual = [
        (
            item["home"],
            item["away"],
            item["home_goals"],
            item["away_goals"],
            item["result"],
        )
        for item in snapshot["fixtures"]
    ]
    assert snapshot["draw_date"] == "2020-12-20"
    assert snapshot["source_url"] == (
        "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/"
        "la-quiniela-resultados-del-20-de-diciembre-de-2020"
    )
    sources = {item["role"]: item["url"] for item in snapshot["supporting_sources"]}
    assert sources["official_selae_result_page"] == snapshot["source_url"]
    assert sources["official_selae_press_release_pdf"] == (
        "https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/"
        "NOTA_DE_PRENSA_DE_LA_QUINIELA_DE_FECHA_20_12_20.pdf"
    )
    assert sources["schedule_and_kickoff_crosscheck"] == (
        "https://www.historicoquiniela.com/historico/2020-2021/22"
    )
    assert sources["football_data_sp1_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2021/SP1.csv"
    )
    assert sources["football_data_sp2_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2021/SP2.csv"
    )
    assert actual == expected
    assert snapshot["pleno"] == {
        "number": 15,
        "home": "Eibar",
        "away": "Real Madrid",
        "home_goals": 1,
        "away_goals": 3,
        "home_category": "1",
        "away_category": "M",
    }

    coupon = {
        "coupon_id": "2020-2021:22",
        "source_date": "2020-12-20",
        "fixtures": [
            {
                "number": item["number"],
                "home": item["home"],
                "away": item["away"],
                "home_goals": item["home_goals"],
                "away_goals": item["away_goals"],
                "result": item["result"],
            }
            for item in snapshot["fixtures"]
        ]
        + [
            {
                "number": 15,
                "home": snapshot["pleno"]["home"],
                "away": snapshot["pleno"]["away"],
                "home_goals": snapshot["pleno"]["home_goals"],
                "away_goals": snapshot["pleno"]["away_goals"],
                "pleno_home_category": snapshot["pleno"]["home_category"],
                "pleno_away_category": snapshot["pleno"]["away_category"],
            }
        ],
    }
    verified = verify_coupon_against_selae_snapshot(
        coupon, snapshot, snapshot_sha256=digest
    )
    assert verified["official_main_matches_verified"] is True
    assert verified["official_pleno_verified"] is True


def test_jornada_25_official_snapshot_matches_reviewed_selae_results() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "kini_engine"
        / "data"
        / "selae_official_coupon_results"
        / "2020-2021-25.json"
    )
    snapshot, digest = load_official_coupon_snapshot(path)

    expected = [
        ("Villarreal", "Levante", 2, 1, "1"),
        ("Betis", "Sevilla", 1, 1, "X"),
        ("Getafe", "Valladolid", 0, 1, "2"),
        ("Real Madrid", "Celta", 2, 0, "1"),
        ("Athletic Club", "Elche", 1, 0, "1"),
        ("Alavés", "At. Madrid", 1, 2, "2"),
        ("Eibar", "Granada", 2, 0, "1"),
        ("Real Sociedad", "Osasuna", 1, 1, "X"),
        ("Huesca", "Barcelona", 0, 1, "2"),
        ("Fuenlabrada", "Leganés", 0, 0, "X"),
        ("Rayo Vallecano", "Alcorcón", 2, 1, "1"),
        ("Las Palmas", "Espanyol", 1, 0, "1"),
        ("Almería", "Ponferradina", 3, 1, "1"),
        ("R. Oviedo", "Mallorca", 2, 2, "X"),
    ]
    actual = [
        (
            item["home"],
            item["away"],
            item["home_goals"],
            item["away_goals"],
            item["result"],
        )
        for item in snapshot["fixtures"]
    ]
    assert snapshot["draw_date"] == "2021-01-03"
    assert snapshot["source_url"] == (
        "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/"
        "la-quiniela-resultados-del-03-de-enero-de-2021"
    )
    sources = {item["role"]: item["url"] for item in snapshot["supporting_sources"]}
    assert sources["official_selae_result_page"] == snapshot["source_url"]
    assert sources["official_selae_press_release_pdf"] == (
        "https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/"
        "NOTA_DE_PRENSA_DE_LA_QUINIELA_DE_FECHA_3_1_21.pdf"
    )
    assert sources["schedule_and_kickoff_crosscheck"] == (
        "https://www.historicoquiniela.com/historico/2020-2021/25"
    )
    assert sources["football_data_sp1_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2021/SP1.csv"
    )
    assert sources["football_data_sp2_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2021/SP2.csv"
    )
    assert actual == expected
    assert snapshot["pleno"] == {
        "number": 15,
        "home": "Valencia",
        "away": "Cádiz",
        "home_goals": 1,
        "away_goals": 1,
        "home_category": "1",
        "away_category": "1",
    }

    coupon = {
        "coupon_id": "2020-2021:25",
        "source_date": "2021-01-03",
        "fixtures": [
            {
                "number": item["number"],
                "home": item["home"],
                "away": item["away"],
                "home_goals": item["home_goals"],
                "away_goals": item["away_goals"],
                "result": item["result"],
            }
            for item in snapshot["fixtures"]
        ]
        + [
            {
                "number": 15,
                "home": snapshot["pleno"]["home"],
                "away": snapshot["pleno"]["away"],
                "home_goals": snapshot["pleno"]["home_goals"],
                "away_goals": snapshot["pleno"]["away_goals"],
                "pleno_home_category": snapshot["pleno"]["home_category"],
                "pleno_away_category": snapshot["pleno"]["away_category"],
            }
        ],
    }
    verified = verify_coupon_against_selae_snapshot(
        coupon, snapshot, snapshot_sha256=digest
    )
    assert verified["official_main_matches_verified"] is True
    assert verified["official_pleno_verified"] is True
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_jornada_1_2021_2022_official_snapshot_matches_reviewed_selae_results() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "kini_engine"
        / "data"
        / "selae_official_coupon_results"
        / "2021-2022-1.json"
    )
    snapshot, digest = load_official_coupon_snapshot(path)

    expected = [
        ("Osasuna", "Espanyol", 0, 0, "X"),
        ("Mallorca", "Betis", 1, 1, "X"),
        ("Cádiz", "Levante", 1, 1, "X"),
        ("Alavés", "Real Madrid", 1, 4, "2"),
        ("Celta", "At. Madrid", 1, 2, "2"),
        ("Barcelona", "Real Sociedad", 4, 2, "1"),
        ("Sevilla", "Rayo Vallecano", 3, 0, "1"),
        ("Villarreal", "Granada", 0, 0, "X"),
        ("R. Sociedad B", "Leganés", 1, 0, "1"),
        ("Ponferradina", "Alcorcón", 1, 0, "1"),
        ("Sporting", "Burgos", 1, 0, "1"),
        ("R. Oviedo", "Lugo", 2, 2, "X"),
        ("Las Palmas", "Valladolid", 1, 1, "X"),
        ("Fuenlabrada", "Tenerife", 1, 2, "2"),
    ]
    actual = [
        (
            item["home"],
            item["away"],
            item["home_goals"],
            item["away_goals"],
            item["result"],
        )
        for item in snapshot["fixtures"]
    ]
    assert snapshot["draw_date"] == "2021-08-15"
    assert snapshot["source_url"] == (
        "https://www.loteriasyapuestas.es/es/la-quiniela/resultados/"
        "la-quiniela-resultados-del-15-de-agosto-de-2021"
    )
    supporting_sources = {
        item["role"]: item["url"] for item in snapshot["supporting_sources"]
    }
    assert supporting_sources["official_selae_press_release_pdf"].endswith(
        "NOTA_DE_PRENSA_DE_LA_QUINIELA_DE_FECHA_15_8_21.pdf"
    )
    assert supporting_sources["schedule_and_kickoff_crosscheck"] == (
        "https://www.historicoquiniela.com/historico/2021-2022/1"
    )
    assert supporting_sources["football_data_sp1_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2122/SP1.csv"
    )
    assert supporting_sources["football_data_sp2_crosscheck"] == (
        "https://www.football-data.co.uk/mmz4281/2122/SP2.csv"
    )
    assert actual == expected
    assert snapshot["pleno"] == {
        "number": 15,
        "home": "Elche",
        "away": "Athletic Club",
        "home_goals": 0,
        "away_goals": 0,
        "home_category": "0",
        "away_category": "0",
    }
    coupon = {
        "coupon_id": "2021-2022:01",
        "source_date": "2021-08-15",
        "fixtures": [dict(item) for item in snapshot["fixtures"]]
        + [
            {
                "number": 15,
                "home": snapshot["pleno"]["home"],
                "away": snapshot["pleno"]["away"],
                "home_goals": snapshot["pleno"]["home_goals"],
                "away_goals": snapshot["pleno"]["away_goals"],
                "pleno_home_category": snapshot["pleno"]["home_category"],
                "pleno_away_category": snapshot["pleno"]["away_category"],
            }
        ],
    }
    verified = verify_coupon_against_selae_snapshot(
        coupon,
        snapshot,
        snapshot_sha256=digest,
    )
    assert verified["official_main_matches_verified"] is True
    assert verified["official_pleno_verified"] is True
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
