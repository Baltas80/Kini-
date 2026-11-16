from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kini_engine.team_identity import (
    AmbiguousTeamIdentityError,
    TeamIdentityRegistry,
    normalize_team_name,
)

DEFAULT_REGISTRY = (
    Path(__file__).resolve().parent
    / "data"
    / "team_identity_registry.json"
)
DEFAULT_DRAWS = Path("data/selae_quiniela_draws.jsonl")
DEFAULT_CROSSWALK = Path("data/selae_fixture_crosswalk.json")
DEFAULT_HISTORICAL = Path("data/historical_spain.csv")
DEFAULT_REPORT = Path("data/selae_fixture_reconciliation.json")
SCORE_PATTERN = re.compile(r"^(\d+)\s*[-–]\s*(\d+)$")
SIGNS = frozenset({"1", "X", "2"})
CROSSWALK_FIELDS = frozenset(
    {
        "draw_date",
        "position",
        "football_data_date",
        "home_selae_display_name",
        "away_selae_display_name",
        "home_football_data_name",
        "away_football_data_name",
        "competition_id",
        "season",
        "gender",
        "kickoff_at",
        "source_fixture_id",
        "schedule_source",
        "evidence_url",
        "evidence_checked_at_utc",
    }
)


class FixtureReconciliationError(ValueError):
    """Raised when coupon or crosswalk input violates its declared contract."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FixtureReconciliationError(f"{field} must be a non-empty string")
    return value.strip()


def _is_safe_https_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _is_official_selae_url(value: object) -> bool:
    if not _is_safe_https_url(value):
        return False
    return urlparse(str(value)).hostname == "www.loteriasyapuestas.es"


def _parse_datetime(value: object, field: str) -> datetime:
    raw = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise FixtureReconciliationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FixtureReconciliationError(f"{field} must include a timezone offset")
    return parsed


def _parse_date(value: object, field: str) -> str:
    raw = _required_text(value, field)
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise FixtureReconciliationError(f"{field} must be an ISO date") from exc


def _fixture_display_name(team: object, field: str) -> str:
    if not isinstance(team, dict):
        raise FixtureReconciliationError(f"{field} must be an object")
    return _required_text(team.get("display_name"), f"{field}.display_name")


def _validate_draw(draw: object, location: str) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(draw, dict):
        raise FixtureReconciliationError(f"{location} must be an object")
    schema_version = draw.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in {1, 2}
    ):
        raise FixtureReconciliationError(f"{location} has an unsupported schema_version")
    if draw.get("provider") != "SELAE":
        raise FixtureReconciliationError(f"{location}.provider must be SELAE")
    if draw.get("record_type") != "completed_quiniela_draw":
        raise FixtureReconciliationError(f"{location}.record_type is invalid")

    draw_date = _parse_date(draw.get("draw_date"), f"{location}.draw_date")
    source_url = _required_text(draw.get("source_url"), f"{location}.source_url")
    if not _is_official_selae_url(source_url):
        raise FixtureReconciliationError(
            f"{location}.source_url must be an official SELAE HTTPS URL"
        )
    raw_sha256 = _required_text(draw.get("raw_sha256"), f"{location}.raw_sha256")
    if re.fullmatch(r"[0-9a-fA-F]{64}", raw_sha256) is None:
        raise FixtureReconciliationError(f"{location}.raw_sha256 must be a SHA-256 hex digest")

    fixtures = draw.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 14:
        raise FixtureReconciliationError(f"{location}.fixtures must contain exactly 14 entries")
    fixture_count = draw.get("fixture_count")
    if (
        isinstance(fixture_count, bool)
        or not isinstance(fixture_count, int)
        or fixture_count != 14
    ):
        raise FixtureReconciliationError(f"{location}.fixture_count must equal 14")

    normalized: list[dict[str, Any]] = []
    for expected_position, raw_fixture in enumerate(fixtures, start=1):
        fixture_location = f"{location}.fixtures[{expected_position}]"
        if not isinstance(raw_fixture, dict):
            raise FixtureReconciliationError(f"{fixture_location} must be an object")
        position = raw_fixture.get("position")
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or position != expected_position
        ):
            raise FixtureReconciliationError(
                f"{fixture_location}.position must equal {expected_position}"
            )
        home_name = _fixture_display_name(raw_fixture.get("home"), f"{fixture_location}.home")
        away_name = _fixture_display_name(raw_fixture.get("away"), f"{fixture_location}.away")
        if normalize_team_name(home_name) == normalize_team_name(away_name):
            raise FixtureReconciliationError(f"{fixture_location} has identical home and away names")

        sign = raw_fixture.get("sign")
        if not isinstance(sign, str) or sign not in SIGNS:
            raise FixtureReconciliationError(f"{fixture_location}.sign must be 1, X or 2")
        score_status = raw_fixture.get("score_status", "played")
        determination = raw_fixture.get("sign_determination", "score")

        item: dict[str, Any] = {
            "draw_date": draw_date,
            "position": expected_position,
            "home": raw_fixture["home"],
            "away": raw_fixture["away"],
            "home_display_name": home_name,
            "away_display_name": away_name,
            "sign": sign,
            "score_status": score_status,
            "sign_determination": determination,
            "source_url": source_url,
            "raw_sha256": raw_sha256.lower(),
        }

        if score_status == "played":
            home_goals = raw_fixture.get("home_goals")
            away_goals = raw_fixture.get("away_goals")
            if (
                isinstance(home_goals, bool)
                or isinstance(away_goals, bool)
                or not isinstance(home_goals, int)
                or not isinstance(away_goals, int)
                or home_goals < 0
                or away_goals < 0
                or determination != "score"
            ):
                raise FixtureReconciliationError(
                    f"{fixture_location} is marked played but has invalid football goals"
                )
            score_raw = raw_fixture.get("score_raw")
            match = SCORE_PATTERN.fullmatch(str(score_raw or "").strip())
            if match is None or (
                int(match.group(1)),
                int(match.group(2)),
            ) != (home_goals, away_goals):
                raise FixtureReconciliationError(
                    f"{fixture_location}.score_raw does not match the goal fields"
                )
            expected_sign = (
                "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"
            )
            if sign != expected_sign:
                raise FixtureReconciliationError(
                    f"{fixture_location}.sign conflicts with its played score"
                )
            item["home_goals"] = home_goals
            item["away_goals"] = away_goals
        elif score_status == "not_played":
            if (
                raw_fixture.get("home_goals") is not None
                or raw_fixture.get("away_goals") is not None
                or raw_fixture.get("score_raw") is not None
                or determination != "public_draw"
                or SCORE_PATTERN.fullmatch(
                    str(raw_fixture.get("reported_score_raw") or "").strip()
                ) is None
            ):
                raise FixtureReconciliationError(
                    f"{fixture_location} non-played fixture contains a football result "
                    "or lacks its reported coupon score"
                )
            if not _is_official_selae_url(raw_fixture.get("sign_evidence_url")):
                raise FixtureReconciliationError(
                    f"{fixture_location} non-played fixture lacks official SELAE evidence"
                )
            evidence_checked_at = _parse_datetime(
                raw_fixture.get("sign_evidence_checked_at_utc"),
                f"{fixture_location}.sign_evidence_checked_at_utc",
            )
            if evidence_checked_at.utcoffset() != timedelta(0):
                raise FixtureReconciliationError(
                    f"{fixture_location}.sign_evidence_checked_at_utc must be UTC"
                )
            _required_text(raw_fixture.get("status_reason"), f"{fixture_location}.status_reason")
            item["home_goals"] = None
            item["away_goals"] = None
        else:
            raise FixtureReconciliationError(
                f"{fixture_location}.score_status must be played or not_played"
            )
        normalized.append(item)

    return draw_date, normalized


def load_draw_records(path: str | Path) -> list[dict[str, Any]]:
    source_path = Path(path)
    try:
        lines = source_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FixtureReconciliationError(f"cannot read SELAE draws {source_path}: {exc}") from exc

    draws: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            draw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FixtureReconciliationError(
                f"invalid JSON in {source_path}, line {line_number}: {exc}"
            ) from exc
        draw_date, fixtures = _validate_draw(draw, f"line {line_number}")
        if draw_date in seen_dates:
            raise FixtureReconciliationError(f"duplicate SELAE draw date: {draw_date}")
        seen_dates.add(draw_date)
        draws.append(
            {
                "draw_date": draw_date,
                "source_url": draw["source_url"],
                "raw_sha256": str(draw["raw_sha256"]).lower(),
                "fixtures": fixtures,
            }
        )
    if not draws:
        raise FixtureReconciliationError("SELAE draw input is empty")
    return draws


def load_fixture_crosswalk(path: str | Path) -> dict[tuple[str, int], dict[str, Any]]:
    crosswalk_path = Path(path)
    try:
        document = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureReconciliationError(
            f"cannot read fixture crosswalk {crosswalk_path}: {exc}"
        ) from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise FixtureReconciliationError("crosswalk schema_version must equal 1")
    if document.get("provider") != "SELAE":
        raise FixtureReconciliationError("crosswalk provider must be SELAE")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise FixtureReconciliationError("crosswalk entries must be a list")

    result: dict[tuple[str, int], dict[str, Any]] = {}
    source_fixture_ids: set[str] = set()
    for index, raw in enumerate(entries):
        location = f"entries[{index}]"
        if not isinstance(raw, dict) or set(raw) != CROSSWALK_FIELDS:
            raise FixtureReconciliationError(
                f"{location} must contain exactly {sorted(CROSSWALK_FIELDS)}"
            )
        draw_date = _parse_date(raw.get("draw_date"), f"{location}.draw_date")
        football_data_date = _parse_date(
            raw.get("football_data_date"), f"{location}.football_data_date"
        )
        position = raw.get("position")
        if isinstance(position, bool) or not isinstance(position, int) or not 1 <= position <= 14:
            raise FixtureReconciliationError(f"{location}.position must be an integer from 1 to 14")

        entry = dict(raw)
        for field in (
            "home_selae_display_name",
            "away_selae_display_name",
            "home_football_data_name",
            "away_football_data_name",
            "competition_id",
            "season",
            "gender",
            "source_fixture_id",
            "schedule_source",
            "evidence_url",
            "evidence_checked_at_utc",
            "kickoff_at",
        ):
            entry[field] = _required_text(entry[field], f"{location}.{field}")

        entry["competition_id"] = entry["competition_id"].upper()
        entry["gender"] = entry["gender"].casefold()
        if entry["gender"] not in {"men", "women"}:
            raise FixtureReconciliationError(f"{location}.gender must be men or women")
        if entry["home_football_data_name"] == entry["away_football_data_name"]:
            raise FixtureReconciliationError(f"{location} has identical Football-Data team labels")

        kickoff = _parse_datetime(entry["kickoff_at"], f"{location}.kickoff_at")
        if abs((date.fromisoformat(football_data_date) - kickoff.date()).days) > 1:
            raise FixtureReconciliationError(
                f"{location}.football_data_date must be within one day of kickoff_at"
            )
        checked_at = _parse_datetime(
            entry["evidence_checked_at_utc"],
            f"{location}.evidence_checked_at_utc",
        )
        if checked_at.utcoffset() != timedelta(0):
            raise FixtureReconciliationError(
                f"{location}.evidence_checked_at_utc must be UTC"
            )
        if not _is_safe_https_url(entry["evidence_url"]):
            raise FixtureReconciliationError(f"{location}.evidence_url must be an HTTPS URL")

        source_fixture_id = entry["source_fixture_id"]
        if source_fixture_id in source_fixture_ids:
            raise FixtureReconciliationError(
                f"duplicate source_fixture_id in crosswalk: {source_fixture_id}"
            )
        source_fixture_ids.add(source_fixture_id)

        key = (draw_date, position)
        if key in result:
            raise FixtureReconciliationError(f"duplicate crosswalk fixture key: {key}")
        entry["draw_date"] = draw_date
        entry["position"] = position
        entry["football_data_date"] = football_data_date
        entry["kickoff_at"] = kickoff.isoformat()
        entry["evidence_checked_at_utc"] = checked_at.astimezone(UTC).isoformat()
        result[key] = entry
    return result


def load_historical_fixture_index(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    try:
        raw_bytes = source_path.read_bytes()
    except OSError as exc:
        raise FixtureReconciliationError(
            f"cannot read Football-Data history {source_path}: {exc}"
        ) from exc

    required_columns = {
        "Div",
        "Date",
        "HomeTeam",
        "AwayTeam",
        "FTHG",
        "FTAG",
        "FTR",
        "Season",
        "SourceURL",
    }
    rows_by_key: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    indexed_row_count = 0
    incomplete_row_count = 0
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
                missing = sorted(required_columns - set(reader.fieldnames or []))
                raise FixtureReconciliationError(
                    f"Football-Data CSV is missing required columns: {missing}"
                )
            for line_number, row in enumerate(reader, start=2):
                location = f"{source_path}:{line_number}"
                competition_id = _required_text(row.get("Div"), f"{location}.Div").upper()
                if competition_id not in {"SP1", "SP2"}:
                    raise FixtureReconciliationError(
                        f"{location}.Div must be SP1 or SP2, got {competition_id}"
                    )
                season = _required_text(row.get("Season"), f"{location}.Season")
                if re.fullmatch(r"\d{4}", season) is None:
                    raise FixtureReconciliationError(f"{location}.Season must be four digits")
                date_raw = _required_text(row.get("Date"), f"{location}.Date")
                try:
                    match_date = datetime.strptime(date_raw, "%d/%m/%Y").date().isoformat()
                except ValueError:
                    match_date = _parse_date(date_raw, f"{location}.Date")
                home_name = _required_text(row.get("HomeTeam"), f"{location}.HomeTeam")
                away_name = _required_text(row.get("AwayTeam"), f"{location}.AwayTeam")
                goal_values = [
                    str(row.get("FTHG") or "").strip(),
                    str(row.get("FTAG") or "").strip(),
                    str(row.get("FTR") or "").strip(),
                ]
                if not any(goal_values):
                    incomplete_row_count += 1
                    continue
                if not all(goal_values):
                    raise FixtureReconciliationError(
                        f"{location} has a partially populated football result"
                    )
                try:
                    home_goals = int(goal_values[0])
                    away_goals = int(goal_values[1])
                except ValueError as exc:
                    raise FixtureReconciliationError(
                        f"{location} has non-integer full-time goals"
                    ) from exc
                if home_goals < 0 or away_goals < 0:
                    raise FixtureReconciliationError(f"{location} has negative full-time goals")
                result = goal_values[2].upper()
                expected_result = (
                    "H" if home_goals > away_goals else "A" if home_goals < away_goals else "D"
                )
                if result != expected_result:
                    raise FixtureReconciliationError(
                        f"{location}.FTR conflicts with the full-time score"
                    )
                source_url = _required_text(row.get("SourceURL"), f"{location}.SourceURL")
                parsed_url = urlparse(source_url)
                if (
                    parsed_url.scheme != "https"
                    or parsed_url.hostname not in {
                        "football-data.co.uk",
                        "www.football-data.co.uk",
                    }
                ):
                    raise FixtureReconciliationError(
                        f"{location}.SourceURL must be an HTTPS Football-Data URL"
                    )

                item = {
                    "competition_id": competition_id,
                    "season": season,
                    "football_data_date": match_date,
                    "home_name": home_name,
                    "away_name": away_name,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "result": result,
                    "time_raw": str(row.get("Time") or "").strip() or None,
                    "source_url": source_url,
                }
                key = (
                    competition_id,
                    season,
                    match_date,
                    normalize_team_name(home_name),
                    normalize_team_name(away_name),
                )
                rows_by_key.setdefault(key, []).append(item)
                indexed_row_count += 1
    except UnicodeDecodeError as exc:
        raise FixtureReconciliationError(
            f"Football-Data CSV {source_path} is not valid UTF-8/UTF-8-SIG"
        ) from exc

    if indexed_row_count == 0:
        raise FixtureReconciliationError("Football-Data history contains no completed fixtures")
    return {
        "rows": rows_by_key,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "indexed_row_count": indexed_row_count,
        "incomplete_row_count": incomplete_row_count,
    }


def _marker_gender(team: dict[str, Any]) -> str | None:
    marker = str(team.get("category_marker") or "").strip().upper()
    if marker == "M":
        return "men"
    if marker == "F":
        return "women"
    return None


def reconcile_draws(
    draws: list[dict[str, Any]],
    crosswalk: dict[tuple[str, int], dict[str, Any]],
    registry: TeamIdentityRegistry,
    historical_index: dict[str, Any],
) -> dict[str, Any]:
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    used_keys: set[tuple[str, int]] = set()
    seen_source_fixture_ids: set[str] = set()
    seen_match_keys: set[tuple[str, str, str, str]] = set()
    fixture_count = 0
    played_count = 0

    for draw in draws:
        draw_date = draw["draw_date"]
        for fixture in draw["fixtures"]:
            fixture_count += 1
            key = (draw_date, int(fixture["position"]))
            base = {
                "draw_date": draw_date,
                "position": fixture["position"],
                "home": fixture["home_display_name"],
                "away": fixture["away_display_name"],
            }
            if fixture["score_status"] == "not_played":
                excluded.append({**base, "status": "excluded_not_played_public_draw"})
                continue

            played_count += 1
            entry = crosswalk.get(key)
            if entry is None:
                unresolved.append({**base, "reason": "missing_verified_crosswalk"})
                continue
            used_keys.add(key)

            if (
                normalize_team_name(entry["home_selae_display_name"])
                != normalize_team_name(fixture["home_display_name"])
                or normalize_team_name(entry["away_selae_display_name"])
                != normalize_team_name(fixture["away_display_name"])
            ):
                unresolved.append({**base, "reason": "coupon_team_name_mismatch"})
                continue

            marker_conflict = False
            for side in ("home", "away"):
                marker_gender = _marker_gender(fixture[side])
                if marker_gender is not None and marker_gender != entry["gender"]:
                    marker_conflict = True
            if marker_conflict:
                unresolved.append({**base, "reason": "category_marker_gender_mismatch"})
                continue

            try:
                home_identity = registry.resolve(
                    entry["home_football_data_name"],
                    source="football-data",
                    competition_id=entry["competition_id"],
                    season=entry["season"],
                    gender=entry["gender"],
                )
                away_identity = registry.resolve(
                    entry["away_football_data_name"],
                    source="football-data",
                    competition_id=entry["competition_id"],
                    season=entry["season"],
                    gender=entry["gender"],
                )
            except AmbiguousTeamIdentityError as exc:
                unresolved.append({**base, "reason": "ambiguous_registry_alias", "detail": str(exc)})
                continue

            if home_identity is None or away_identity is None:
                missing_sides = []
                if home_identity is None:
                    missing_sides.append("home")
                if away_identity is None:
                    missing_sides.append("away")
                unresolved.append(
                    {
                        **base,
                        "reason": "unresolved_football_data_identity",
                        "sides": missing_sides,
                        "competition_id": entry["competition_id"],
                        "season": entry["season"],
                        "gender": entry["gender"],
                    }
                )
                continue
            if home_identity.team_id == away_identity.team_id:
                unresolved.append({**base, "reason": "same_canonical_team_on_both_sides"})
                continue

            source_fixture_id = entry["source_fixture_id"]
            if source_fixture_id in seen_source_fixture_ids:
                unresolved.append({**base, "reason": "duplicate_source_fixture_id"})
                continue
            seen_source_fixture_ids.add(source_fixture_id)

            kickoff_utc = _parse_datetime(
                entry["kickoff_at"], "crosswalk.kickoff_at"
            ).astimezone(UTC).isoformat()
            match_key = (
                entry["competition_id"],
                kickoff_utc,
                home_identity.team_id,
                away_identity.team_id,
            )
            if match_key in seen_match_keys:
                unresolved.append({**base, "reason": "duplicate_canonical_fixture"})
                continue
            seen_match_keys.add(match_key)

            historical_key = (
                entry["competition_id"],
                entry["season"],
                entry["football_data_date"],
                normalize_team_name(entry["home_football_data_name"]),
                normalize_team_name(entry["away_football_data_name"]),
            )
            historical_matches = historical_index["rows"].get(historical_key, [])
            if not historical_matches:
                unresolved.append(
                    {**base, "reason": "no_exact_historical_fixture_match"}
                )
                continue
            if len(historical_matches) != 1:
                unresolved.append(
                    {**base, "reason": "ambiguous_historical_fixture_match"}
                )
                continue
            historical = historical_matches[0]
            if (
                historical["home_goals"] != fixture["home_goals"]
                or historical["away_goals"] != fixture["away_goals"]
            ):
                unresolved.append(
                    {
                        **base,
                        "reason": "historical_score_mismatch",
                        "selae_score": [
                            fixture["home_goals"],
                            fixture["away_goals"],
                        ],
                        "football_data_score": [
                            historical["home_goals"],
                            historical["away_goals"],
                        ],
                    }
                )
                continue

            resolved.append(
                {
                    "source_fixture_id": source_fixture_id,
                    "draw_date": draw_date,
                    "coupon_position": fixture["position"],
                    "kickoff_at": entry["kickoff_at"],
                    "football_data_date": entry["football_data_date"],
                    "competition_id": entry["competition_id"],
                    "season": entry["season"],
                    "gender": entry["gender"],
                    "home_team_id": home_identity.team_id,
                    "away_team_id": away_identity.team_id,
                    "home_canonical_name": home_identity.canonical_name,
                    "away_canonical_name": away_identity.canonical_name,
                    "home_selae_display_name": fixture["home_display_name"],
                    "away_selae_display_name": fixture["away_display_name"],
                    "home_football_data_name": entry["home_football_data_name"],
                    "away_football_data_name": entry["away_football_data_name"],
                    "home_goals": fixture["home_goals"],
                    "away_goals": fixture["away_goals"],
                    "target_1x2": fixture["sign"],
                    "target_source": "SELAE_official_escrutinio",
                    "draw_source_url": draw["source_url"],
                    "draw_raw_sha256": draw["raw_sha256"],
                    "schedule_source": entry["schedule_source"],
                    "schedule_evidence_url": entry["evidence_url"],
                    "schedule_evidence_checked_at_utc": entry["evidence_checked_at_utc"],
                    "historical_time_raw": historical["time_raw"],
                    "historical_source_url": historical["source_url"],
                    "historical_dataset_sha256": historical_index["sha256"],
                    "training_label_eligible": True,
                }
            )

    unused = [
        {
            "draw_date": key[0],
            "position": key[1],
            "source_fixture_id": entry["source_fixture_id"],
            "reason": "crosswalk_entry_not_used_by_a_played_coupon_fixture",
        }
        for key, entry in sorted(crosswalk.items())
        if key not in used_keys
    ]
    unresolved_count = len(unresolved) + len(unused)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "registry_id": registry.registry_id,
        "historical_dataset_sha256": historical_index["sha256"],
        "historical_indexed_row_count": historical_index["indexed_row_count"],
        "historical_incomplete_row_count": historical_index["incomplete_row_count"],
        "draw_count": len(draws),
        "coupon_fixture_count": fixture_count,
        "played_fixture_count": played_count,
        "eligible_fixture_count": len(resolved),
        "excluded_not_played_count": len(excluded),
        "unresolved_count": unresolved_count,
        "unused_crosswalk_entry_count": len(unused),
        "success": bool(fixture_count) and bool(resolved) and unresolved_count == 0,
        "resolved_fixtures": resolved,
        "unresolved_fixtures": unresolved,
        "excluded_fixtures": excluded,
        "unused_crosswalk_entries": unused,
    }


def reconcile_files(
    draws_path: str | Path,
    crosswalk_path: str | Path,
    historical_path: str | Path,
    registry: TeamIdentityRegistry,
) -> dict[str, Any]:
    draws = load_draw_records(draws_path)
    crosswalk = load_fixture_crosswalk(crosswalk_path)
    historical_index = load_historical_fixture_index(historical_path)
    return reconcile_draws(draws, crosswalk, registry, historical_index)
