from __future__ import annotations

import argparse
import json
import math
import unicodedata
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kini_engine.core import LAE_KICKOFF_EVIDENCE_MAX_AGE
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
    "dia",
    "orden",
    "jornada",
    "temporada",
    "caducidad",
)
_TIME_HINTS = (
    "fecha",
    "date",
    "hora",
    "time",
    "inicio",
    "kickoff",
    "dia",
    "caducidad",
)
_MAX_CANDIDATES = 80


def _timezone_aware_iso(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.strip())
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


def _candidate_fields(
    value: Any, path: str = "", depth: int = 0
) -> list[dict[str, Any]]:
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
    """Expose bounded schema evidence, not the full provider response."""
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
        "root_candidate_fields": _candidate_fields(payload),
        "details_key_present": "detallePartidos" in payload,
        "details_value_type": (
            type(raw_records).__name__ if "detallePartidos" in payload else None
        ),
        "details_record_count": (
            len(records) if isinstance(raw_records, list) else None
        ),
        "sample_records": samples,
    }


def summarize_probability_payload(payload: Any) -> dict[str, Any]:
    """Expose bounded LAE XML probability-field evidence without storing raw XML."""
    if not isinstance(payload, Mapping):
        return {
            "payload_type": type(payload).__name__,
            "root_keys": [],
            "percentage_keys": [],
            "record_count": 0,
            "record_fields": [],
            "probability_field_samples": {},
            "parsed_match_count": 0,
            "valid_probability_vector_count": 0,
            "invalid_probability_match_ids": [],
        }

    root = payload.get("quinielista")
    percentages = root.get("porcentajes") if isinstance(root, Mapping) else None
    raw_records = (
        percentages.get("partido") if isinstance(percentages, Mapping) else None
    )
    if isinstance(raw_records, Mapping):
        records = [raw_records]
    elif isinstance(raw_records, list):
        records = [record for record in raw_records if isinstance(record, Mapping)]
    else:
        records = []

    field_names = sorted({str(key) for record in records[:10] for key in record})
    probability_fields = [
        key
        for key in field_names
        if any(
            token in key.casefold()
            for token in ("porc", "prob", "pronost", "sign", "1x2")
        )
        or key.casefold() in {"1", "x", "2"}
    ]
    field_samples = {
        key: [_safe_sample(record.get(key)) for record in records[:3] if key in record]
        for key in probability_fields[:30]
    }

    parsed = KinielaGPTSource._probability_map(dict(payload))
    valid_ids = [
        match_id
        for match_id, row in parsed.items()
        if isinstance(row.get("probabilities"), Mapping)
    ]
    invalid_ids = [
        match_id for match_id, row in parsed.items() if row.get("probabilities") is None
    ]

    return {
        "payload_type": "object",
        "root_keys": sorted(str(key) for key in payload)[:40],
        "percentage_keys": (
            sorted(str(key) for key in percentages)[:40]
            if isinstance(percentages, Mapping)
            else []
        ),
        "record_count": len(records),
        "record_fields": field_names[:80],
        "probability_field_samples": field_samples,
        "expected_parser_fields_present": {
            field: field in field_names
            for field in ("num", "local", "visitante", "porc_1", "porc_X", "porc_2")
        },
        "parsed_match_count": len(parsed),
        "valid_probability_vector_count": len(valid_ids),
        "invalid_probability_match_ids": invalid_ids[:30],
    }


def _normalize_team_name(value: Any) -> str | None:
    """Normalize case, accents and punctuation without applying team aliases."""
    if not isinstance(value, str):
        return None
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    normalized = " ".join(
        "".join(
            character if character.isalnum() else " " for character in without_marks
        ).split()
    )
    return normalized or None


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        return None
    return number if number > 0 else None


