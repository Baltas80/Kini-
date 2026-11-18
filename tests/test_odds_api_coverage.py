import argparse
import json
from datetime import UTC, datetime

import pytest

from scripts.probe_the_odds_api_coverage import (
    ProbeFixture,
    TheOddsApiCoverageClient,
    load_probe_fixtures,
    parse_lead_hours,
    probe_coverage,
)


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.content = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {url}")
        return self.responses.pop(0)


def fixture():
    return ProbeFixture(
        draw_date="2026-11-08",
        position=1,
        competition_id="SP1",
        sport_key="soccer_spain_la_liga",
        home_team="Malaga",
        away_team="Santander",
        kickoff_at=datetime(2026, 11, 7, 13, 0, tzinfo=UTC),
        schedule_source="Official club schedule",
        evidence_url="https://example.com/official-schedule",
    )


def event_payload(
    *,
    timestamp="2026-11-07T06:55:00Z",
    home="Malaga",
    away="Santander",
    commence_time="2026-11-07T13:00:00Z",
):
    return {
        "timestamp": timestamp,
        "previous_timestamp": "2026-11-07T06:50:00Z",
        "next_timestamp": "2026-11-07T07:00:00Z",
        "data": [
            {
                "id": "event-123",
                "sport_key": "soccer_spain_la_liga",
                "home_team": home,
                "away_team": away,
                "commence_time": commence_time,
            }
        ],
    }


def markets_payload():
    return {
        "timestamp": "2026-11-07T06:55:00Z",
        "previous_timestamp": "2026-11-07T06:50:00Z",
        "next_timestamp": "2026-11-07T07:00:00Z",
        "data": {
            "id": "event-123",
            "sport_key": "soccer_spain_la_liga",
            "home_team": "Malaga",
            "away_team": "Santander",
            "commence_time": "2026-11-07T13:00:00Z",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "markets": [{"key": "h2h"}],
                },
                {
                    "key": "betfair",
                    "title": "Betfair",
                    "markets": [{"key": "totals"}],
                },
            ],
        },
    }


