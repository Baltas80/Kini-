from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

API_BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEYS = {
    "SP1": "soccer_spain_la_liga",
    "SP2": "soccer_spain_segunda_division",
}
DEFAULT_LEAD_HOURS = (24.0, 6.0, 1.0)
DEFAULT_REGION = "eu"
REQUEST_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ProbeFixture:
    draw_date: str
    position: int
    competition_id: str
    sport_key: str
    home_team: str
    away_team: str
    kickoff_at: datetime
    schedule_source: str
    evidence_url: str

    @property
    def fixture_id(self) -> str:
        identity = {
            "draw_date": self.draw_date,
            "position": self.position,
            "competition_id": self.competition_id,
            "kickoff_at": _format_timestamp(self.kickoff_at),
            "home_team": self.home_team,
            "away_team": self.away_team,
        }
        payload = json.dumps(
            identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_aware_datetime(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include an explicit timezone")
    return parsed.astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _exact_name_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def load_probe_fixtures(path: str | Path) -> tuple[list[ProbeFixture], str]:
    """Load only verified men's SP1/SP2 fixtures from the official crosswalk."""
    source_path = Path(path)
    raw_bytes = source_path.read_bytes()
    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid crosswalk JSON: {source_path}") from exc

    if not isinstance(payload, dict):
        raise TypeError("SELAE crosswalk must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported SELAE crosswalk schema")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise TypeError("SELAE crosswalk entries must be a list")

    fixtures: list[ProbeFixture] = []
    seen: set[tuple[str, str, int]] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise TypeError(f"Crosswalk entry {index} must be an object")
        if entry.get("gender") != "men":
            continue

        competition_id = entry.get("competition_id")
        if competition_id not in SPORT_KEYS:
            continue

        home = entry.get("home_football_data_name")
        away = entry.get("away_football_data_name")
        draw_date = entry.get("draw_date")
        position = entry.get("position")
        schedule_source = entry.get("schedule_source")
        evidence_url = entry.get("evidence_url")
        if not isinstance(home, str) or not home.strip():
            raise ValueError(f"Crosswalk entry {index} has no canonical home name")
        if not isinstance(away, str) or not away.strip():
            raise ValueError(f"Crosswalk entry {index} has no canonical away name")
        if not isinstance(draw_date, str) or not draw_date.strip():
            raise ValueError(f"Crosswalk entry {index} has no draw date")
        if isinstance(position, bool) or not isinstance(position, int) or position < 1:
            raise ValueError(f"Crosswalk entry {index} has an invalid position")
        if not isinstance(schedule_source, str) or not schedule_source.strip():
            raise ValueError(f"Crosswalk entry {index} has no official schedule source")
        if (
            not isinstance(evidence_url, str)
            or not evidence_url.startswith("https://")
        ):
            raise ValueError(f"Crosswalk entry {index} has no HTTPS schedule evidence URL")

        kickoff_at = _parse_aware_datetime(
            entry.get("kickoff_at"), f"Crosswalk entry {index} kickoff_at"
        )
        duplicate_key = (draw_date, competition_id, position)
        if duplicate_key in seen:
            raise ValueError(f"Duplicate crosswalk fixture key: {duplicate_key}")
        seen.add(duplicate_key)

        fixtures.append(
            ProbeFixture(
                draw_date=draw_date,
                position=position,
                competition_id=competition_id,
                sport_key=SPORT_KEYS[competition_id],
                home_team=home.strip(),
                away_team=away.strip(),
                kickoff_at=kickoff_at,
                schedule_source=schedule_source.strip(),
                evidence_url=evidence_url.strip(),
            )
        )

    if not fixtures:
        raise ValueError("Crosswalk contains no verified men's SP1/SP2 fixtures")
    fixtures.sort(
        key=lambda fixture: (
            fixture.kickoff_at,
            fixture.competition_id,
            fixture.position,
        )
    )
    return fixtures, hashlib.sha256(raw_bytes).hexdigest()


def parse_lead_hours(value: str) -> tuple[float, ...]:
    try:
        hours = tuple(float(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "lead hours must be comma-separated positive numbers"
        ) from exc
    if not hours or any(not math.isfinite(item) or item <= 0 for item in hours):
        raise argparse.ArgumentTypeError(
            "lead hours must contain positive finite numbers"
        )
    if len(set(hours)) != len(hours):
        raise argparse.ArgumentTypeError("lead hours must not contain duplicates")
    return hours


def _response_sha256(response: Any, payload: dict[str, Any]) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        raw = content
    else:
        raw = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _usage_headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", {}) or {}
    wanted = ("x-requests-used", "x-requests-remaining", "x-requests-last")
    output: dict[str, str] = {}
    for name in wanted:
        value = headers.get(name)
        if value is None:
            value = headers.get(name.title())
        if value is not None:
            output[name] = str(value)
    return output


class TheOddsApiCoverageClient:
    """Read-only client for The Odds API's free historical coverage endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        session: Any | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("The Odds API key must be a non-empty string")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("request timeout must be a positive finite number")
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.request_count = 0
        self.reported_last_credits: list[float] = []

    def _get_json(
        self, path: str, params: dict[str, str]
    ) -> tuple[dict[str, Any], str, dict[str, str]]:
        url = f"{API_BASE_URL}{path}"
        response = self.session.get(
            url,
            params=params,
            headers={
                "x-api-key": self.api_key,
                "Accept": "application/json",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"The Odds API returned invalid JSON for {path}") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"The Odds API returned a non-object response for {path}")

        usage = _usage_headers(response)
        last_cost = usage.get("x-requests-last")
        if last_cost is not None:
            try:
                parsed_cost = float(last_cost)
            except ValueError:
                pass
            else:
                if math.isfinite(parsed_cost) and parsed_cost >= 0:
                    self.reported_last_credits.append(parsed_cost)

        self.request_count += 1
        return payload, _response_sha256(response, payload), usage

    @staticmethod
    def _snapshot_timestamp(
        payload: dict[str, Any], requested_at: datetime, endpoint: str
    ) -> datetime:
        snapshot = _parse_aware_datetime(payload.get("timestamp"), f"{endpoint} timestamp")
        if snapshot > requested_at:
            raise ValueError(
                f"{endpoint} returned a future snapshot: "
                f"{_format_timestamp(snapshot)} > {_format_timestamp(requested_at)}"
            )
        return snapshot

    def historical_events(
        self, fixture: ProbeFixture, requested_at: datetime
    ) -> tuple[list[dict[str, str]], datetime, str, dict[str, str]]:
        """Discover event IDs and participants without downloading odds prices."""
        window = timedelta(hours=12)
        params = {
            "date": _format_timestamp(requested_at),
            "dateFormat": "iso",
            "commenceTimeFrom": _format_timestamp(fixture.kickoff_at - window),
            "commenceTimeTo": _format_timestamp(fixture.kickoff_at + window),
        }
        payload, digest, usage = self._get_json(
            f"/historical/sports/{fixture.sport_key}/events", params
        )
        snapshot = self._snapshot_timestamp(payload, requested_at, "historical events")
        raw_events = payload.get("data")
        if not isinstance(raw_events, list):
            raise TypeError("Historical events response data must be a list")

        events: list[dict[str, str]] = []
        for index, raw_event in enumerate(raw_events, start=1):
            if not isinstance(raw_event, dict):
                raise TypeError(f"Historical event {index} must be an object")
            event_id = raw_event.get("id")
            home = raw_event.get("home_team")
            away = raw_event.get("away_team")
            commence_time = raw_event.get("commence_time")
            if not all(isinstance(value, str) and value.strip() for value in (
                event_id, home, away, commence_time
            )):
                raise ValueError(f"Historical event {index} is missing identity fields")
            parsed_commence = _parse_aware_datetime(
                commence_time, f"Historical event {event_id} commence_time"
            )
            events.append(
                {
                    "id": event_id,
                    "home_team": home,
                    "away_team": away,
                    "commence_time": commence_time,
                    "kickoff_delta_seconds": str(
                        int((parsed_commence - fixture.kickoff_at).total_seconds())
                    ),
                }
            )
        return events, snapshot, digest, usage

    def historical_event_markets(
        self,
        fixture: ProbeFixture,
        event_id: str,
        requested_at: datetime,
        region: str,
    ) -> tuple[dict[str, Any], datetime, str, dict[str, str]]:
        """Inspect bookmaker market keys only; this endpoint returns no prices."""
        params = {
            "date": _format_timestamp(requested_at),
            "dateFormat": "iso",
            "regions": region,
        }
        payload, digest, usage = self._get_json(
            f"/historical/sports/{fixture.sport_key}/events/{event_id}/markets",
            params,
        )
        snapshot = self._snapshot_timestamp(
            payload, requested_at, "historical event markets"
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TypeError("Historical event markets data must be an object")
        if data.get("id") != event_id:
            raise ValueError("Historical event markets response has a mismatched event ID")

        bookmakers = data.get("bookmakers", [])
        if not isinstance(bookmakers, list):
            raise TypeError("Historical event markets bookmakers must be a list")

        market_keys_by_bookmaker: dict[str, list[str]] = {}
        for index, bookmaker in enumerate(bookmakers, start=1):
            if not isinstance(bookmaker, dict):
                raise TypeError(f"Bookmaker {index} must be an object")
            key = bookmaker.get("key")
            markets = bookmaker.get("markets", [])
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"Bookmaker {index} has no key")
            if not isinstance(markets, list):
                raise TypeError(f"Bookmaker {key} markets must be a list")
            keys: set[str] = set()
            for market in markets:
                if not isinstance(market, dict) or not isinstance(market.get("key"), str):
                    raise TypeError(f"Bookmaker {key} has a malformed market entry")
                keys.add(market["key"])
            market_keys_by_bookmaker[key] = sorted(keys)

        bookmaker_keys = sorted(market_keys_by_bookmaker)
        h2h_bookmaker_keys = sorted(
            key
            for key, market_keys in market_keys_by_bookmaker.items()
            if "h2h" in market_keys
        )
        return (
            {
                "bookmaker_keys": bookmaker_keys,
                "h2h_bookmaker_keys": h2h_bookmaker_keys,
                "h2h_market_available": bool(h2h_bookmaker_keys),
                "market_keys_by_bookmaker": market_keys_by_bookmaker,
            },
            snapshot,
            digest,
            usage,
        )


def probe_coverage(
    fixtures: list[ProbeFixture],
    lead_hours: tuple[float, ...],
    client: TheOddsApiCoverageClient,
    *,
    region: str = DEFAULT_REGION,
    crosswalk_sha256: str | None = None,
) -> dict[str, Any]:
    if not fixtures:
        raise ValueError("At least one fixture is required")
    if not lead_hours or any(
        not math.isfinite(value) or value <= 0 for value in lead_hours
    ):
        raise ValueError("Lead hours must be positive finite values")
    if not isinstance(region, str) or not region.strip():
        raise ValueError("Bookmaker region must not be empty")
    region = region.strip()
    if "," in region:
        raise ValueError("Probe one bookmaker region per run to keep credit estimates exact")

    results: list[dict[str, Any]] = []
    for fixture in fixtures:
        for lead in lead_hours:
            requested_at = fixture.kickoff_at - timedelta(hours=lead)
            if requested_at >= fixture.kickoff_at:
                raise ValueError("Coverage snapshot must precede kickoff")

            events, event_snapshot, event_digest, event_usage = (
                client.historical_events(fixture, requested_at)
            )
            exact_matches = [
                event
                for event in events
                if _exact_name_key(event["home_team"])
                == _exact_name_key(fixture.home_team)
                and _exact_name_key(event["away_team"])
                == _exact_name_key(fixture.away_team)
            ]

            row: dict[str, Any] = {
                "fixture_id": fixture.fixture_id,
                "draw_date": fixture.draw_date,
                "position": fixture.position,
                "competition_id": fixture.competition_id,
                "sport_key": fixture.sport_key,
                "target_home_team": fixture.home_team,
                "target_away_team": fixture.away_team,
                "official_kickoff_at": _format_timestamp(fixture.kickoff_at),
                "schedule_source": fixture.schedule_source,
                "schedule_evidence_url": fixture.evidence_url,
                "requested_lead_hours": lead,
                "requested_at": _format_timestamp(requested_at),
                "region": region,
                "events_snapshot_timestamp": _format_timestamp(event_snapshot),
                "events_snapshot_staleness_seconds": int(
                    (requested_at - event_snapshot).total_seconds()
                ),
                "events_response_sha256": event_digest,
                "events_usage": event_usage,
                "candidate_event_count": len(events),
                "candidate_events": events,
                "exact_match_count": len(exact_matches),
                "match_status": (
                    "exact"
                    if len(exact_matches) == 1
                    else ("ambiguous" if exact_matches else "no_exact_match")
                ),
                "event_id": None,
                "market_snapshot_timestamp": None,
                "market_snapshot_staleness_seconds": None,
                "market_response_sha256": None,
                "market_usage": None,
                "bookmaker_keys": [],
                "h2h_bookmaker_keys": [],
                "h2h_market_available": False,
                "market_keys_by_bookmaker": {},
            }

            if len(exact_matches) == 1:
                event = exact_matches[0]
                event_id = event["id"]
                markets, market_snapshot, market_digest, market_usage = (
                    client.historical_event_markets(
                        fixture, event_id, requested_at, region
                    )
                )
                row.update(
                    {
                        "event_id": event_id,
                        "provider_home_team": event["home_team"],
                        "provider_away_team": event["away_team"],
                        "provider_commence_time": event["commence_time"],
                        "kickoff_delta_seconds": int(event["kickoff_delta_seconds"]),
                        "market_snapshot_timestamp": _format_timestamp(market_snapshot),
                        "market_snapshot_staleness_seconds": int(
                            (requested_at - market_snapshot).total_seconds()
                        ),
                        "market_response_sha256": market_digest,
                        "market_usage": market_usage,
                        **markets,
                    }
                )
                row["coverage_status"] = (
                    "h2h_available"
                    if markets["h2h_market_available"]
                    else "event_found_without_h2h"
                )
            elif exact_matches:
                row["coverage_status"] = "ambiguous_exact_event_match"
            else:
                row["coverage_status"] = "no_exact_event_match"

            results.append(row)

    reported_credits = (
        round(sum(client.reported_last_credits), 6)
        if len(client.reported_last_credits) == client.request_count
        else None
    )
    return {
        "schema_version": 1,
        "provider": "The Odds API",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "crosswalk_sha256": crosswalk_sha256,
        "sport_keys": SPORT_KEYS,
        "region": region,
        "lead_hours": list(lead_hours),
        "fixture_probe_count": len(results),
        "api_request_count": client.request_count,
        "estimated_credits_upper_bound": client.request_count,
        "reported_credits_last_sum": reported_credits,
        "historical_odds_prices_requested": False,
        "production_dataset_modified": False,
        "eligible_for_model_input": False,
        "results": results,
        "limitations": [
            "This probe uses historical events and historical event markets endpoints only.",
            "No odds prices are downloaded; the paid historical odds endpoint is not called.",
            "Only exact normalized home/away name matches are accepted; no fuzzy team matching is used.",
            "The supplied crosswalk is a sample, not a complete league-season coverage census.",
            "Coverage metadata does not establish redistribution rights or commercial licensing.",
        ],
    }


def write_report(report: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe The Odds API historical Spanish SP1/SP2 event and h2h market "
            "coverage without downloading odds prices."
        )
    )
    parser.add_argument(
        "--crosswalk",
        type=Path,
        default=Path("data/selae_fixture_crosswalk.json"),
        help="Verified SELAE-to-Football-Data fixture crosswalk",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/the_odds_api_coverage.json"),
        help="Local JSON report path (the default artifacts/ directory is gitignored)",
    )
    parser.add_argument(
        "--api-key-env",
        default="THE_ODDS_API_KEY",
        help="Environment variable containing the API key (default: THE_ODDS_API_KEY)",
    )
    parser.add_argument(
        "--lead-hours",
        type=parse_lead_hours,
        default=DEFAULT_LEAD_HOURS,
        help="Comma-separated pre-kickoff horizons in hours (default: 24,6,1)",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help="Bookmaker region to inspect (default: eu)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=REQUEST_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds (default: 20)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        parser.error(
            f"missing API key: set environment variable {args.api_key_env}; "
            "no network requests were sent"
        )

    fixtures, crosswalk_digest = load_probe_fixtures(args.crosswalk)
    client = TheOddsApiCoverageClient(api_key, timeout=args.timeout)
    report = probe_coverage(
        fixtures,
        args.lead_hours,
        client,
        region=args.region,
        crosswalk_sha256=crosswalk_digest,
    )
    write_report(report, args.output)
    summary = {
        "output": str(args.output),
        "fixtures": report["fixture_probe_count"],
        "requests": report["api_request_count"],
        "estimated_credits_upper_bound": report["estimated_credits_upper_bound"],
        "reported_credits_last_sum": report["reported_credits_last_sum"],
        "exact_matches": sum(
            row["match_status"] == "exact" for row in report["results"]
        ),
        "h2h_available": sum(
            row["h2h_market_available"] for row in report["results"]
        ),
        "prices_downloaded": False,
        "production_dataset_modified": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