def reconcile_fixture_order(details: Any, percentage_matches: Any) -> dict[str, Any]:
    """Verify detail.orden -> percentage.num using an exact normalized team pair.

    Accent/case/punctuation normalization is allowed, but no aliases, fuzzy
    matching, reversed home/away pairs or positional fallback are used.
    """
    detail_records = details if isinstance(details, list) else []
    percentage_records = (
        percentage_matches if isinstance(percentage_matches, list) else []
    )
    percentage_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    percentage_ids: list[int] = []
    invalid_percentage_records = 0

    for record in percentage_records:
        if not isinstance(record, Mapping):
            invalid_percentage_records += 1
            continue
        match_id = _positive_integer(record.get("id"))
        home = _normalize_team_name(record.get("home"))
        away = _normalize_team_name(record.get("away"))
        if match_id is None or home is None or away is None:
            invalid_percentage_records += 1
            continue
        percentage_ids.append(match_id)
        percentage_by_pair.setdefault((home, away), []).append(
            {
                "id": match_id,
                "home": str(record.get("home", ""))[:100],
                "away": str(record.get("away", ""))[:100],
            }
        )

    mappings: list[dict[str, Any]] = []
    detail_orders: list[int] = []
    invalid_detail_records = 0
    matched_ids: list[int] = []

    for record in detail_records:
        if not isinstance(record, Mapping):
            invalid_detail_records += 1
            continue
        order = _positive_integer(record.get("orden"))
        home = _normalize_team_name(record.get("local"))
        away = _normalize_team_name(record.get("visitante"))
        if order is None or home is None or away is None:
            invalid_detail_records += 1
            continue

        detail_orders.append(order)
        candidates = percentage_by_pair.get((home, away), [])
        matched_num = candidates[0]["id"] if len(candidates) == 1 else None
        if matched_num is not None:
            matched_ids.append(matched_num)
        mappings.append(
            {
                "orden": order,
                "matched_num": matched_num,
                "name_match_count": len(candidates),
                "order_matches_num": matched_num == order
                if matched_num is not None
                else False,
                "local": str(record.get("local", ""))[:100],
                "visitante": str(record.get("visitante", ""))[:100],
                "provider_day_label": str(record.get("dia") or "")[:20] or None,
                "provider_clock_time": str(record.get("hora") or "")[:20] or None,
                "timezone_aware_candidate_fields": [
                    field["path"]
                    for field in _candidate_fields(record)
                    if field.get("timezone_aware_iso") is True
                ],
            }
        )

    duplicate_orders = sorted(
        value for value, count in Counter(detail_orders).items() if count > 1
    )
    duplicate_percentage_ids = sorted(
        value for value, count in Counter(percentage_ids).items() if count > 1
    )
    reasons: list[str] = []
    if not detail_records or not percentage_records:
        reasons.append("empty_source")
    if invalid_detail_records:
        reasons.append("invalid_detail_records")
    if invalid_percentage_records:
        reasons.append("invalid_percentage_records")
    if len(detail_records) != len(percentage_records):
        reasons.append("fixture_count_mismatch")
    if duplicate_orders:
        reasons.append("duplicate_detail_orders")
    if duplicate_percentage_ids:
        reasons.append("duplicate_percentage_ids")
    if any(item["name_match_count"] != 1 for item in mappings):
        reasons.append("home_away_name_pair_not_unique_or_unmatched")
    if any(not item["order_matches_num"] for item in mappings):
        reasons.append("order_does_not_match_percentage_num")
    if len(set(matched_ids)) != len(matched_ids):
        reasons.append("multiple_details_match_same_percentage_row")
    if set(matched_ids) != set(percentage_ids):
        reasons.append("percentage_rows_not_fully_covered")

    verified = (
        bool(detail_records)
        and bool(percentage_records)
        and invalid_detail_records == 0
        and invalid_percentage_records == 0
        and len(detail_records) == len(percentage_records)
        and not duplicate_orders
        and not duplicate_percentage_ids
        and len(mappings) == len(detail_records)
        and all(item["name_match_count"] == 1 for item in mappings)
        and all(item["order_matches_num"] for item in mappings)
        and len(set(matched_ids)) == len(matched_ids)
        and set(matched_ids) == set(percentage_ids)
    )

    return {
        "status": "verified" if verified else "not_verified",
        "method": "exact_normalized_home_away_name_pair_plus_order_num",
        "aliases_or_fuzzy_matching_used": False,
        "details_count": len(detail_records),
        "percentage_matches_count": len(percentage_records),
        "verified_count": sum(item["order_matches_num"] for item in mappings),
        "order_equals_percentage_num_for_all": verified,
        "duplicate_detail_orders": duplicate_orders,
        "duplicate_percentage_ids": duplicate_percentage_ids,
        "invalid_detail_records": invalid_detail_records,
        "invalid_percentage_records": invalid_percentage_records,
        "unmatched_percentage_ids": sorted(set(percentage_ids) - set(matched_ids)),
        "reasons": sorted(set(reasons)),
        "mapping": mappings[:30],
    }


