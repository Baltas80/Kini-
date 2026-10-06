from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

from scripts.build_dataset_manifest import canonical_payload_hash

VALID_STATUSES = {
    "scheduled",
    "live",
    "finished",
    "postponed",
    "cancelled",
    "abandoned",
    "unknown",
}
SIGNS = {"1", "X", "2"}
SEASON_RE = re.compile(r"^(?P<start>\d{4})-(?P<end>\d{2})$")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    record_id: str | None = None
    line: int | None = None


@dataclass
class ValidationReport:
    valid: bool
    as_of: str
    checks: dict[str, str]
    counts: dict[str, int]
    issues: list[ValidationIssue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "as_of": self.as_of,
            "checks": self.checks,
            "counts": self.counts,
            "issues": [asdict(issue) for issue in self.issues],
        }


def parse_utc_timestamp(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field_name} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return parsed.astimezone(timezone.utc)


def _expected_result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "1"
    if away_goals > home_goals:
        return "2"
    return "X"


def _issue(
    issues: list[ValidationIssue],
    code: str,
    message: str,
    *,
    record_id: str | None = None,
    line: int | None = None,
) -> None:
    issues.append(ValidationIssue(code, "error", message, record_id, line))


def _round_expectation_key(competition_id: str, season: str, round_number: int) -> str:
    return f"{competition_id}|{season}|{round_number}"


