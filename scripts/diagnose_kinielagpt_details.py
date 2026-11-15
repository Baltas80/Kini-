from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kini_engine.sources import KinielaGPTSource

_KEY_HINTS = (
    "id",
    "fecha",
    "date",
    "hora",
    "time",
    "inicio",
    "kickoff",
    "utc",
    "timezone",
    "zona",
    "partido",
    "local",
    "visitante",
    "equipo",
    "num",
)
_TIME_HINTS = ("fecha", "date", "hora", "time", "inicio", "kickoff")
_MAX_CANDIDATES = 80


def _timezone_aware_iso(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _safe_sample(value: Any) -> Any:
    if isinstance(value, str):
        return value[:180]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {"type": "object", "keys": sorted(str(key) for key in value)[:30]}
    if isinstance(value, list):
        first = type(value[0]).__name__ if value else None
        return {"type": "array", "length": len(value), "first_item_type": first}
    return {"type": type(value).__name__}


def _candidate_fields(value: Any, path: str = "", depth: int = 0) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if depth > 4 or len(found) >= _MAX_CANDIDATES:
        return found

    if isinstance(value, Mapping):
        for key, child in list(value.items())[:80]:
            name = str(key)
            field_path = f"{path}.{name}" if path else name
            normalized = name.casefold()
            if any(hint in normalized for hint in _KEY_HINTS):
                item = {"path": field_path, "sample": _safe_sample(child)}
                if isinstance(child, str) and any(
                    hint in normalized for hint in _TIME_HINTS
                ):
                    item["timezone_aware_iso"] = _timezone_aware_iso(child)
                found.append(item)
            if isinstance(child, (Mapping, list)) and depth < 4:
                found.extend(_candidate_fields(child, field_path, depth + 1))
            if len(found) >= _MAX_CANDIDATES:
                break
    elif isinstance(value, list):
        for index, child in enumerate(value[:3]):
            found.extend(_candidate_fields(child, f"{path}[{index}]", depth + 1))
            if len(found) >= _MAX_CANDIDATES:
                break
    return found[:_MAX_CANDIDATES]


def summarize_payload(payload: Any) -> dict[str, Any]:
    """Expose only bounded schema evidence, not the full provider response."""
    if not isinstance(payload, Mapping):
        return {
            "payload_type": type(payload).__name__,
            "root_keys": [],
            "details_key_present": False,
            "details_value_type": None,
            "details_record_count": None,
            "sample_records": [],
        }

    raw_records = payload.get("detallePartidos")
    records = raw_records if isinstance(raw_records, list) else []
    samples = []
    for index, record in enumerate(records[:5]):
        if isinstance(record, Mapping):
            keys = sorted(str(key) for key in record)[:80]
            candidates = _candidate_fields(record)
            record_type = "object"
        else:
            keys = []
            candidates = []
            record_type = type(record).__name__
        samples.append(
            {
                "index": index,
                "record_type": record_type,
                "keys": keys,
                "candidate_fields": candidates,
            }
        )

    return {
        "payload_type": "object",
        "root_keys": sorted(str(key) for key in payload)[:80],
        "details_key_present": "detallePartidos" in payload,
        "details_value_type": (
            type(raw_records).__name__ if "detallePartidos" in payload else None
        ),
        "details_record_count": len(records) if isinstance(raw_records, list) else None,
        "sample_records": samples,
    }


def collect_live_diagnostic() -> dict[str, Any]:
    report: dict[str, Any] = {
        "diagnostic": "kinielagpt_detalle_partido_schema",
        "requested_at": datetime.now(UTC).isoformat(),
        "method": "GET",
        "mutating_operations": False,
    }
    source = KinielaGPTSource(timeout=20)
    jornada, temporada, _ = source.last()
    report["jornada"] = jornada
    report["temporada"] = temporada
    payload, captured_at = source.details_payload(jornada, temporada)
    report["details_response_received_at"] = captured_at
    report["schema"] = summarize_payload(payload)
    report["status"] = (
        "ok"
        if report["schema"]["details_key_present"]
        and report["schema"]["details_value_type"] == "list"
        and report["schema"]["details_record_count"] > 0
        else "empty_or_unrecognized_schema"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the live KinielaGPT details schema without storing raw responses."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("kinielagpt-details-diagnostic.json"),
    )
    args = parser.parse_args()

    try:
        report = collect_live_diagnostic()
        exit_code = 0 if report["status"] == "ok" else 2
    except Exception as exc:  # diagnostic must preserve failure evidence
        report = {
            "diagnostic": "kinielagpt_detalle_partido_schema",
            "requested_at": datetime.now(UTC).isoformat(),
            "method": "GET",
            "mutating_operations": False,
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
        }
        exit_code = 1

    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
