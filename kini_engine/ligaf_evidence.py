from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kini_engine.team_identity import (
    AmbiguousTeamIdentityError,
    TeamIdentityRegistry,
)

DEFAULT_LIGAF_REGISTRY = (
    Path(__file__).resolve().parent / "data" / "ligaf_team_identity_registry.json"
)
DEFAULT_LIGAF_EVIDENCE = Path("data/ligaf_fixture_evidence.json")
OFFICIAL_HOSTS = frozenset({"ligaf.es", "www.ligaf.es"})
SIGNS = frozenset({"1", "X", "2"})
MATCH_ID_PATTERN = re.compile(r"^[0-9]+$")


class LigaFEvidenceError(ValueError):
    """Raised when official Liga F fixture evidence violates its contract."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LigaFEvidenceError(f"{field} must be a non-empty string")
    return value.strip()


def _parse_datetime(value: object, field: str) -> datetime:
    raw = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LigaFEvidenceError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LigaFEvidenceError(f"{field} must include a timezone offset")
    return parsed


def _official_url(value: object, field: str) -> str:
    raw = _required_text(value, field)
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
        raise LigaFEvidenceError(f"{field} must be an HTTPS URL on the official Liga F domain")
    return raw


def _resolve_team(
    registry: TeamIdentityRegistry,
    name: str,
    *,
    source: str,
    season: str,
    expected_team_id: str,
    field: str,
) -> None:
    try:
        identity = registry.resolve(
            name,
            source=source,
            competition_id="LIGA_F",
            season=season,
            gender="women",
        )
    except AmbiguousTeamIdentityError as exc:
        raise LigaFEvidenceError(f"{field} is ambiguous in the Liga F identity registry") from exc
    if identity is None or identity.team_id != expected_team_id:
        raise LigaFEvidenceError(f"{field} does not resolve to {expected_team_id!r}")


def load_ligaf_fixture_evidence(
    path: str | Path = DEFAULT_LIGAF_EVIDENCE,
    *,
    registry: TeamIdentityRegistry | None = None,
) -> list[dict[str, Any]]:
    """Load official Liga F fixture evidence without promoting it to training data.

    The source-specific manifest is intentionally separate from the
    Football-Data crosswalk. Returned records always carry
    training_label_eligible=False until a validated multi-season Liga F
    historical dataset and temporal training contract exist.
    """
    evidence_path = Path(path)
    try:
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LigaFEvidenceError(f"cannot read Liga F evidence {evidence_path}: {exc}") from exc

    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise LigaFEvidenceError("Liga F evidence schema_version must equal 1")
    if document.get("provider") != "LIGA_F":
        raise LigaFEvidenceError("Liga F evidence provider must equal LIGA_F")
    if document.get("competition_id") != "LIGA_F":
        raise LigaFEvidenceError("Liga F evidence competition_id must equal LIGA_F")
    if document.get("gender") != "women":
        raise LigaFEvidenceError("Liga F evidence gender must equal women")

    season = _required_text(document.get("season"), "season")
    try:
        draw_date = date.fromisoformat(_required_text(document.get("draw_date"), "draw_date"))
    except ValueError as exc:
        raise LigaFEvidenceError("draw_date must be an ISO date") from exc

    eligibility = document.get("training_eligibility")
    if (
        not isinstance(eligibility, dict)
        or eligibility.get("eligible") is not False
        or not isinstance(eligibility.get("reason"), str)
        or not eligibility["reason"].strip()
    ):
        raise LigaFEvidenceError(
            "Liga F evidence must remain excluded from training until a historical dataset is validated"
        )

    team_registry = registry or TeamIdentityRegistry.from_path(DEFAULT_LIGAF_REGISTRY)
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        raise LigaFEvidenceError("Liga F evidence entries must be a non-empty list")

    required_fields = {
        "coupon_position",
        "selae_home_display_name",
        "selae_away_display_name",
        "home_team_name",
        "away_team_name",
        "home_team_id",
        "away_team_id",
        "matchday",
        "match_id",
        "kickoff_at",
        "home_goals",
        "away_goals",
        "coupon_sign",
        "match_url",
        "home_team_profile_url",
        "away_team_profile_url",
        "evidence_checked_at_utc",
    }
    seen_positions: set[int] = set()
    seen_match_ids: set[str] = set()
    seen_fixtures: set[tuple[datetime, str, str]] = set()
    validated: list[dict[str, Any]] = []

    for index, raw in enumerate(entries):
        location = f"entries[{index}]"
        if not isinstance(raw, dict) or set(raw) != required_fields:
            raise LigaFEvidenceError(
                f"{location} must contain exactly {sorted(required_fields)}"
            )

        position = raw["coupon_position"]
        if isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= 14:
            raise LigaFEvidenceError(f"{location}.coupon_position must be an integer from 1 to 14")
        if position in seen_positions:
            raise LigaFEvidenceError(f"duplicate Liga F coupon position: {position}")
        seen_positions.add(position)

        matchday = raw["matchday"]
        if isinstance(matchday, bool) or not isinstance(matchday, int) or matchday < 1:
            raise LigaFEvidenceError(f"{location}.matchday must be a positive integer")

        match_id = _required_text(raw["match_id"], f"{location}.match_id")
        if MATCH_ID_PATTERN.fullmatch(match_id) is None:
            raise LigaFEvidenceError(f"{location}.match_id must contain only digits")
        if match_id in seen_match_ids:
            raise LigaFEvidenceError(f"duplicate Liga F match_id: {match_id}")
        seen_match_ids.add(match_id)

        kickoff = _parse_datetime(raw["kickoff_at"], f"{location}.kickoff_at")
        if kickoff.date() > draw_date:
            raise LigaFEvidenceError(f"{location}.kickoff_at occurs after the SELAE draw date")

        checked_at = _parse_datetime(
            raw["evidence_checked_at_utc"],
            f"{location}.evidence_checked_at_utc",
        )
        if checked_at.utcoffset() != timedelta(0):
            raise LigaFEvidenceError(f"{location}.evidence_checked_at_utc must be UTC")

        match_url = _official_url(raw["match_url"], f"{location}.match_url")
        if f"/{match_id}/" not in urlparse(match_url).path:
            raise LigaFEvidenceError(f"{location}.match_url does not contain its match_id")
        home_profile_url = _official_url(
            raw["home_team_profile_url"],
            f"{location}.home_team_profile_url",
        )
        away_profile_url = _official_url(
            raw["away_team_profile_url"],
            f"{location}.away_team_profile_url",
        )

        home_team_name = _required_text(raw["home_team_name"], f"{location}.home_team_name")
        away_team_name = _required_text(raw["away_team_name"], f"{location}.away_team_name")
        home_team_id = _required_text(raw["home_team_id"], f"{location}.home_team_id")
        away_team_id = _required_text(raw["away_team_id"], f"{location}.away_team_id")
        if home_team_id == away_team_id:
            raise LigaFEvidenceError(f"{location} has identical home and away team IDs")

        _resolve_team(
            team_registry,
            home_team_name,
            source="ligaf",
            season=season,
            expected_team_id=home_team_id,
            field=f"{location}.home_team_name",
        )
        _resolve_team(
            team_registry,
            away_team_name,
            source="ligaf",
            season=season,
            expected_team_id=away_team_id,
            field=f"{location}.away_team_name",
        )
        _resolve_team(
            team_registry,
            _required_text(raw["selae_home_display_name"], f"{location}.selae_home_display_name"),
            source="selae",
            season=season,
            expected_team_id=home_team_id,
            field=f"{location}.selae_home_display_name",
        )
        _resolve_team(
            team_registry,
            _required_text(raw["selae_away_display_name"], f"{location}.selae_away_display_name"),
            source="selae",
            season=season,
            expected_team_id=away_team_id,
            field=f"{location}.selae_away_display_name",
        )

        home_goals = raw["home_goals"]
        away_goals = raw["away_goals"]
        if (
            isinstance(home_goals, bool)
            or isinstance(away_goals, bool)
            or not isinstance(home_goals, int)
            or not isinstance(away_goals, int)
            or home_goals < 0
            or away_goals < 0
        ):
            raise LigaFEvidenceError(f"{location} has invalid full-time goals")
        coupon_sign = raw["coupon_sign"]
        if not isinstance(coupon_sign, str) or coupon_sign not in SIGNS:
            raise LigaFEvidenceError(f"{location}.coupon_sign must be 1, X or 2")
        expected_sign = (
            "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"
        )
        if coupon_sign != expected_sign:
            raise LigaFEvidenceError(f"{location}.coupon_sign conflicts with the official score")

        fixture_key = (
            kickoff.astimezone(UTC),
            home_team_id,
            away_team_id,
        )
        if fixture_key in seen_fixtures:
            raise LigaFEvidenceError(f"{location} duplicates a canonical Liga F fixture")
        seen_fixtures.add(fixture_key)

        validated.append(
            {
                **raw,
                "draw_date": draw_date.isoformat(),
                "season": season,
                "competition_id": "LIGA_F",
                "gender": "women",
                "kickoff_at": kickoff.isoformat(),
                "evidence_checked_at_utc": checked_at.astimezone(UTC).isoformat(),
                "match_url": match_url,
                "home_team_profile_url": home_profile_url,
                "away_team_profile_url": away_profile_url,
                "training_label_eligible": False,
                "training_exclusion_reason": eligibility["reason"].strip(),
            }
        )

    return sorted(validated, key=lambda item: item["coupon_position"])
