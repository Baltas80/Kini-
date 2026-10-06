from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

from kini_engine.validation import load_expected_rounds, load_known_teams, validate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a canonical Kini historical dataset.")
    parser.add_argument("matches", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--known-teams", type=Path, required=True)
    parser.add_argument("--expected-rounds", type=Path, required=True)
    parser.add_argument("--as-of", required=True, help="UTC ISO-8601 timestamp ending in Z")
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args()

    try:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        parser.error(f"invalid --as-of: {exc}")
    if as_of.tzinfo is None or as_of.utcoffset() != timezone.utc.utcoffset(as_of):
        parser.error("--as-of must be timezone-aware UTC")

    try:
        known_teams = load_known_teams(args.known_teams)
        expected_rounds = load_expected_rounds(args.expected_rounds)
        report = validate_dataset(
            args.matches,
            args.observations,
            as_of=as_of.astimezone(timezone.utc),
            known_team_ids=known_teams,
            expected_rounds=expected_rounds,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"VALIDATION CONFIG/IO ERROR: {exc}", file=sys.stderr)
        return 2

    output = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    if args.report_out:
        args.report_out.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
