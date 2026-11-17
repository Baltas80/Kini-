from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from kini_engine.fixture_reconciliation import (
    DEFAULT_CROSSWALK,
    DEFAULT_DRAWS,
    DEFAULT_HISTORICAL,
    DEFAULT_REGISTRY,
    DEFAULT_REPORT,
    FixtureReconciliationError,
    reconcile_files,
)
from kini_engine.team_identity import TeamIdentityRegistry


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
        Path(temporary).replace(path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile official SELAE coupon fixtures with independently evidenced "
            "Football-Data identities and kickoff metadata."
        )
    )
    parser.add_argument("--draws", type=Path, default=DEFAULT_DRAWS)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--historical", type=Path, default=DEFAULT_HISTORICAL)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--labels-output",
        type=Path,
        help="Optional JSONL export; written only when every played fixture is reconciled.",
    )
    args = parser.parse_args(argv)

    try:
        registry = TeamIdentityRegistry.from_path(args.registry)
        report = reconcile_files(
            args.draws,
            args.crosswalk,
            args.historical,
            registry,
        )
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        _atomic_write(args.output, serialized)

        if args.labels_output is not None:
            if not report["success"]:
                raise FixtureReconciliationError(
                    "refusing to export training labels while any played fixture is unresolved "
                    "or any crosswalk entry is unused"
                )
            labels = report["resolved_fixtures"]
            jsonl = "".join(
                json.dumps(label, ensure_ascii=False, sort_keys=True) + "\n"
                for label in labels
            )
            _atomic_write(args.labels_output, jsonl)

        print(
            "SELAE_RECONCILIATION "
            f"success={report['success']} "
            f"eligible={report['eligible_fixture_count']} "
            f"excluded_not_played={report['excluded_not_played_count']} "
            f"unresolved={report['unresolved_count']}"
        )
        print(f"Report: {args.output}")
        if args.labels_output is not None:
            print(f"Training-label candidates: {args.labels_output}")
        return 0 if report["success"] else 1
    except (FixtureReconciliationError, ValueError) as exc:
        print(f"SELAE_RECONCILIATION_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