def load_expected_rounds(path: Path) -> dict[tuple[str, str, int], int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("expected rounds configuration must be a JSON object")

    nested = raw.get("competitions", raw)
    if not isinstance(nested, dict):
        raise ValueError("expected rounds configuration has invalid competitions")

    result: dict[tuple[str, str, int], int] = {}
    for competition_id, seasons in nested.items():
        if not isinstance(seasons, dict):
            raise ValueError(f"invalid seasons for competition {competition_id}")
        for season, rounds in seasons.items():
            if not isinstance(rounds, dict):
                raise ValueError(f"invalid rounds for {competition_id}/{season}")
            for round_number, expected in rounds.items():
                try:
                    round_int = int(round_number)
                    expected_int = int(expected)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid round expectation for {competition_id}/{season}/{round_number}") from exc
                if round_int <= 0 or expected_int <= 0:
                    raise ValueError(f"round and expected match count must be positive for {competition_id}/{season}/{round_number}")
                result[(str(competition_id), str(season), round_int)] = expected_int
    return result


def load_known_teams(path: Path) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise ValueError("known teams configuration must be a JSON list of non-empty team IDs")
    teams = {item.strip() for item in raw}
    if not teams:
        raise ValueError("known teams configuration must not be empty")
    return teams


def _validate_match_rows(
    rows: list[dict[str, str]],
    issues: list[ValidationIssue],
    *,
    as_of: datetime,
    known_team_ids: set[str] | None,
    expected_rounds: dict[tuple[str, str, int], int] | None,
) -> dict[str, datetime]:
    required = (
        "match_id",
        "competition_id",
        "season",
        "round_number",
        "home_team_id",
        "away_team_id",
        "kickoff_at",
        "status",
        "home_goals",
        "away_goals",
        "result_1x2",
    )
    if not rows:
        _issue(issues, "empty_dataset", "matches.csv contains no records")
        return {}

    kickoff_by_match: dict[str, datetime] = {}
    match_ids: set[str] = set()
    fixture_keys: set[tuple[str, str, int, str, str, str]] = set()
    team_rounds: dict[tuple[str, str, int], set[str]] = defaultdict(set)
    round_times: dict[tuple[str, str, int], list[datetime]] = defaultdict(list)

    for line, row in enumerate(rows, 2):
        match_id = row.get("match_id", "")
        if not match_id:
            _issue(issues, "missing_match_id", "match_id is empty", line=line)
            continue

        if match_id in match_ids:
            _issue(issues, "duplicate_match_id", f"duplicate match_id: {match_id}", record_id=match_id, line=line)
        match_ids.add(match_id)

        values = [row.get(field, "") for field in required]
        if any(value == "" for value in values[:7]):
            _issue(issues, "missing_required_field", f"required match field is empty: {match_id}", record_id=match_id, line=line)
            continue

        competition_id = row["competition_id"]
        season = row["season"]
        try:
            round_number = int(row["round_number"])
            if round_number <= 0:
                raise ValueError
        except ValueError:
            _issue(issues, "invalid_round", f"invalid round_number for {match_id}: {row['round_number']}", record_id=match_id, line=line)
            continue

        season_match = SEASON_RE.fullmatch(season)
        if not season_match:
            _issue(issues, "invalid_season", f"invalid season for {match_id}: {season}", record_id=match_id, line=line)
        else:
            start_year = int(season_match.group("start"))
            end_year = start_year + 1
            try:
                kickoff_year = datetime.fromisoformat(row["kickoff_at"].replace("Z", "+00:00")).year
            except ValueError:
                kickoff_year = None
            if kickoff_year not in {start_year, end_year}:
                _issue(issues, "date_incoherent", f"kickoff year {kickoff_year} is outside season {season} for {match_id}", record_id=match_id, line=line)

        try:
            kickoff = parse_utc_timestamp(row["kickoff_at"], f"kickoff_at for {match_id}")
            kickoff_by_match[match_id] = kickoff
            if kickoff > as_of:
                _issue(issues, "future_match", f"kickoff is after validation as_of for {match_id}", record_id=match_id, line=line)
        except ValueError as exc:
            _issue(issues, "invalid_timestamp", str(exc), record_id=match_id, line=line)
            kickoff = None

        home = row["home_team_id"]
        away = row["away_team_id"]
        if home == away:
            _issue(issues, "impossible_match", f"home and away team are identical for {match_id}", record_id=match_id, line=line)
        if known_team_ids is not None:
            for team_id, side in ((home, "home"), (away, "away")):
                if team_id not in known_team_ids:
                    _issue(issues, "unknown_team", f"unknown {side}_team_id {team_id} for {match_id}", record_id=match_id, line=line)

        if kickoff is not None:
            fixture_key = (competition_id, season, round_number, home, away, row["kickoff_at"])
            if fixture_key in fixture_keys:
                _issue(issues, "duplicate_fixture", f"duplicate fixture tuple for {match_id}", record_id=match_id, line=line)
            fixture_keys.add(fixture_key)
            round_key = (competition_id, season, round_number)
            team_rounds[round_key].update((home, away))
            round_times[round_key].append(kickoff)

        status = row["status"]
        if status not in VALID_STATUSES:
            _issue(issues, "invalid_status", f"invalid status for {match_id}: {status}", record_id=match_id, line=line)

        hg, ag, result = row["home_goals"], row["away_goals"], row["result_1x2"]
        has_home = hg != ""
        has_away = ag != ""
        if has_home != has_away:
            _issue(issues, "invalid_score", f"score must contain both home_goals and away_goals for {match_id}", record_id=match_id, line=line)
        elif has_home:
            try:
                home_goals, away_goals = int(hg), int(ag)
                if home_goals < 0 or away_goals < 0:
                    raise ValueError
            except ValueError:
                _issue(issues, "impossible_score", f"negative or non-integer score for {match_id}", record_id=match_id, line=line)
            else:
                expected = _expected_result(home_goals, away_goals)
                if result not in SIGNS:
                    _issue(issues, "invalid_result", f"invalid result_1x2 for {match_id}: {result}", record_id=match_id, line=line)
                elif result != expected:
                    _issue(issues, "result_mismatch", f"result_1x2 does not match score for {match_id}", record_id=match_id, line=line)
        elif result:
            _issue(issues, "invalid_result", f"result_1x2 exists without a complete score for {match_id}", record_id=match_id, line=line)

        if status == "finished" and (not has_home or not has_away or result not in SIGNS):
            _issue(issues, "finished_without_result", f"finished match lacks a valid final score/result: {match_id}", record_id=match_id, line=line)
        if status in {"scheduled", "postponed", "cancelled"} and (has_home or has_away or result):
            _issue(issues, "status_score_conflict", f"{status} match has final score/result data: {match_id}", record_id=match_id, line=line)

    by_comp_season: dict[tuple[str, str], list[tuple[int, datetime]]] = defaultdict(list)
    for (competition_id, season, round_number), times in round_times.items():
        if times:
            by_comp_season[(competition_id, season)].append((round_number, min(times)))
        if expected_rounds is not None:
            expected = expected_rounds.get((competition_id, season, round_number))
            if expected is None:
                _issue(
                    issues,
                    "missing_round_expectation",
                    f"no expected fixture count for {competition_id}/{season}/round {round_number}",
                )
            else:
                actual = len(times)
                if actual != expected:
                    _issue(
                        issues,
                        "incomplete_round",
                        f"{competition_id}/{season}/round {round_number} has {actual} fixtures; expected {expected}",
                    )
        if len(team_rounds[(competition_id, season, round_number)]) != len(times) * 2:
            _issue(
                issues,
                "impossible_round",
                f"a team appears in multiple fixtures in {competition_id}/{season}/round {round_number}",
            )

    if expected_rounds is not None:
        observed_keys = set(round_times)
        for key, expected in expected_rounds.items():
            if key not in observed_keys:
                _issue(
                    issues,
                    "missing_round",
                    f"missing entire jornada {key[0]}/{key[1]}/round {key[2]}; expected {expected} fixtures",
                )

    for comp_season, round_starts in by_comp_season.items():
        round_starts.sort()
        for previous, current in zip(round_starts, round_starts[1:]):
            if current[1] < previous[1]:
                _issue(
                    issues,
                    "round_date_order",
                    f"round {current[0]} starts before round {previous[0]} in {comp_season[0]}/{comp_season[1]}",
                )

    return kickoff_by_match


def _validate_observations(
    path: Path,
    kickoff_by_match: dict[str, datetime],
    issues: list[ValidationIssue],
    *,
    as_of: datetime,
) -> None:
    seen_ids: set[str] = set()
    last_captured: dict[str, datetime] = {}

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                _issue(issues, "invalid_observation_json", f"invalid JSON at line {line_number}: {exc}", line=line_number)
                continue
            if not isinstance(obj, dict):
                _issue(issues, "invalid_observation", "observation must be a JSON object", line=line_number)
                continue

            observation_id = obj.get("observation_id")
            if not isinstance(observation_id, str) or not observation_id:
                _issue(issues, "invalid_observation_id", "observation_id is missing", line=line_number)
                continue
            if observation_id in seen_ids:
                _issue(issues, "duplicate_observation_id", f"duplicate observation_id: {observation_id}", record_id=observation_id, line=line_number)
            seen_ids.add(observation_id)

            match_id = obj.get("match_id")
            if match_id not in kickoff_by_match:
                _issue(issues, "unknown_observation_match", f"observation references unknown match_id: {match_id}", record_id=observation_id, line=line_number)

            captured_value = obj.get("captured_at")
            try:
                captured_at = parse_utc_timestamp(captured_value, f"captured_at for {observation_id}")
                if captured_at > as_of:
                    _issue(issues, "future_observation", f"observation is after validation as_of: {observation_id}", record_id=observation_id, line=line_number)
                previous = last_captured.get(str(match_id))
                if previous is not None and captured_at < previous:
                    _issue(issues, "observation_date_order", f"observations are not append-ordered for match {match_id}", record_id=observation_id, line=line_number)
                last_captured[str(match_id)] = captured_at
                kickoff = kickoff_by_match.get(str(match_id))
                if kickoff is not None and obj.get("payload", {}).get("status") == "scheduled" and captured_at >= kickoff:
                    _issue(issues, "late_scheduled_observation", f"scheduled observation captured at/after kickoff: {observation_id}", record_id=observation_id, line=line_number)
            except ValueError as exc:
                _issue(issues, "invalid_observation_timestamp", str(exc), record_id=observation_id, line=line_number)

            for field in ("source_id", "source_record_id"):
                if not isinstance(obj.get(field), str) or not obj[field]:
                    _issue(issues, "invalid_observation_field", f"{field} is missing for {observation_id}", record_id=observation_id, line=line_number)

            payload = obj.get("payload")
            if not isinstance(payload, dict):
                _issue(issues, "invalid_observation_payload", f"payload is not an object for {observation_id}", record_id=observation_id, line=line_number)
            else:
                expected_hash = canonical_payload_hash(payload)
                if obj.get("payload_hash") != expected_hash:
                    _issue(issues, "payload_hash_mismatch", f"payload_hash does not match payload for {observation_id}", record_id=observation_id, line=line_number)


def validate_dataset(
    matches_path: Path,
    observations_path: Path | None,
    *,
    as_of: datetime,
    known_team_ids: Iterable[str] | None,
    expected_rounds: dict[tuple[str, str, int], int] | None,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    checks = {
        "duplicates": "pass",
        "impossible_matches": "pass",
        "invalid_results": "pass",
        "date_coherence": "pass",
        "round_completeness": "pass",
        "unknown_teams": "pass" if known_team_ids is not None else "not_run",
        "future_data": "pass",
    }

    try:
        parse_utc_timestamp(as_of.isoformat().replace("+00:00", "Z"), "as_of")
    except ValueError as exc:
        _issue(issues, "invalid_as_of", str(exc))
        return ValidationReport(False, as_of.isoformat(), checks, {}, issues)

    known = None if known_team_ids is None else {team_id for team_id in known_team_ids}
    with matches_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != (
            "match_id",
            "competition_id",
            "season",
            "round_number",
            "home_team_id",
            "away_team_id",
            "kickoff_at",
            "status",
            "home_goals",
            "away_goals",
            "result_1x2",
        ):
            _issue(issues, "invalid_matches_header", "matches.csv has an invalid canonical header")
            kickoff_by_match = {}
        else:
            kickoff_by_match = _validate_match_rows(
                list(reader),
                issues,
                as_of=as_of,
                known_team_ids=known,
                expected_rounds=expected_rounds,
            )

    if observations_path is not None:
        _validate_observations(observations_path, kickoff_by_match, issues, as_of=as_of)

    error_codes = {issue.code for issue in issues}
    duplicate_codes = {"duplicate_match_id", "duplicate_fixture", "duplicate_observation_id"}
    impossible_codes = {"impossible_match", "impossible_score", "impossible_round", "status_score_conflict"}
    result_codes = {"invalid_result", "result_mismatch", "finished_without_result", "invalid_score"}
    date_codes = {"invalid_timestamp", "invalid_season", "round_date_order", "observation_date_order", "invalid_observation_timestamp", "late_scheduled_observation"}
    round_codes = {"incomplete_round", "missing_round", "missing_round_expectation"}

    if error_codes & duplicate_codes:
        checks["duplicates"] = "fail"
    if error_codes & impossible_codes:
        checks["impossible_matches"] = "fail"
    if error_codes & result_codes:
        checks["invalid_results"] = "fail"
    if error_codes & date_codes:
        checks["date_coherence"] = "fail"
    if error_codes & round_codes:
        checks["round_completeness"] = "fail"
    if "unknown_team" in error_codes:
        checks["unknown_teams"] = "fail"
    if error_codes & {"future_match", "future_observation"}:
        checks["future_data"] = "fail"

    counts = {
        "matches": sum(1 for _ in matches_path.open("r", encoding="utf-8")) - 1,
        "observations": (
            sum(1 for line in observations_path.open("r", encoding="utf-8") if line.strip())
            if observations_path is not None
            else 0
        ),
        "errors": len(issues),
    }
    return ValidationReport(not issues, as_of.isoformat().replace("+00:00", "Z"), checks, counts, issues)
