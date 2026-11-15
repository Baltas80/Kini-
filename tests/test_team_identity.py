from __future__ import annotations

import json
from pathlib import Path

import pytest

from kini_engine.team_identity import (
    AmbiguousTeamIdentityError,
    TeamIdentityRegistry,
    TeamIdentityRegistryError,
    normalize_team_name,
)
from scripts.validate_team_identity_registry import validate_csv_references


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "kini_engine" / "data" / "team_identity_registry.json"


def test_packaged_default_registry_is_available():
    assert TeamIdentityRegistry.from_default().team_count == 56


def test_default_registry_resolves_exact_football_data_alias_with_scope():
    registry = TeamIdentityRegistry.from_path(REGISTRY_PATH)

    identity = registry.resolve(
        "  ATH BILBAO  ",
        source="Football-Data",
        competition_id="sp1",
        season="2425",
        gender="men",
    )

    assert identity is not None
    assert identity.team_id == "team:es:ath-bilbao"
    assert identity.canonical_name == "Ath Bilbao"


def test_default_registry_rejects_wrong_competition_or_season():
    registry = TeamIdentityRegistry.from_path(REGISTRY_PATH)

    assert registry.resolve(
        "Ath Bilbao",
        source="football-data",
        competition_id="SP2",
        season="2425",
        gender="men",
    ) is None
    assert registry.resolve(
        "Malaga",
        source="football-data",
        competition_id="SP1",
        season="2425",
        gender="men",
    ) is None


def test_aliases_are_provider_scoped_and_never_fuzzy():
    registry = TeamIdentityRegistry.from_path(REGISTRY_PATH)

    assert registry.resolve("Real Madrid", source="selae", gender="men") is None
    assert registry.resolve("Athletic Club", source="football-data", gender="men") is None
    assert registry.resolve("Ath Bilbao FC", source="football-data", gender="men") is None


def test_name_normalization_preserves_accents_and_punctuation():
    assert normalize_team_name("  MÁLAGA\u00a0CF ") == "málaga cf"
    registry = TeamIdentityRegistry.from_path(REGISTRY_PATH)
    assert registry.resolve("Malaga", source="football-data", gender="men") is not None
    assert registry.resolve("Málaga", source="football-data", gender="men") is None


def test_ambiguous_exact_alias_requires_gender_disambiguation():
    registry = TeamIdentityRegistry({
        "schema_version": 1,
        "registry_id": "test",
        "teams": [
            {
                "team_id": "team:men:barcelona",
                "canonical_name": "Barcelona men",
                "gender": "men",
                "aliases": [{"source": "selae", "name": "Barcelona"}],
            },
            {
                "team_id": "team:women:barcelona",
                "canonical_name": "Barcelona women",
                "gender": "women",
                "aliases": [{"source": "selae", "name": "Barcelona"}],
            },
        ],
    })

    with pytest.raises(AmbiguousTeamIdentityError, match="ambiguous team alias"):
        registry.resolve("Barcelona", source="selae")
    assert (
        registry.resolve("Barcelona", source="selae", gender="women").team_id
        == "team:women:barcelona"
    )


def test_registry_rejects_duplicate_ids():
    team = {
        "team_id": "team:duplicate",
        "canonical_name": "A",
        "gender": "men",
        "aliases": [{"source": "x", "name": "A"}],
    }
    with pytest.raises(TeamIdentityRegistryError, match="duplicate team_id"):
        TeamIdentityRegistry({"schema_version": 1, "teams": [team, dict(team)]})


def test_registry_rejects_duplicate_participation_scope():
    document = {
        "schema_version": 1,
        "teams": [{
            "team_id": "team:a",
            "canonical_name": "A",
            "gender": "men",
            "aliases": [{
                "source": "football-data",
                "name": "A",
                "participations": [
                    {"competition_id": "SP1", "season": "2425"},
                    {"competition_id": "SP1", "season": "2425"},
                ],
            }],
        }],
    }
    with pytest.raises(TeamIdentityRegistryError, match="duplicate participation"):
        TeamIdentityRegistry(document)


def test_csv_validator_checks_every_home_and_away_reference(tmp_path: Path):
    csv_path = tmp_path / "history.csv"
    csv_path.write_text(
        "Div,Season,HomeTeam,AwayTeam\n"
        "SP1,2425,Ath Bilbao,Real Madrid\n"
        "SP2,2425,Albacete,Malaga\n",
        encoding="utf-8",
    )
    registry = TeamIdentityRegistry.from_path(REGISTRY_PATH)

    report = validate_csv_references(csv_path, registry)

    assert report["fixture_count"] == 2
    assert report["team_reference_count"] == 4
    assert report["resolved_references"] == 4
    assert report["resolved_unique_team_ids"] == 4
    assert report["unresolved_count"] == 0
    assert report["ambiguous_count"] == 0
    assert report["success"] is True


def test_csv_validator_reports_unregistered_alias_instead_of_guessing(tmp_path: Path):
    csv_path = tmp_path / "unknown.csv"
    csv_path.write_text(
        "Div,Season,HomeTeam,AwayTeam\n"
        "SP1,2425,Athletic Club,Real Madrid\n",
        encoding="utf-8",
    )
    report = validate_csv_references(
        csv_path, TeamIdentityRegistry.from_path(REGISTRY_PATH)
    )

    assert report["success"] is False
    assert report["unresolved_count"] == 1
    assert report["unresolved_examples"][0]["name"] == "Athletic Club"
    assert report["unresolved_examples"][0]["reason"] == "no_exact_scoped_alias"


def test_default_registry_contains_all_source_teams_and_provenance():
    document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    registry = TeamIdentityRegistry(document)

    assert registry.team_count == 56
    assert document["source_dataset"]["fixture_count"] == 5311
    assert document["source_dataset"]["team_reference_count"] == 10622
    assert (
        document["source_dataset"]["csv_sha256"]
        == "a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab"
    )
