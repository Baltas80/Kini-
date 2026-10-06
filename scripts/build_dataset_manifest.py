from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kini_engine.validation import canonical_payload_hash

SCHEMA_VERSION = "1"
REQUIRED_MATCH_FIELDS = (
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
VALID_STATUSES = {
    "scheduled",
    "live",
    "finished",
    "postponed",
    "cancelled",
    "abandoned",
    "unknown",
}
SEASON_RE = re.compile(r"^\d{4}-\d{2}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def parse_utc_timestamp(value: str, field_name: str) -> datetime:
    if not value or not value.endswith("Z"):
        raise ValueError(f"{field_name} must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return parsed.astimezone(timezone.utc)


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_matches(path: Path) -> tuple[int, str, str, dict[str, datetime]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = tuple(reader.fieldnames or ())
    if fields != REQUIRED_MATCH_FIELDS:
        raise ValueError("matches.csv has an invalid header")

    ids = [row["match_id"] for row in rows]
    if any(not match_id for match_id in ids):
        raise ValueError("match_id must not be empty")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate match_id in matches.csv")

    kickoff_by_match: dict[str, datetime] = {}
    for row in rows:
        match_id = row["match_id"]
        if not row["competition_id"]:
            raise ValueError(f"competition_id must not be empty for {match_id}")
        if not SEASON_RE.fullmatch(row["season"]):
            raise ValueError(f"invalid season for {match_id}: {row['season']}")
        try:
            round_number = int(row["round_number"])
        except ValueError as exc:
            raise ValueError(f"invalid round_number for {match_id}") from exc
        if round_number <= 0:
            raise ValueError(f"round_number must be positive for {match_id}")
        if not row["home_team_id"] or not row["away_team_id"]:
            raise ValueError(f"team IDs must not be empty for {match_id}")
        if row["home_team_id"] == row["away_team_id"]:
            raise ValueError(f"home_team_id == away_team_id for {match_id}")

        kickoff = parse_utc_timestamp(row["kickoff_at"], f"kickoff_at for {match_id}")
        kickoff_by_match[match_id] = kickoff

        status = row["status"]
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status for {match_id}: {status}")

        hg, ag = row["home_goals"], row["away_goals"]
        result = row["result_1x2"]
        if (hg == "") != (ag == ""):
            raise ValueError(f"incomplete score for {match_id}")
        if hg == "":
            if result != "":
                raise ValueError(f"result_1x2 requires a complete score for {match_id}")
        else:
            try:
                home_goals, away_goals = int(hg), int(ag)
            except ValueError as exc:
                raise ValueError(f"invalid score for {match_id}") from exc
            if home_goals < 0 or away_goals < 0:
                raise ValueError(f"negative score for {match_id}")
            expected = (
                "1"
                if home_goals > away_goals
                else "2"
                if away_goals > home_goals
                else "X"
            )
            if result != expected:
                raise ValueError(f"inconsistent result_1x2 for {match_id}")
            if status == "finished" and result not in {"1", "X", "2"}:
                raise ValueError(f"finished match requires result_1x2 for {match_id}")

    seasons = sorted({row["season"] for row in rows})
    return (
        len(rows),
        seasons[0] if seasons else "",
        seasons[-1] if seasons else "",
        kickoff_by_match,
    )


def count_jsonl(path: Path, kickoff_by_match: dict[str, datetime]) -> int:
    count = 0
    seen: set[str] = set()

    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at observations.jsonl:{line_number}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"observation must be an object at line {line_number}")

            oid = obj.get("observation_id")
            if not isinstance(oid, str) or not oid or oid in seen:
                raise ValueError("invalid or duplicate observation_id")
            seen.add(oid)

            match_id = obj.get("match_id")
            if match_id not in kickoff_by_match:
                raise ValueError(f"observation references unknown match_id: {match_id}")

            source_id = obj.get("source_id")
            source_record_id = obj.get("source_record_id")
            if not isinstance(source_id, str) or not source_id:
                raise ValueError(f"invalid source_id for {oid}")
            if not isinstance(source_record_id, str) or not source_record_id:
                raise ValueError(f"invalid source_record_id for {oid}")

            captured_at = obj.get("captured_at")
            captured = parse_utc_timestamp(captured_at, f"captured_at for {oid}")

            payload = obj.get("payload")
            if not isinstance(payload, dict):
                raise ValueError(f"payload must be an object for {oid}")

            payload_hash = obj.get("payload_hash")
            if not isinstance(payload_hash, str) or not HEX64_RE.fullmatch(payload_hash):
                raise ValueError(f"payload_hash must be a lowercase SHA-256 hex digest for {oid}")
            if payload_hash != canonical_payload_hash(payload):
                raise ValueError(f"payload_hash does not match payload for {oid}")

            if payload.get("status") == "scheduled" and captured >= kickoff_by_match[match_id]:
                raise ValueError(f"scheduled observation is not pre-kickoff for {oid}")

            count += 1

    return count


def build_manifest(
    release: Path,
    dataset_id: str,
    source_revision: str,
    generated_at: str,
) -> dict[str, Any]:
    matches = release / "matches.csv"
    observations = release / "observations.jsonl"
    if not matches.exists() or not observations.exists():
        raise FileNotFoundError("release must contain matches.csv and observations.jsonl")

    generated = parse_utc_timestamp(generated_at, "generated_at")
    n_matches, season_from, season_to, kickoff_by_match = validate_matches(matches)
    n_observations = count_jsonl(observations, kickoff_by_match)

    files = {}
    for path in (matches, observations):
        files[str(path.relative_to(release))] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    return {
        "dataset_id": dataset_id,
        "schema_version": SCHEMA_VERSION,
        "dataset_kind": "historical",
        "immutable_release": True,
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "source_code_revision": source_revision,
        "record_counts": {
            "matches": n_matches,
            "observations": n_observations,
        },
        "season_range": {"from": season_from, "to": season_to},
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()

    release = Path(args.release)
    manifest = build_manifest(
        release,
        args.dataset_id,
        args.source_revision,
        args.generated_at,
    )
    (release / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
