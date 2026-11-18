from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from kini_engine.ticket_ledger import TicketLedger, TicketLedgerError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a consistent, integrity-checked backup of the local "
            "Quiniela ticket ledger."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(
            os.environ.get("KINI_TICKET_LEDGER_PATH", "data/kini-tickets.sqlite3")
        ),
        help="SQLite ledger path (defaults to KINI_TICKET_LEDGER_PATH or data/kini-tickets.sqlite3).",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="New backup file path; existing files are never overwritten.",
    )
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(
            f"TICKET_LEDGER_BACKUP_ERROR: source database does not exist: {args.source}",
            file=sys.stderr,
        )
        return 2

    try:
        result = TicketLedger(args.source).backup_to(args.destination)
    except (OSError, sqlite3.Error, TicketLedgerError) as exc:
        print(f"TICKET_LEDGER_BACKUP_ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
