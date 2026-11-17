from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from kini_engine.core import Match
from kini_engine.coupon_identity import canonicalize_coupon


def _fixture_data():
    fixtures = []
    aliases = {}
    matches = []
    for number in range(1, 16):
        source_home = f"Home {number}"
        source_away = f"Away {number}"
        canonical_home = f"Canonical Home {number}"
        canonical_away = f"Canonical Away {number}"
        kickoff = datetime(2020, 12, 12 + (number > 10), 14, 0)
        home_goals, away_goals = (4, 0) if number == 15 else (1, 0)
        result = (
            "1"
            if home_goals > away_goals
            else ("2" if away_goals > home_goals else "X")
        )
        fixtures.append(
            {
                "number": number,
                "kickoff_at": kickoff.replace(
                    tzinfo=ZoneInfo("Europe/Madrid")
                ).isoformat(),
                "home": source_home,
                "away": source_away,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result": result,
            }
        )
        aliases[source_home] = canonical_home
        aliases[source_away] = canonical_away
        matches.append(
            Match(
                kickoff, canonical_home, canonical_away, home_goals, away_goals, result
            )
        )
    coupon = {"coupon_id": "2020-2021:21", "season": "2020-2021", "fixtures": fixtures}
    alias_document = {
        "schema_version": 1,
        "source": "historicoquiniela.com",
        "seasons": {"2020-2021": aliases},
    }
    return coupon, alias_document, matches


def test_canonicalize_coupon_reconciles_all_15_fixtures() -> None:
    coupon, alias_document, matches = _fixture_data()

    class FakeRegistry:
        def resolve(self, name: str, *, source: str) -> SimpleNamespace:
            assert source == "football-data"
            return SimpleNamespace(canonical_name=name)

    resolved, reconciliation = canonicalize_coupon(
        coupon, matches, alias_document=alias_document, registry=FakeRegistry()
    )
    assert len(reconciliation) == 15
    assert resolved["fixtures"][0]["source_home"] == "Home 1"
    assert resolved["fixtures"][0]["home"] == "Canonical Home 1"
    assert coupon["fixtures"][0]["home"] == "Home 1"
    assert reconciliation[0]["home_goals"] == 1
    assert reconciliation[0]["away_goals"] == 0
    assert reconciliation[0]["result"] == "1"
    assert reconciliation[14]["pleno_home_category"] == "M"
    assert reconciliation[14]["pleno_away_category"] == "0"


def test_canonicalize_coupon_rejects_unmapped_team() -> None:
    coupon, alias_document, matches = _fixture_data()
    del alias_document["seasons"]["2020-2021"]["Home 1"]

    class FakeRegistry:
        def resolve(self, name: str, *, source: str) -> SimpleNamespace:
            return SimpleNamespace(canonical_name=name)

    with pytest.raises(ValueError, match="no explicit home alias"):
        canonicalize_coupon(
            coupon, matches, alias_document=alias_document, registry=FakeRegistry()
        )


def test_canonicalize_coupon_rejects_date_or_score_mismatch() -> None:
    coupon, alias_document, matches = _fixture_data()
    wrong = matches[0]
    matches[0] = Match(wrong.date, wrong.home, wrong.away, 0, 0, "X")

    class FakeRegistry:
        def resolve(self, name: str, *, source: str) -> SimpleNamespace:
            return SimpleNamespace(canonical_name=name)

    with pytest.raises(ValueError, match="score/result mismatch"):
        canonicalize_coupon(
            coupon, matches, alias_document=alias_document, registry=FakeRegistry()
        )


def test_jornada_19_aliases_resolve_through_canonical_team_registry() -> None:
    from kini_engine.coupon_identity import load_coupon_team_aliases
    from kini_engine.team_identity import TeamIdentityRegistry

    aliases = load_coupon_team_aliases()["seasons"]["2020-2021"]
    registry = TeamIdentityRegistry.from_default()
    expected = {
        "Valencia": "Valencia",
        "Valladolid": "Valladolid",
        "Osasuna": "Osasuna",
        "Lugo": "Lugo",
        "Málaga": "Malaga",
        "Rayo Vallecano": "Vallecano",
        "Sabadell": "Sabadell",
        "R. Oviedo": "Oviedo",
    }

    for source_name, target_name in expected.items():
        assert aliases[source_name] == target_name
        assert registry.resolve(target_name, source="football-data") is not None


def test_jornada_22_cartagena_alias_resolves_through_canonical_registry() -> None:
    from kini_engine.coupon_identity import load_coupon_team_aliases
    from kini_engine.team_identity import TeamIdentityRegistry

    aliases = load_coupon_team_aliases()["seasons"]["2020-2021"]
    registry = TeamIdentityRegistry.from_default()

    assert aliases["Cartagena"] == "Cartagena"
    identity = registry.resolve("Cartagena", source="football-data")
    assert identity is not None
    assert identity.team_id == "team:es:cartagena"
    assert identity.canonical_name == "Cartagena"


def test_jornada_25_ponferradina_alias_resolves_through_canonical_registry() -> None:
    from kini_engine.coupon_identity import load_coupon_team_aliases
    from kini_engine.team_identity import TeamIdentityRegistry

    aliases = load_coupon_team_aliases()["seasons"]["2020-2021"]
    registry = TeamIdentityRegistry.from_default()

    assert aliases["Ponferradina"] == "Ponferradina"
    resolved = registry.resolve("Ponferradina", source="football-data")
    assert resolved is not None
    assert resolved.canonical_name == "Ponferradina"