def _parse_aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _valid_three_way_vector(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    probabilities = []
    for sign in ("1", "X", "2"):
        probability = value.get(sign)
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(float(probability))
            or not 0.0 <= float(probability) <= 1.0
        ):
            return False
        probabilities.append(float(probability))
    return math.isclose(sum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-6)


def summarize_kickoff_attachment(rows: Any, lae_source: str) -> dict[str, Any]:
    """Summarize only fixture identity, timestamp ordering and LAE vector validity."""
    records = rows if isinstance(rows, list) else []
    fixtures = []
    for row in records:
        if not isinstance(row, Mapping):
            continue
        captured_at = _parse_aware_datetime(row.get("lae_captured_at"))
        kickoff_at = _parse_aware_datetime(row.get("kickoff_at"))
        evidence_checked_at = _parse_aware_datetime(
            row.get("kickoff_evidence_checked_at_utc")
        )
        vector_valid = _valid_three_way_vector(row.get("lae"))
        evidence_before_capture = (
            evidence_checked_at is not None
            and captured_at is not None
            and evidence_checked_at <= captured_at
        )
        evidence_age = (
            captured_at - evidence_checked_at
            if evidence_checked_at is not None and captured_at is not None
            else None
        )
        evidence_fresh_at_capture = (
            evidence_age is not None
            and 0 <= evidence_age.total_seconds()
            <= LAE_KICKOFF_EVIDENCE_MAX_AGE.total_seconds()
        )
        capture_before_kickoff = (
            captured_at is not None
            and kickoff_at is not None
            and captured_at < kickoff_at
        )
        eligible = (
            row.get("fixture_identity_status") == "verified"
            and row.get("lae_source") == lae_source
            and vector_valid
            and evidence_before_capture
            and evidence_fresh_at_capture
            and capture_before_kickoff
        )
        fixtures.append(
            {
                "id": row.get("id"),
                "fixture_identity_status": row.get("fixture_identity_status"),
                "kickoff_at": row.get("kickoff_at"),
                "lae_vector_valid": vector_valid,
                "evidence_before_capture": evidence_before_capture,
                "evidence_fresh_at_capture": evidence_fresh_at_capture,
                "capture_before_kickoff": capture_before_kickoff,
                "temporally_eligible_lae": eligible,
            }
        )

    return {
        "rows_count": len(records),
        "kickoff_mapped_count": sum(
            _parse_aware_datetime(row.get("kickoff_at")) is not None
            for row in records
            if isinstance(row, Mapping)
        ),
        "lae_source_rows_count": sum(
            row.get("lae_source") == lae_source
            for row in records
            if isinstance(row, Mapping)
        ),
        "valid_lae_vector_count": sum(
            _valid_three_way_vector(row.get("lae"))
            for row in records
            if isinstance(row, Mapping)
        ),
        "temporally_eligible_lae_count": sum(
            fixture["temporally_eligible_lae"] for fixture in fixtures
        ),
        "fixtures": fixtures[:30],
    }


def collect_live_diagnostic() -> dict[str, Any]:
    report: dict[str, Any] = {
        "diagnostic": "kinielagpt_detalle_partido_schema",
        "requested_at": datetime.now(UTC).isoformat(),
        "method": "GET",
        "mutating_operations": False,
    }
    source = KinielaGPTSource(timeout=20)
    jornada, temporada, percentage_matches = source.last()
    report["jornada"] = jornada
    report["temporada"] = temporada
    payload, captured_at = source.details_payload(jornada, temporada)
    report["details_response_received_at"] = captured_at
    report["schema"] = summarize_payload(payload)
    details = payload.get("detallePartidos")
    report["fixture_crosswalk"] = reconcile_fixture_order(details, percentage_matches)
    lae_payload, lae_schema_received_at = source._xml_snapshot(
        source.LAE.format(jornada, temporada)
    )
    report["lae_probability_schema"] = {
        "schema_probe_received_at": lae_schema_received_at,
        **summarize_probability_payload(lae_payload),
    }
    probability_rows = source.probabilities(jornada, temporada)
    report["kickoff_attachment"] = summarize_kickoff_attachment(
        probability_rows, source.LAE_SOURCE
    )
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
    except Exception as exc:  # noqa: BLE001 - preserve failure evidence in this diagnostic
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
