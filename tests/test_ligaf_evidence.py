from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from kini_engine.ligaf_evidence import (
    LigaFEvidenceError,
    load_ligaf_fixture_evidence,
)
from kini_engine.team_identity import TeamIdentityRegistry

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "data" / "ligaf_fixture_evidence.json"


def _document() -> dict[str, object]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def _write_document(tmp_path: Path, document: dict[str, object]) -> Path:
    path = tmp_path / "ligaf_fixture_evidence.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_official_ligaf_evidence_resolves_three_womens_coupon_fixtures():
    fixtures = load_ligaf_fixture_evidence(EVIDENCE_PATH)

    assert len(fixtures) == 3
    assert [item["coupon_position"] for item in fixtures] == [11, 12, 13]
    assert [item["match_id"] for item in fixtures] == [
        "202723868",
        "202723864",
        "202723866",
    ]
    assert [
        (item["home_goals"], item["away_goals"], item["coupon_sign"])
        for item in fixtures
    ] == [(1, 1, "X"), (2, 2, "X"), (1, 2, "2")]
    assert [item["kickoff_at"] for item in fixtures] == [
        "2026-11-07T16:00:00+01:00",
        "2026-11-08T12:00:00+01:00",
        "2026-11-07T17:00:00+01:00",
    ]
    assert all(item["training_label_eligible"] is False for item in fixtures)
    assert all("multi-season" in item["training_exclusion_reason"] for item in fixtures)


def test_ligaf_registry_covers_all_sixteen_current_season_teams():
    registry = TeamIdentityRegistry.from_path(
        ROOT / "kini_engine" / "data" / "ligaf_team_identity_registry.json"
    )
    names = {
        "Athletic Club",
        "Atlético de Madrid",
        "Costa Adeje Tenerife",
        "Deportivo Abanca",
        "Deportivo Alavés",
        "FC Badalona Women",
        "FC Barcelona",
        "Granada CF",
        "Logroño United",
        "Madrid CFF",
        "RCD Espanyol",
        "Real Madrid CF",
        "Real Sociedad",
        "SD Eibar",
        "Sevilla FC",
        "VCF Femenino",
    }

    identities = {
        registry.resolve(
            name,
            source="ligaf",
            competition_id="LIGA_F",
            season="2026-27",
            gender="women",
        )
        for name in names
    }

    assert len(identities) == 16
    assert all(identity is not None for identity in identities)
    assert registry.team_count == 16


def test_ligaf_profile_crosswalk_covers_all_sixteen_current_season_teams():
    crosswalk = json.loads(
        (ROOT / "data" / "ligaf_team_profile_crosswalk.json").read_text(
            encoding="utf-8"
        )
    )
    registry = TeamIdentityRegistry.from_path(
        ROOT / "kini_engine" / "data" / "ligaf_team_identity_registry.json"
    )

    assert crosswalk["provider"] == "LIGA_F"
    assert crosswalk["competition_id"] == "LIGA_F"
    assert crosswalk["gender"] == "women"
    assert crosswalk["season"] == "2026-27"
    assert urlparse(crosswalk["source_archive_url"]).hostname == "ligaf.es"
    assert len(crosswalk["entries"]) == 16

    team_ids = set()
    provider_ids = set()
    for entry in crosswalk["entries"]:
        assert set(entry) == {
            "team_id",
            "canonical_name",
            "provider_team_profile_id",
            "team_profile_url",
            "match_evidence_url",
        }
        assert entry["team_id"] not in team_ids
        assert entry["provider_team_profile_id"] not in provider_ids
        team_ids.add(entry["team_id"])
        provider_ids.add(entry["provider_team_profile_id"])

        identity = registry.resolve(
            entry["canonical_name"],
            source="ligaf",
            competition_id="LIGA_F",
            season="2026-27",
            gender="women",
        )
        assert identity is not None
        assert identity.team_id == entry["team_id"]

        profile_url = urlparse(entry["team_profile_url"])
        assert profile_url.scheme == "https"
        assert profile_url.hostname == "ligaf.es"
        assert f"/{entry['provider_team_profile_id']}/plantilla/2027" in profile_url.path

        match_url = urlparse(entry["match_evidence_url"])
        assert match_url.scheme == "https"
        assert match_url.hostname == "ligaf.es"
        assert match_url.path.endswith("/detalle")


def test_ligaf_registry_resolves_both_provider_aliases_for_all_six_teams():
    fixtures = load_ligaf_fixture_evidence(EVIDENCE_PATH)
    expected = {
        ("Athletic Club", "Athletic Club (F)", "team:ligaf:athletic-club"),
        ("Real Madrid CF", "Real Madrid (F)", "team:ligaf:real-madrid-cf"),
        ("Logroño United", "Logroño (F)", "team:ligaf:logrono-united"),
        ("Sevilla FC", "Sevilla (F)", "team:ligaf:sevilla-fc"),
        ("SD Eibar", "Eibar (F)", "team:ligaf:sd-eibar"),
        ("Real Sociedad", "Real Sociedad (F)", "team:ligaf:real-sociedad"),
    }
    observed = set()
    for fixture in fixtures:
        observed.add(
            (
                fixture["home_team_name"],
                fixture["selae_home_display_name"],
                fixture["home_team_id"],
            )
        )
        observed.add(
            (
                fixture["away_team_name"],
                fixture["selae_away_display_name"],
                fixture["away_team_id"],
            )
        )
    assert observed == expected


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda doc: doc["entries"][0].update(
                match_url="https://example.org/partido/202723868/detalle"
            ),
            "official Liga F domain",
        ),
        (
            lambda doc: doc["entries"][0].update(coupon_sign="1"),
            "conflicts with the official score",
        ),
        (
            lambda doc: doc["entries"][0].update(kickoff_at="2026-11-07T16:00:00"),
            "must include a timezone offset",
        ),
        (
            lambda doc: doc["entries"][0].update(
                selae_home_display_name="Athletic Femenino (F)"
            ),
            "does not resolve",
        ),
        (
            lambda doc: doc["entries"][1].update(match_id="202723868"),
            "duplicate Liga F match_id",
        ),
        (
            lambda doc: doc["training_eligibility"].update(eligible=True),
            "must remain excluded from training",
        ),
    ],
)
def test_ligaf_evidence_rejects_invalid_records(tmp_path, mutate, message):
    document = _document()
    mutate(document)
    path = _write_document(tmp_path, document)

    with pytest.raises(LigaFEvidenceError, match=message):
        load_ligaf_fixture_evidence(path)


def test_ligaf_evidence_rejects_non_utc_verification_timestamp(tmp_path):
    document = _document()
    document["entries"][0]["evidence_checked_at_utc"] = "2026-11-15T10:39:37+01:00"
    path = _write_document(tmp_path, document)

    with pytest.raises(LigaFEvidenceError, match="must be UTC"):
        load_ligaf_fixture_evidence(path)


def test_ligaf_evidence_rejects_a_wrong_internal_team_id(tmp_path):
    document = _document()
    document["entries"][0]["home_team_id"] = "team:ligaf:wrong"
    path = _write_document(tmp_path, document)

    with pytest.raises(LigaFEvidenceError, match="does not resolve"):
        load_ligaf_fixture_evidence(path)


def test_ligaf_evidence_cannot_use_a_future_kickoff_for_a_past_coupon(tmp_path):
    document = _document()
    document["entries"][0]["kickoff_at"] = "2026-11-09T16:00:00+01:00"
    path = _write_document(tmp_path, document)

    with pytest.raises(LigaFEvidenceError, match="after the SELAE draw date"):
        load_ligaf_fixture_evidence(path)
