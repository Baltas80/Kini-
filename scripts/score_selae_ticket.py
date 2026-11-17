from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from kini_engine.ticket_outcomes import TicketOutcomeError, score_ticket_record


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: invalid UTF-8 JSON input") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{path}: JSON root must be an object")
    return value, raw


def _write_json_once(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing output: {path}")
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score persisted 14-match Quiniela ticket columns against a fully "
            "reconciled SELAE coupon, including official public-draw signs."
        )
    )
    parser.add_argument("--ticket", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument(
        "--pleno15",
        type=Path,
        help="Optional separately verified official SELAE Pleno al 15 result JSON.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        ticket, ticket_bytes = _load_json(args.ticket)
        reconciliation, reconciliation_bytes = _load_json(args.reconciliation)
        pleno15 = None
        pleno15_digest = None
        if args.pleno15 is not None:
            pleno15, pleno15_bytes = _load_json(args.pleno15)
            pleno15_digest = hashlib.sha256(pleno15_bytes).hexdigest()
        result = score_ticket_record(
            ticket,
            reconciliation,
            ticket_sha256=hashlib.sha256(ticket_bytes).hexdigest(),
            reconciliation_sha256=hashlib.sha256(reconciliation_bytes).hexdigest(),
            pleno15_report=pleno15,
            pleno15_report_sha256=pleno15_digest,
        )
        _write_json_once(args.output, result)
    except (OSError, TicketOutcomeError, TypeError, ValueError) as exc:
        print(f"SELAE_TICKET_SCORE_ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"SELAE_TICKET_SCORE_OK: ticket={result['ticket_id']} "
        f"columns={result['column_count']} "
        f"public_draw_positions={result['public_draw_positions']} "
        f"covered_14={result['covered_14']} "
        f"pleno15_evaluated={result.get('pleno15_evaluated', False)} "
        f"pleno15_hit={result.get('pleno15_hit')} "
        f"covered_full_coupon={result.get('covered_full_coupon')} "
        f"best_column_hits={result['best_column_hits']}"
    )
    print(f"Result: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
