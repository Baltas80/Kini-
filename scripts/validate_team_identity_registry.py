from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

from kini_engine.team_identity import (
    AmbiguousTeamIdentityError,
    TeamIdentityRegistry,
)

DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[1]
    / "kini_engine"
    / "data"
    / "team_identity_registry.json"
)
DEFAULT_CSV = Path("data/historical_spain.csv")


def validate_csv_references(
    csv_path: str | Path,
    registry: TeamIdentityRegistry,
) -> dict[str, Any]:
    """Check every Football-Data home/away label against its exact scope."""
    path = Path(csv_path)
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"cannot open historical CSV {path}: {exc}") from exc

    unresolved: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    resolved_ids: set[str] = set()
    fixture_count = 0
    team_reference_count = 0
    required = {"Div", "Season", "HomeTeam", "AwayTeam"}

    with handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"historical CSV missing required columns: {sorted(missing)}"
            )

        for line_number, row in enumerate(reader, start=2):
            fixture_count += 1
            competition_id = (row.get("Div") or "").strip().upper()
            season = (row.get("Season") or "").strip()
            if not competition_id or not season:
                raise ValueError(
                    f"CSV line {line_number}: Div and Season are required for identity resolution"
                )

            for side in ("HomeTeam", "AwayTeam"):
                team_name = (row.get(side) or "").strip()
                team_reference_count += 1
                if not team_name:
                    unresolved.append({
                        "line": line_number,
                        "side": side,
                        "name": team_name,
                        "competition_id": competition_id,
                        "season": season,
                        "reason": "empty_name",
                    })
                    continue
                try:
                    identity = registry.resolve(
                        team_name,
                        source="football-data",
                        competition_id=competition_id,
                        season=season,
                        gender="men",
                    )
                except AmbiguousTeamIdentityError as exc:
                    ambiguous.append({
                        "line": line_number,
                        "side": side,
                        "name": team_name,
                        "competition_id": competition_id,
                        "season": season,
                        "reason": str(exc),
                    })
                    continue
                if identity is None:
                    unresolved.append({
                        "line": line_number,
                        "side": side,
                        "name": team_name,
                        "competition_id": competition_id,
                        "season": season,
                        "reason": "no_exact_scoped_alias",
                    })
                    continue
                resolved_ids.add(identity.team_id)

    return {
        "registry_id": registry.registry_id,
        "registry_team_count": registry.team_count,
        "source": "football-data",
        "fixture_count": fixture_count,
        "team_reference_count": team_reference_count,
        "resolved_references": team_reference_count - len(unresolved) - len(ambiguous),
        "resolved_unique_team_ids": len(resolved_ids),
        "unresolved_count": len(unresolved),
        "ambiguous_count": len(ambiguous),
        "unresolved_examples": unresolved[:50],
        "ambiguous_examples": ambiguous[:50],
        "success": bool(fixture_count) and not unresolved and not ambiguous,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate exact Football-Data team identities against the canonical registry."
        )
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    registry = TeamIdentityRegistry.from_path(args.registry)
    report = validate_csv_references(args.csv, registry)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
