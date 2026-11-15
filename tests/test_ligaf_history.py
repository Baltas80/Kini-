from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kini_engine.ligaf_history import (
    LigaFHistoryError,
    _cache_paths,
    extract_match_links,
    fetch_html,
    parse_match_detail,
    validate_history,
)

ROUND_URL = "https://ligaf.es/resultados/primera_division_femenina/10/2027"
MATCH_URL = "https://ligaf.es/partido/athletic-club-femenino/real-madrid-cf-femenino/202723868/detalle"
ROUND_HTML = """
<html><head><title>Resultados Jornada 10 Liga F | LPFF</title></head><body>
<a href="/partido/athletic-club-femenino/real-madrid-cf-femenino/202723868/detalle">
Athletic Club 1 - 1 Real Madrid CF</a>
<a href="https://outside.example/partido/other/999/detalle">External</a>
</body></html>
"""
MATCH_HTML = """
<html><head>
<title>Athletic Club Vs Real Madrid CF - Liga F 2027 | LIGAF</title>
</head><body>
<h2>Liga F Moeve | JOR. 10 | Sáb 07 NOV 16:00</h2>
<p>Finalizado</p>
<div>Athletic Club</div><div>1 - 1</div><div>Real Madrid CF</div>
</body></html>
"""


def source_metadata(content: str, url: str) -> dict:
    import hashlib

    return {
        "source_url": url,
        "retrieved_at_utc": "2026-11-15T09:00:00+00:00",
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "cache_stale": False,
    }


def parsed_row(match_html: str = MATCH_HTML) -> dict:
    return parse_match_detail(
        match_html,
        match_url=MATCH_URL,
        season_end_year=2027,
        expected_matchday=10,
        round_url=ROUND_URL,
        match_source_metadata=source_metadata(match_html, MATCH_URL),
        round_source_metadata=source_metadata(ROUND_HTML, ROUND_URL),
    )


def test_extract_match_links_accepts_only_official_ligaf_urls():
    links = extract_match_links(ROUND_HTML, page_url=ROUND_URL)
    assert links == [{"match_id": "202723868", "match_url": MATCH_URL}]


def test_extract_match_links_rejects_empty_or_non_official_archive():
    with pytest.raises(LigaFHistoryError, match="no official Liga F match links"):
        extract_match_links("<html><body>No matches</body></html>", page_url=ROUND_URL)
    with pytest.raises(LigaFHistoryError, match="official ligaf.es"):
        extract_match_links(ROUND_HTML, page_url="https://outside.example/archive")


def test_parse_match_detail_extracts_score_kickoff_and_source_provenance():
    row = parsed_row()
    assert row["match_id"] == "202723868"
    assert row["season"] == "2026-27"
    assert row["matchday"] == 10
    assert row["home_team_name"] == "Athletic Club"
    assert row["away_team_name"] == "Real Madrid CF"
    assert row["home_goals"] == 1
    assert row["away_goals"] == 1
    assert row["result_1x2"] == "X"
    assert row["match_status"] == "played"
    assert row["kickoff_at"] == "2026-11-07T16:00:00+01:00"
    assert row["training_label_eligible"] is False
    assert len(row["match_source_sha256"]) == 64


def test_parse_match_detail_handles_postponed_without_fabricating_score():
    html = """
    <html><head><title>Costa Adeje Tenerife Vs Deportivo Alavés - Liga F 2027 | LIGAF</title></head>
    <body><h2>Liga F Moeve | JOR. 10 | Dom 08 NOV 12:00</h2>
    <p>Aplazado</p></body></html>
    """
    row = parse_match_detail(
        html,
        match_url="https://ligaf.es/partido/tenerife/alaves/202723999/detalle",
        season_end_year=2027,
        expected_matchday=10,
        round_url=ROUND_URL,
        match_source_metadata=source_metadata(html, MATCH_URL),
        round_source_metadata=source_metadata(ROUND_HTML, ROUND_URL),
    )
    assert row["match_status"] == "postponed"
    assert row["home_goals"] is None
    assert row["away_goals"] is None
    assert row["result_1x2"] is None


def test_parse_match_detail_uses_archive_season_not_static_title_year():
    html = """
    <html><head>
    <title>Real Sociedad Vs Real Madrid CF - Liga F 2027 | LIGAF</title>
    </head><body>
    <h2>Liga F Moeve | JOR. 30 | Vie 19 MAY 19:00</h2>
    <p>Finalizado</p>
    <div>Real Sociedad</div><div>1 - 1</div><div>Real Madrid CF</div>
    </body></html>
    """
    url = "https://ligaf.es/partido/real-sociedad/real-madrid/2023310144/detalle"
    row = parse_match_detail(
        html,
        match_url=url,
        season_end_year=2023,
        expected_matchday=30,
        round_url="https://ligaf.es/resultados/primera_division_femenina/30/2023",
        match_source_metadata=source_metadata(html, url),
        round_source_metadata=source_metadata(ROUND_HTML, ROUND_URL),
    )
    assert row["season"] == "2022-23"
    assert row["kickoff_at"] == "2023-05-19T19:00:00+02:00"
    assert row["home_team_name"] == "Real Sociedad"
    assert row["away_team_name"] == "Real Madrid CF"


def test_validate_history_rejects_result_score_mismatch():
    row = _record(1)
    row["result_1x2"] = "2"
    with pytest.raises(LigaFHistoryError, match="result conflicts with the full-time score"):
        validate_history(
            [row],
            completed_seasons=set(),
            requested_rounds={2023: 1},
            expected_fixtures_per_round=1,
        )