def test_jornada_29_girona_and_castellon_aliases_resolve_through_canonical_registry() -> (
    None
):
    from kini_engine.coupon_identity import load_coupon_team_aliases
    from kini_engine.team_identity import TeamIdentityRegistry

    aliases = load_coupon_team_aliases()["seasons"]["2020-2021"]
    registry = TeamIdentityRegistry.from_default()
    expected = {
        "Girona": ("Girona", "team:es:girona"),
        "Castellón": ("Castellon", "team:es:castellon"),
    }

    for source_name, (target_name, team_id) in expected.items():
        assert aliases[source_name] == target_name
        resolved = registry.resolve(target_name, source="football-data")
        assert resolved is not None
        assert resolved.canonical_name == target_name
        assert resolved.team_id == team_id


def test_2021_2022_coupon_aliases_resolve_through_canonical_team_registry() -> None:
    from kini_engine.coupon_identity import load_coupon_team_aliases
    from kini_engine.team_identity import TeamIdentityRegistry

    aliases = load_coupon_team_aliases()["seasons"]["2021-2022"]
    registry = TeamIdentityRegistry.from_default()
    expected = {
        "Alavés": "Alaves",
        "Alcorcón": "Alcorcon",
        "Almería": "Almeria",
        "Amorebieta": "Amorebieta",
        "At. Madrid": "Ath Madrid",
        "Athletic Club": "Ath Bilbao",
        "Barcelona": "Barcelona",
        "Betis": "Betis",
        "Burgos": "Burgos",
        "Cádiz": "Cadiz",
        "Cartagena": "Cartagena",
        "Celta": "Celta",
        "Eibar": "Eibar",
        "Elche": "Elche",
        "Espanyol": "Espanol",
        "Fuenlabrada": "Fuenlabrada",
        "Getafe": "Getafe",
        "Girona": "Girona",
        "Granada": "Granada",
        "Huesca": "Huesca",
        "Ibiza": "Ibiza",
        "Las Palmas": "Las Palmas",
        "Leganés": "Leganes",
        "Levante": "Levante",
        "Lugo": "Lugo",
        "Málaga": "Malaga",
        "Mallorca": "Mallorca",
        "Mirandés": "Mirandes",
        "Osasuna": "Osasuna",
        "Ponferradina": "Ponferradina",
        "R. Oviedo": "Oviedo",
        "R. Sociedad B": "Sociedad B",
        "Rayo Vallecano": "Vallecano",
        "Real Madrid": "Real Madrid",
        "Real Sociedad": "Sociedad",
        "Real Sociedad B": "Sociedad B",
        "Sevilla": "Sevilla",
        "Sporting": "Sp Gijon",
        "Tenerife": "Tenerife",
        "Valencia": "Valencia",
        "Valladolid": "Valladolid",
        "Villarreal": "Villarreal",
    }

    assert aliases == expected
    for source_name, target_name in expected.items():
        identity = registry.resolve(target_name, source="football-data")
        assert identity is not None, source_name
        assert identity.canonical_name == target_name

    assert (
        registry.resolve("Sociedad B", source="football-data").team_id
        == "team:es:sociedad-b"
    )
    assert (
        registry.resolve("Burgos", source="football-data").team_id == "team:es:burgos"
    )
    assert (
        registry.resolve("Tenerife", source="football-data").team_id
        == "team:es:tenerife"
    )

def test_2022_2023_jornada_1_aliases_resolve_in_the_correct_competition_and_season() -> (
    None
):
    from kini_engine.coupon_identity import load_coupon_team_aliases
    from kini_engine.team_identity import TeamIdentityRegistry

    aliases = load_coupon_team_aliases()["seasons"]["2022-2023"]
    registry = TeamIdentityRegistry.from_default()
    expected = {
        "Celta": ("Celta", "SP1"),
        "Espanyol": ("Espanol", "SP1"),
        "Valladolid": ("Valladolid", "SP1"),
        "Villarreal": ("Villarreal", "SP1"),
        "Barcelona": ("Barcelona", "SP1"),
        "Rayo Vallecano": ("Vallecano", "SP1"),
        "Cádiz": ("Cadiz", "SP1"),
        "Real Sociedad": ("Sociedad", "SP1"),
        "Valencia": ("Valencia", "SP1"),
        "Girona": ("Girona", "SP1"),
        "Almería": ("Almeria", "SP1"),
        "Real Madrid": ("Real Madrid", "SP1"),
        "Athletic Club": ("Ath Bilbao", "SP1"),
        "Mallorca": ("Mallorca", "SP1"),
        "Getafe": ("Getafe", "SP1"),
        "At. Madrid": ("Ath Madrid", "SP1"),
        "Eibar": ("Eibar", "SP2"),
        "Tenerife": ("Tenerife", "SP2"),
        "Mirandés": ("Mirandes", "SP2"),
        "Sporting": ("Sp Gijon", "SP2"),
        "Leganés": ("Leganes", "SP2"),
        "Alavés": ("Alaves", "SP2"),
        "Las Palmas": ("Las Palmas", "SP2"),
        "Zaragoza": ("Zaragoza", "SP2"),
        "Racing": ("Santander", "SP2"),
        "Villarreal B": ("Villarreal B", "SP2"),
        "Ibiza": ("Ibiza", "SP2"),
        "Granada": ("Granada", "SP2"),
        "Betis": ("Betis", "SP1"),
        "Elche": ("Elche", "SP1"),
    }

    assert aliases == {source: target for source, (target, _) in expected.items()}
    for source_name, (target_name, competition_id) in expected.items():
        identity = registry.resolve(
            target_name,
            source="football-data",
            competition_id=competition_id,
            season="2223",
        )
        assert identity is not None, source_name
        assert identity.canonical_name == target_name
