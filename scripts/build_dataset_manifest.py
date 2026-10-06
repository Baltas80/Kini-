from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"
REQUIRED_MATCH_FIELDS = (
    "match_id", "competition_id", "season", "round_number",
    "home_team_id", "away_team_id", "kickoff_at", "status",
    "home_goals", "away_goals", "result_1x2",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_matches(path: Path) -> tuple[int, str, str]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fields = tuple(reader.fieldnames or ())
    if fields != REQUIRED_MATCH_FIELDS:
        raise ValueError("matches.csv has an invalid header")
    ids = [row["match_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate match_id in matches.csv")
    for row in rows:
        if row["home_team_id"] == row["away_team_id"]:
            raise ValueError(f"home_team_id == away_team_id for {row['match_id']}")
        hg, ag = row["home_goals"], row["away_goals"]
        result = row["result_1x2"]
        if (hg == "") != (ag == ""):
            raise ValueError(f"incomplete score for {row['match_id']}")
        if hg != "":
            if int(hg) < 0 or int(ag) < 0:
                raise ValueError(f"negative score for {row['match_id']}")
            expected = "1" if int(hg) > int(ag) else "2" if int(ag) > int(hg) else "X"
            if result != expected:
                raise ValueError(f"inconsistent result_1x2 for {row['match_id']}")
    seasons = sorted({row["season"] for row in rows})
    return len(rows), seasons[0] if seasons else "", seasons[-1] if seasons else ""


def count_jsonl(path: Path) -> int:
    count = 0
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            oid = obj.get("observation_id")
            if not oid or oid in seen:
                raise ValueError("invalid or duplicate observation_id")
            seen.add(oid)
            count += 1
    return count


def build_manifest(release: Path, dataset_id: str, source_revision: str, generated_at: str) -> dict[str, Any]:
    matches = release / "matches.csv"
    observations = release / "observations.jsonl"
    if not matches.exists() or not observations.exists():
        raise FileNotFoundError("release must contain matches.csv and observations.jsonl")
    n_matches, season_from, season_to = validate_matches(matches)
    n_observations = count_jsonl(observations)
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
        "generated_at": generated_at,
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
    manifest = build_manifest(release, args.dataset_id, args.source_revision, args.generated_at)
    (release / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
