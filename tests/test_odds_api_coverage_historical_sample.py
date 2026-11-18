from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.probe_the_odds_api_coverage import (
    load_historical_sample_fixtures,
    load_probe_fixture_bundle,
)


def _entry(
    *,
    kickoff_at: str = "2025-03-08T17:30:00+01:00",
    evidence_checked_at_utc: str = "2026-11-18T13:40:08Z",
) -> dict[str, str]:
    return {
        "sample_id": "sp1-2425-valencia-valladolid",
        "fixture_date": "2025-03-08",
        "season": "2425",
        "competition_id": "SP1",
        "gender": "men",
        "home_football_data_name": "Valencia",
        "away_football_data_name": "Valladolid",
        "kickoff_at": kickoff_at,
        "schedule_source": "LaLiga official match page",
        "evidence_url": "https://www.laliga.com/example-fixture",
        "evidence_checked_at_utc": evidence_checked_at_utc,
    }


def _write_sample(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "verified_schedule_sample",
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )


def test_historical_sample_loader_validates_timezone_and_identity(tmp_path):
    path = tmp_path / "sample.json"
    _write_sample(path, [_entry()])

    fixtures, digest = load_historical_sample_fixtures(path)

    assert len(fixtures) == 1
    assert fixtures[0].sample_id == "sp1-2425-valencia-valladolid"
    assert fixtures[0].fixture_date == "2025-03-08"
    assert fixtures[0].season == "2425"
    assert fixtures[0].draw_date is None
    assert fixtures[0].position is None
    assert fixtures[0].kickoff_at == datetime(2025, 3, 8, 16, 30, tzinfo=UTC)
    assert len(fixtures[0].fixture_id) == 64
    assert len(digest) == 64


def test_historical_sample_loader_rejects_timezone_naive_kickoff(tmp_path):
    path = tmp_path / "sample.json"
    _write_sample(path, [_entry(kickoff_at="2025-03-08T17:30:00")])

    with pytest.raises(ValueError, match="explicit timezone"):
        load_historical_sample_fixtures(path)


def test_historical_sample_loader_requires_utc_evidence_timestamp(tmp_path):
    path = tmp_path / "sample.json"
    _write_sample(path, [_entry(evidence_checked_at_utc="2026-11-18T14:40:08+01:00")])

    with pytest.raises(ValueError, match="must use UTC"):
        load_historical_sample_fixtures(path)


def test_historical_sample_loader_rejects_fixture_date_mismatch(tmp_path):
    path = tmp_path / "sample.json"
    entry = _entry()
    entry["fixture_date"] = "2025-03-09"
    _write_sample(path, [entry])

    with pytest.raises(ValueError, match="local date"):
        load_historical_sample_fixtures(path)


def test_checked_in_bundle_has_six_historical_and_ten_current_fixtures():
    root = Path(__file__).resolve().parents[1]
    fixtures, bundle_digest = load_probe_fixture_bundle(
        root / "data/selae_fixture_crosswalk.json",
        root / "data/odds_api_coverage_historical_sample.json",
    )

    assert len(fixtures) == 16
    assert len({fixture.fixture_id for fixture in fixtures}) == 16
    assert {fixture.competition_id for fixture in fixtures} == {"SP1", "SP2"}
    assert len([fixture for fixture in fixtures if fixture.sample_id is not None]) == 6
    assert {fixture.season for fixture in fixtures if fixture.sample_id is not None} == {
        "2021",
        "2122",
        "2223",
        "2324",
        "2425",
        "2526",
    }
    assert len(bundle_digest) == 64


def test_fixture_bundle_combines_sources(tmp_path):
    crosswalk = tmp_path / "crosswalk.json"
    crosswalk.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "draw_date": "2026-11-08",
                        "position": 1,
                        "competition_id": "SP2",
                        "gender": "men",
                        "home_football_data_name": "Malaga",
                        "away_football_data_name": "Santander",
                        "kickoff_at": "2026-11-07T14:00:00+01:00",
                        "schedule_source": "Official schedule",
                        "evidence_url": "https://example.com/schedule",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sample = tmp_path / "sample.json"
    _write_sample(sample, [_entry()])

    fixtures, digest = load_probe_fixture_bundle(crosswalk, sample)

    assert len(fixtures) == 2
    assert len({fixture.fixture_id for fixture in fixtures}) == 2
    assert len(digest) == 64


def test_historical_sample_loader_rejects_duplicate_sample_id(tmp_path):
    path = tmp_path / "sample.json"
    entries = [_entry(), {**_entry(), "home_football_data_name": "Other Home"}]
    _write_sample(path, entries)

    with pytest.raises(ValueError, match="Duplicate historical sample_id"):
        load_historical_sample_fixtures(path)


def test_historical_sample_loader_rejects_duplicate_fixture_key(tmp_path):
    path = tmp_path / "sample.json"
    entries = [
        _entry(),
        {**_entry(), "sample_id": "different-id"},
    ]
    _write_sample(path, entries)

    with pytest.raises(ValueError, match="Duplicate historical sample fixture"):
        load_historical_sample_fixtures(path)