def _record(
    match_id: int,
    *,
    season_end_year: int = 2023,
    matchday: int = 1,
    home: str = "Home",
    away: str = "Away",
    home_goals: int = 1,
    away_goals: int = 0,
) -> dict:
    import hashlib

    digest = hashlib.sha256(str(match_id).encode()).hexdigest()
    return {
        "schema_version": 1,
        "provider": "LIGA_F",
        "competition_id": "LIGA_F",
        "gender": "women",
        "season": f"{season_end_year - 1}-{str(season_end_year)[-2:]}",
        "season_end_year": season_end_year,
        "matchday": matchday,
        "match_id": str(match_id),
        "kickoff_at": f"{season_end_year - 1}-08-20T16:00:00+02:00",
        "home_team_name": home,
        "away_team_name": away,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "result_1x2": "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X",
        "match_status": "played",
        "match_url": f"https://ligaf.es/partido/home/away/{match_id}/detalle",
        "round_url": f"https://ligaf.es/resultados/primera_division_femenina/{matchday}/{season_end_year}",
        "match_source_retrieved_at_utc": "2026-11-15T09:00:00+00:00",
        "match_source_sha256": digest,
        "round_source_retrieved_at_utc": "2026-11-15T09:00:00+00:00",
        "round_source_sha256": digest,
        "training_label_eligible": False,
        "training_exclusion_reason": "evidence only",
    }


def test_validate_history_accepts_complete_16_team_double_round_robin():
    teams = [f"Team {index:02d}" for index in range(16)]
    rotation = teams[:]
    first_half = []
    for _ in range(15):
        first_half.append([(rotation[index], rotation[15 - index]) for index in range(8)])
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]

    records = []
    match_id = 1000
    for matchday, fixtures in enumerate(first_half, start=1):
        for home, away in fixtures:
            records.append(
                _record(match_id, matchday=matchday, home=home, away=away)
            )
            match_id += 1
    for matchday, fixtures in enumerate(first_half, start=16):
        for home, away in fixtures:
            records.append(
                _record(match_id, matchday=matchday, home=away, away=home)
            )
            match_id += 1

    profile = validate_history(
        records,
        completed_seasons={2023},
        requested_rounds={2023: 30},
    )
    assert profile["total_scheduled_fixtures"] == 240
    assert profile["total_played_fixtures"] == 240
    assert profile["season_profiles"]["2023"]["team_count_in_played_fixtures"] == 16
    assert profile["training_eligibility"]["eligible"] is False


def test_validate_history_rejects_duplicate_match_ids():
    first = _record(1)
    second = _record(1, matchday=2, home="Away", away="Home")
    with pytest.raises(LigaFHistoryError, match="duplicate Liga F match ID"):
        validate_history(
            [first, second],
            completed_seasons=set(),
            requested_rounds={2023: 2},
        )


def test_validate_history_rejects_duplicate_scheduled_home_away_pair():
    first = _record(1)
    second = _record(2)
    second["kickoff_at"] = first["kickoff_at"]
    with pytest.raises(LigaFHistoryError, match="duplicate scheduled home/away pair"):
        validate_history(
            [first, second],
            completed_seasons=set(),
            requested_rounds={2023: 1},
            expected_fixtures_per_round=2,
        )


def test_validate_history_rejects_non_final_fixture_with_goals():
    row = _record(1)
    row["match_status"] = "postponed"
    with pytest.raises(LigaFHistoryError, match="non-final fixture"):
        validate_history(
            [row],
            completed_seasons=set(),
            requested_rounds={2023: 1},
        )


def test_validate_history_requires_complete_season_round_coverage():
    with pytest.raises(LigaFHistoryError, match="scheduled fixtures"):
        validate_history(
            [_record(1)],
            completed_seasons=set(),
            requested_rounds={2023: 1},
            expected_fixtures_per_round=8,
        )


def test_validate_history_requires_16_teams_and_30_appearances_for_complete_seasons():
    with pytest.raises(LigaFHistoryError, match="scheduled fixtures"):
        validate_history(
            [_record(1)],
            completed_seasons={2023},
            requested_rounds={2023: 30},
        )


def test_fetch_html_offline_requires_validated_cache(tmp_path: Path):
    url = "https://ligaf.es/resultados/primera_division_femenina/1/2027"
    with pytest.raises(LigaFHistoryError, match="offline mode has no cached source"):
        fetch_html(url, cache_dir=tmp_path, offline=True)

    html_path, metadata_path = _cache_paths(tmp_path, url)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<html><head><title>Resultados Liga F</title></head></html>", encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "source_url": url,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "content_sha256": __import__("hashlib").sha256(html_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    html, metadata = fetch_html(url, cache_dir=tmp_path, offline=True)
    assert "Resultados Liga F" in html
    assert metadata["cache_used"] is True
    assert metadata["cache_stale"] is False


def test_fetch_html_rejects_cache_hash_mismatch(tmp_path: Path):
    url = "https://ligaf.es/resultados/primera_division_femenina/1/2027"
    html_path, metadata_path = _cache_paths(tmp_path, url)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<html>tampered</html>", encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "source_url": url,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
                "content_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LigaFHistoryError, match="cache hash mismatch"):
        fetch_html(url, cache_dir=tmp_path, offline=True)
