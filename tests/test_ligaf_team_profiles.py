from __future__ import annotations

import pytest

from kini_engine.ligaf_history import LigaFHistoryError
from kini_engine.ligaf_team_profiles import (
    _cross_season_display_name_observations,
    _cross_season_observations,
    extract_team_profile_link,
    parse_team_profile_page,
    validate_historical_team_profiles,
)

MATCH_URL = (
    "https://ligaf.es/partido/team-a/team-b/2023310001/detalle"
)
PROFILE_URL = "https://ligaf.es/equipo/team-a/123/plantilla/2023"


def test_extract_team_profile_link_uses_exact_official_anchor_text():
    html = """
    <html><head><title>Team A Vs Team B - Liga F 2023 | LIGAF</title></head>
    <body>
      <a href="/equipo/team-a/123/plantilla/2027">Team A</a>
      <a href="/equipo/team-b/456/plantilla/2027">Team B</a>
      <a href="/equipo/team-a/123/plantilla/2027">Team A</a>
    </body></html>
    """
    assert extract_team_profile_link(
        html,
        match_url=MATCH_URL,
        team_name="Team A",
    ) == {
        "profile_slug": "team-a",
        "provider_team_profile_id": "123",
        "profile_link_season_end_year": "2027",
        "match_detail_profile_link_url": (
            "https://ligaf.es/equipo/team-a/123/plantilla/2027"
        ),
    }


def test_extract_team_profile_link_rejects_missing_or_external_anchor():
    html = """
    <html><body>
      <a href="https://outside.example/equipo/team-a/123/plantilla/2027">
        Team A
      </a>
    </body></html>
    """
    with pytest.raises(LigaFHistoryError, match="no official team-profile link"):
        extract_team_profile_link(
            html,
            match_url=MATCH_URL,
            team_name="Team A",
        )


def test_extract_team_profile_link_rejects_conflicting_profile_ids():
    html = """
    <html><body>
      <a href="/equipo/team-a/123/plantilla/2027">Team A</a>
      <a href="/equipo/team-a/124/plantilla/2027">Team A</a>
    </body></html>
    """
    with pytest.raises(LigaFHistoryError, match="conflicting official profile links"):
        extract_team_profile_link(
            html,
            match_url=MATCH_URL,
            team_name="Team A",
        )


def test_parse_team_profile_page_requires_season_route_and_standings():
    html = """
    <html><head><title>Plantilla Team A | LPFF</title></head>
    <body><h2>Liga F</h2><p>Clasificación Jornada 30</p>
    <p>Pts PJ PG PE PP</p></body></html>
    """
    assert (
        parse_team_profile_page(
            html,
            profile_url=PROFILE_URL,
            season_end_year=2023,
        )
        == "Team A"
    )


def test_parse_team_profile_page_rejects_wrong_season_route():
    html = """
    <html><head><title>Plantilla Team A | LPFF</title></head>
    <body><p>Clasificación Jornada 30</p></body></html>
    """
    with pytest.raises(LigaFHistoryError, match="requested season"):
        parse_team_profile_page(
            html,
            profile_url="https://ligaf.es/equipo/team-a/123/plantilla/2024",
            season_end_year=2023,
        )


def test_parse_team_profile_page_rejects_missing_season_standings():
    html = """
    <html><head><title>Plantilla Team A | LPFF</title></head>
    <body><p>Información general del equipo</p></body></html>
    """
    with pytest.raises(LigaFHistoryError, match="no season standings"):
        parse_team_profile_page(
            html,
            profile_url=PROFILE_URL,
            season_end_year=2023,
        )


def _crosswalk_document() -> dict:
    entries = []
    for index in range(16):
        entries.append(
            {
                "team_name_in_match": f"Team {index:02d}",
                "provider_team_profile_id": str(1000 + index),
                "team_profile_url": (
                    "https://ligaf.es/equipo/"
                    f"team-{index:02d}/{1000 + index}/plantilla/2023"
                ),
                "match_evidence_url": (
                    "https://ligaf.es/partido/home/away/"
                    f"{2023310000 + index}/detalle"
                ),
                "match_detail_profile_link_url": (
                    "https://ligaf.es/equipo/"
                    f"team-{index:02d}/{1000 + index}/plantilla/2027"
                ),
                "name_match_exact": True,
                "identity_review_required": False,
                "identity_status": "exact_name_match",
            }
        )
    return {
        "schema_version": 1,
        "provider": "LIGA_F",
        "competition_id": "LIGA_F",
        "gender": "women",
        "training_eligibility": {"eligible": False},
        "seasons": {
            "2023": {
                "season_end_year": 2023,
                "team_count": 16,
                "unique_profile_ids": 16,
                "entries": entries,
            }
        },
    }


def test_validate_historical_profiles_accepts_season_scoped_evidence_only():
    document = _crosswalk_document()
    validate_historical_team_profiles(document)


def test_validate_historical_profiles_rejects_canonical_identity_promotion():
    document = _crosswalk_document()
    document["seasons"]["2023"]["entries"][0]["team_id"] = "team:ligaf:team-00"
    with pytest.raises(LigaFHistoryError, match="must not assign a canonical"):
        validate_historical_team_profiles(document)


def test_validate_historical_profiles_rejects_duplicate_provider_ids():
    document = _crosswalk_document()
    document["seasons"]["2023"]["entries"][1]["provider_team_profile_id"] = "1000"
    with pytest.raises(LigaFHistoryError, match="duplicate provider profile IDs"):
        validate_historical_team_profiles(document)


def test_cross_season_display_name_audit_flags_multiple_provider_ids():
    seasons = {
        "2023": {
            "entries": [
                {
                    "team_name_in_match": "Team A",
                    "provider_team_profile_id": "123",
                    "team_profile_url": (
                        "https://ligaf.es/equipo/team-a/123/plantilla/2023"
                    ),
                }
            ]
        },
        "2024": {
            "entries": [
                {
                    "team_name_in_match": "Team A",
                    "provider_team_profile_id": "124",
                    "team_profile_url": (
                        "https://ligaf.es/equipo/team-a/124/plantilla/2024"
                    ),
                }
            ]
        },
    }
    summary = _cross_season_display_name_observations(seasons)
    assert summary[0]["continuity_status"] == (
        "same_display_name_multiple_profile_ids_requires_review"
    )
    assert summary[0]["provider_team_profile_ids"] == ["123", "124"]


def test_cross_season_provider_id_audit_flags_label_changes():
    seasons = {
        "2023": {
            "entries": [
                {
                    "provider_team_profile_id": "123",
                    "team_name_in_match": "Old Name",
                    "team_profile_url": "https://ligaf.es/equipo/team-a/123/plantilla/2023",
                }
            ]
        },
        "2024": {
            "entries": [
                {
                    "provider_team_profile_id": "123",
                    "team_name_in_match": "New Name",
                    "team_profile_url": "https://ligaf.es/equipo/team-a/123/plantilla/2024",
                }
            ]
        },
    }
    summary = _cross_season_observations(seasons)
    assert summary[0]["continuity_status"] == (
        "repeat_profile_id_with_label_change_requires_review"
    )
    assert summary[0]["observed_team_names"] == ["New Name", "Old Name"]