def test_load_probe_fixtures_keeps_only_verified_mens_sp1_sp2(tmp_path):
    path = tmp_path / "crosswalk.json"
    payload = {
        "schema_version": 1,
        "entries": [
            {
                "draw_date": "2026-11-08",
                "position": 1,
                "competition_id": "SP1",
                "gender": "men",
                "home_football_data_name": "Malaga",
                "away_football_data_name": "Santander",
                "kickoff_at": "2026-11-07T14:00:00+01:00",
                "schedule_source": "Official club schedule",
                "evidence_url": "https://example.com/official-schedule",
            },
            {
                "draw_date": "2026-11-08",
                "position": 2,
                "competition_id": "SP1",
                "gender": "women",
                "home_football_data_name": "Women A",
                "away_football_data_name": "Women B",
                "kickoff_at": "2026-11-07T15:00:00+01:00",
            },
            {
                "draw_date": "2026-11-08",
                "position": 3,
                "competition_id": "CUP",
                "gender": "men",
                "home_football_data_name": "Cup A",
                "away_football_data_name": "Cup B",
                "kickoff_at": "2026-11-07T16:00:00+01:00",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    fixtures, digest = load_probe_fixtures(path)

    assert len(fixtures) == 1
    assert fixtures[0].sport_key == "soccer_spain_la_liga"
    assert fixtures[0].kickoff_at == datetime(2026, 11, 7, 13, 0, tzinfo=UTC)
    assert len(digest) == 64


def test_load_probe_fixtures_rejects_timezone_naive_kickoff(tmp_path):
    path = tmp_path / "crosswalk.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "draw_date": "2026-11-08",
                        "position": 1,
                        "competition_id": "SP1",
                        "gender": "men",
                        "home_football_data_name": "Malaga",
                        "away_football_data_name": "Santander",
                        "kickoff_at": "2026-11-07T14:00:00",
                        "schedule_source": "Official club schedule",
                        "evidence_url": "https://example.com/official-schedule",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit timezone"):
        load_probe_fixtures(path)


def test_parse_lead_hours_requires_positive_unique_finite_values():
    assert parse_lead_hours("24, 6, 1") == (24.0, 6.0, 1.0)
    for value in ("0,6", "-1", "nan", "6,6", ""):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_lead_hours(value)


def test_probe_records_exact_match_snapshot_hashes_and_h2h_bookmakers():
    session = FakeSession(
        [
            FakeResponse(
                event_payload(),
                {
                    "x-requests-used": "1",
                    "x-requests-remaining": "499",
                    "x-requests-last": "1",
                },
            ),
            FakeResponse(
                markets_payload(),
                {
                    "x-requests-used": "2",
                    "x-requests-remaining": "498",
                    "x-requests-last": "1",
                },
            ),
        ]
    )
    client = TheOddsApiCoverageClient("test-api-key", session=session)

    report = probe_coverage([fixture()], (6.0,), client)

    row = report["results"][0]
    assert row["match_status"] == "exact"
    assert row["snapshot_is_pre_kickoff"] is True
    assert row["coverage_status"] == "h2h_available"
    assert row["event_id"] == "event-123"
    assert row["events_snapshot_timestamp"] == "2026-11-07T06:55:00Z"
    assert row["events_snapshot_staleness_seconds"] == 300
    assert row["market_snapshot_staleness_seconds"] == 300
    assert row["bookmaker_keys"] == ["betfair", "pinnacle"]
    assert row["h2h_bookmaker_keys"] == ["pinnacle"]
    assert len(row["events_response_sha256"]) == 64
    assert len(row["market_response_sha256"]) == 64
    assert report["api_request_count"] == 2
    assert report["estimated_credits_upper_bound"] == 2
    assert report["reported_credits_last_sum"] == 2
    assert report["historical_odds_prices_requested"] is False
    assert report["production_dataset_modified"] is False
    assert report["eligible_for_model_input"] is False
    assert len(session.calls) == 2
    for url, kwargs in session.calls:
        assert "/historical/sports/" in url
        assert "/odds" not in url
        assert kwargs["headers"]["x-api-key"] == "test-api-key"
        assert "apiKey" not in url
        assert kwargs["timeout"] > 0


def test_probe_does_not_fuzzy_match_team_aliases_or_query_market_endpoint():
    session = FakeSession([FakeResponse(event_payload(home="Málaga"))])
    client = TheOddsApiCoverageClient("test-api-key", session=session)

    report = probe_coverage([fixture()], (6.0,), client)

    row = report["results"][0]
    assert row["match_status"] == "no_exact_match"
    assert row["coverage_status"] == "no_exact_event_match"
    assert row["event_id"] is None
    assert row["candidate_events"][0]["home_team"] == "Málaga"
    assert len(session.calls) == 1


def test_probe_rejects_participant_match_with_kickoff_delta_over_tolerance():
    session = FakeSession(
        [FakeResponse(event_payload(commence_time="2026-11-07T16:00:00Z"))]
    )
    client = TheOddsApiCoverageClient("test-api-key", session=session)

    report = probe_coverage([fixture()], (6.0,), client)

    row = report["results"][0]
    assert row["participant_match_count"] == 1
    assert row["kickoff_mismatch_count"] == 1
    assert row["match_status"] == "kickoff_mismatch"
    assert row["coverage_status"] == "kickoff_mismatch"
    assert row["event_id"] is None
    assert len(session.calls) == 1


def test_probe_skips_market_lookup_when_snapshot_is_after_provider_kickoff():
    session = FakeSession(
        [FakeResponse(event_payload(commence_time="2026-11-07T11:30:00Z"))]
    )
    client = TheOddsApiCoverageClient("test-api-key", session=session)

    report = probe_coverage([fixture()], (1.0,), client)

    row = report["results"][0]
    assert row["match_status"] == "exact"
    assert row["kickoff_delta_seconds"] == -5400
    assert row["snapshot_is_pre_kickoff"] is False
    assert row["coverage_status"] == "snapshot_not_pre_kickoff"
    assert row["h2h_market_available"] is False
    assert row["event_id"] == "event-123"
    assert len(session.calls) == 1


def test_probe_rejects_snapshot_later_than_requested_time():
    session = FakeSession(
        [FakeResponse(event_payload(timestamp="2026-11-07T07:05:00Z"))]
    )
    client = TheOddsApiCoverageClient("test-api-key", session=session)

    with pytest.raises(ValueError, match="future snapshot"):
        probe_coverage([fixture()], (6.0,), client)


def test_probe_rejects_mismatched_market_event_id():
    payload = markets_payload()
    payload["data"]["id"] = "different-event"
    session = FakeSession(
        [
            FakeResponse(event_payload()),
            FakeResponse(payload),
        ]
    )
    client = TheOddsApiCoverageClient("test-api-key", session=session)

    with pytest.raises(ValueError, match="mismatched event ID"):
        probe_coverage([fixture()], (6.0,), client)
