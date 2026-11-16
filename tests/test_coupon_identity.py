from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from kini_engine.coupon_identity import canonicalize_coupon
from kini_engine.core import Match


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
        result = "1" if home_goals > away_goals else ("2" if away_goals > home_goals else "X")
        fixtures.append(
            {
                "number": number,
                "kickoff_at": kickoff.replace(tzinfo=ZoneInfo("Europe/Madrid")).isoformat(),
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
            Match(kickoff, canonical_home, canonical_away, home_goals, away_goals, result)
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
