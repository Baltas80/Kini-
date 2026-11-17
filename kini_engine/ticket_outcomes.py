from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

SIGNS = ("1", "X", "2")
POSITIONS = tuple(range(1, 15))
SELAE_HOSTS = {"loteriasyapuestas.es", "www.loteriasyapuestas.es"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TicketOutcomeError(ValueError):
    """Raised when ticket or official coupon outcome evidence is incomplete."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TicketOutcomeError(f"{field} must be a non-empty string")
    return value.strip()


def _parse_timestamp(value: object, field: str) -> datetime:
    raw = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TicketOutcomeError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TicketOutcomeError(f"{field} must include a timezone offset")
    return parsed


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    parsed = _parse_timestamp(value, field)
    if parsed.utcoffset() != timedelta(0):
        raise TicketOutcomeError(f"{field} must be expressed in UTC")
    return parsed.astimezone(UTC)


def _parse_draw_date(value: object, field: str) -> str:
    raw = _required_text(value, field)
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise TicketOutcomeError(f"{field} must be an ISO date") from exc


def _validate_sha256(value: object, field: str) -> str:
    raw = _required_text(value, field).lower()
    if _SHA256_RE.fullmatch(raw) is None:
        raise TicketOutcomeError(f"{field} must be a SHA-256 hex digest")
    return raw


def _validate_https_url(value: object, field: str) -> str:
    raw = _required_text(value, field)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise TicketOutcomeError(f"{field} must be a valid HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise TicketOutcomeError(f"{field} must be a safe HTTPS URL")
    return raw


def _validate_official_selae_url(value: object, field: str) -> str:
    raw = _validate_https_url(value, field)
    if urlsplit(raw).hostname not in SELAE_HOSTS:
        raise TicketOutcomeError(f"{field} must use an official SELAE host")
    return raw


def _validate_probability_vector(value: object, field: str) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(SIGNS):
        raise TicketOutcomeError(f"{field} must contain exactly 1, X and 2")
    vector: dict[str, float] = {}
    for sign in SIGNS:
        probability = value[sign]
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not isfinite(float(probability))
            or not 0.0 <= float(probability) <= 1.0
        ):
            raise TicketOutcomeError(f"{field}.{sign} must be finite and in [0, 1]")
        vector[sign] = float(probability)
    if abs(sum(vector.values()) - 1.0) > 1e-6:
        raise TicketOutcomeError(f"{field} must sum to one")
    return vector


def _result_from_score(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "1"
    if home_goals < away_goals:
        return "2"
    return "X"


def _position(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in POSITIONS:
        raise TicketOutcomeError(f"{field} must be an integer from 1 to 14")
    return value


def outcomes_from_reconciliation(
    report: dict[str, Any],
    draw_date: str,
) -> list[dict[str, Any]]:
    """Build a complete 14-sign outcome vector from the SELAE reconciliation report.

    Played fixtures use their reconciled score-derived sign. Public-draw fixtures
    use the official coupon sign, never the reported placeholder score.
    """
    expected_date = _parse_draw_date(draw_date, "draw_date")
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise TicketOutcomeError("unsupported SELAE fixture reconciliation schema")

    collection_names = (
        "resolved_fixtures",
        "excluded_fixtures",
        "unresolved_fixtures",
        "unused_crosswalk_entries",
    )
    collections: dict[str, list[dict[str, Any]]] = {}
    for name in collection_names:
        value = report.get(name)
        if not isinstance(value, list) or any(
            not isinstance(item, dict) for item in value
        ):
            raise TicketOutcomeError(f"reconciliation {name} must be a list of objects")
        collections[name] = [
            item for item in value if item.get("draw_date") == expected_date
        ]

    if collections["unresolved_fixtures"]:
        raise TicketOutcomeError(
            f"{expected_date}: unresolved fixtures prevent complete ticket scoring"
        )
    if collections["unused_crosswalk_entries"]:
        raise TicketOutcomeError(
            f"{expected_date}: unused crosswalk entries prevent complete ticket scoring"
        )

    outcomes: dict[int, dict[str, Any]] = {}
    for item in collections["resolved_fixtures"]:
        position = _position(item.get("coupon_position"), "resolved coupon_position")
        if position in outcomes:
            raise TicketOutcomeError(
                f"{expected_date}: duplicate outcome at position {position}"
            )
        if item.get("training_label_eligible") is not True:
            raise TicketOutcomeError(
                f"{expected_date} position {position}: played fixture must be training-eligible"
            )
        home_goals = item.get("home_goals")
        away_goals = item.get("away_goals")
        if (
            isinstance(home_goals, bool)
            or isinstance(away_goals, bool)
            or not isinstance(home_goals, int)
            or not isinstance(away_goals, int)
            or home_goals < 0
            or away_goals < 0
        ):
            raise TicketOutcomeError(
                f"{expected_date} position {position}: invalid reconciled football score"
            )
        sign = item.get("target_1x2")
        if sign not in SIGNS or sign != _result_from_score(home_goals, away_goals):
            raise TicketOutcomeError(
                f"{expected_date} position {position}: target sign conflicts with score"
            )
        source_url = _validate_official_selae_url(
            item.get("draw_source_url"), f"position {position}.draw_source_url"
        )
        source_sha256 = _validate_sha256(
            item.get("draw_raw_sha256"), f"position {position}.draw_raw_sha256"
        )
        outcomes[position] = {
            "position": position,
            "sign": sign,
            "outcome_type": "played",
            "training_label_eligible": True,
            "ticket_outcome_eligible": True,
            "home": item.get("home_selae_display_name"),
            "away": item.get("away_selae_display_name"),
            "home_goals": home_goals,
            "away_goals": away_goals,
            "source_url": source_url,
            "source_sha256": source_sha256,
        }

    for item in collections["excluded_fixtures"]:
        position = _position(item.get("position"), "excluded position")
        if position in outcomes:
            raise TicketOutcomeError(
                f"{expected_date}: duplicate outcome at position {position}"
            )
        if (
            item.get("score_status") != "not_played"
            or item.get("sign_determination") != "public_draw"
            or item.get("training_label_eligible") is not False
            or item.get("ticket_outcome_eligible") is not True
            or item.get("home_goals") is not None
            or item.get("away_goals") is not None
        ):
            raise TicketOutcomeError(
                f"{expected_date} position {position}: invalid public-draw eligibility contract"
            )
        sign = item.get("sign")
        if not isinstance(sign, str) or sign not in SIGNS:
            raise TicketOutcomeError(
                f"{expected_date} position {position}: public-draw sign must be 1, X or 2"
            )
        source_url = _validate_official_selae_url(
            item.get("source_url"), f"position {position}.source_url"
        )
        source_sha256 = _validate_sha256(
            item.get("raw_sha256"), f"position {position}.raw_sha256"
        )
        evidence_url = _validate_official_selae_url(
            item.get("sign_evidence_url"), f"position {position}.sign_evidence_url"
        )
        evidence_checked_at = _parse_utc_timestamp(
            item.get("sign_evidence_checked_at_utc"),
            f"position {position}.sign_evidence_checked_at_utc",
        )
        status_reason = _required_text(
            item.get("status_reason"), f"position {position}.status_reason"
        )
        reported_score_raw = _required_text(
            item.get("reported_score_raw"), f"position {position}.reported_score_raw"
        )
        outcomes[position] = {
            "position": position,
            "sign": sign,
            "outcome_type": "public_draw",
            "training_label_eligible": False,
            "ticket_outcome_eligible": True,
            "home": item.get("home"),
            "away": item.get("away"),
            "home_goals": None,
            "away_goals": None,
            "reported_score_raw": reported_score_raw,
            "status_reason": status_reason,
            "source_url": source_url,
            "source_sha256": source_sha256,
            "sign_evidence_url": evidence_url,
            "sign_evidence_checked_at_utc": evidence_checked_at.isoformat().replace(
                "+00:00", "Z"
            ),
        }

    if set(outcomes) != set(POSITIONS):
        missing = sorted(set(POSITIONS) - set(outcomes))
        extra = sorted(set(outcomes) - set(POSITIONS))
        raise TicketOutcomeError(
            f"{expected_date}: reconciliation must cover positions 1..14; "
            f"missing={missing}, extra={extra}"
        )
    return [outcomes[position] for position in POSITIONS]


def validate_preclose_public_draw_snapshot(
    snapshot: dict[str, Any],
    *,
    draw_date: str,
    position: int,
    ticket_cutoff_at_utc: str,
) -> dict[str, Any]:
    """Validate a timestamped participant-forecast snapshot captured before ticket close."""
    expected_date = _parse_draw_date(draw_date, "draw_date")
    expected_position = _position(position, "position")
    cutoff = _parse_utc_timestamp(ticket_cutoff_at_utc, "ticket_cutoff_at_utc")
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise TicketOutcomeError("unsupported pre-close forecast snapshot schema")
    if snapshot.get("provider") != "SELAE":
        raise TicketOutcomeError("pre-close forecast provider must be SELAE")
    if (
        _parse_draw_date(snapshot.get("draw_date"), "snapshot.draw_date")
        != expected_date
    ):
        raise TicketOutcomeError("pre-close forecast draw date mismatch")
    if _position(snapshot.get("position"), "snapshot.position") != expected_position:
        raise TicketOutcomeError("pre-close forecast coupon position mismatch")
    if "ball_counts" in snapshot:
        raise TicketOutcomeError(
            "post-close ball counts are draw metadata, not a pre-close forecast snapshot"
        )

    source_id = _required_text(snapshot.get("source_id"), "snapshot.source_id")
    source_url = _validate_official_selae_url(
        snapshot.get("source_url"), "snapshot.source_url"
    )
    source_sha256 = _validate_sha256(
        snapshot.get("source_sha256"), "snapshot.source_sha256"
    )
    captured_at = _parse_utc_timestamp(
        snapshot.get("captured_at_utc"), "snapshot.captured_at_utc"
    )
    declared_cutoff = _parse_utc_timestamp(
        snapshot.get("ticket_cutoff_at_utc"), "snapshot.ticket_cutoff_at_utc"
    )
    if declared_cutoff != cutoff:
        raise TicketOutcomeError("pre-close snapshot ticket cutoff mismatch")
    if captured_at >= cutoff:
        raise TicketOutcomeError(
            "participant-forecast snapshot must be captured strictly before ticket close"
        )
    probabilities = _validate_probability_vector(
        snapshot.get("probabilities"), "snapshot.probabilities"
    )
    return {
        "probabilities": probabilities,
        "source": "preclose_participant_forecast",
        "source_id": source_id,
        "captured_at_utc": captured_at.isoformat().replace("+00:00", "Z"),
        "source_url": source_url,
        "source_sha256": source_sha256,
    }


def build_ticket_probability_vectors(
    *,
    draw_date: str,
    reconciliation_report: dict[str, Any],
    model_probabilities_by_position: Mapping[int, dict[str, float]],
    public_draw_snapshots: Mapping[int, dict[str, Any]],
    ticket_cutoff_at_utc: str,
) -> dict[str, Any]:
    """Prepare the 14 vectors for TicketOptimizer without inventing public-draw priors.

    Football model probabilities are accepted only for played fixtures. A public-draw
    position requires its own official, timestamped pre-close participant snapshot.
    """
    outcomes = outcomes_from_reconciliation(reconciliation_report, draw_date)
    public_positions = {
        item["position"] for item in outcomes if item["outcome_type"] == "public_draw"
    }
    played_positions = set(POSITIONS) - public_positions
    if set(model_probabilities_by_position) != played_positions:
        raise TicketOutcomeError(
            "football model probabilities must cover played positions only; "
            f"expected={sorted(played_positions)}, "
            f"received={sorted(model_probabilities_by_position)}"
        )
    if set(public_draw_snapshots) != public_positions:
        raise TicketOutcomeError(
            "pre-close participant snapshots must cover every public-draw position only; "
            f"expected={sorted(public_positions)}, "
            f"received={sorted(public_draw_snapshots)}"
        )

    probabilities = []
    sources = []
    for position in POSITIONS:
        if position in public_positions:
            validated = validate_preclose_public_draw_snapshot(
                public_draw_snapshots[position],
                draw_date=draw_date,
                position=position,
                ticket_cutoff_at_utc=ticket_cutoff_at_utc,
            )
            probabilities.append(validated["probabilities"])
            sources.append(
                {
                    "position": position,
                    "source": validated["source"],
                    "source_id": validated["source_id"],
                    "captured_at_utc": validated["captured_at_utc"],
                    "source_url": validated["source_url"],
                    "source_sha256": validated["source_sha256"],
                }
            )
        else:
            vector = _validate_probability_vector(
                model_probabilities_by_position[position],
                f"model_probabilities_by_position[{position}]",
            )
            probabilities.append(vector)
            sources.append({"position": position, "source": "football_model"})

    return {
        "draw_date": _parse_draw_date(draw_date, "draw_date"),
        "ticket_cutoff_at_utc": _parse_utc_timestamp(
            ticket_cutoff_at_utc, "ticket_cutoff_at_utc"
        )
        .isoformat()
        .replace("+00:00", "Z"),
        "probabilities": probabilities,
        "probability_sources": sources,
        "public_draw_positions": sorted(public_positions),
    }


def _validate_ticket_record(ticket: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ticket, dict) or ticket.get("schema_version") != 1:
        raise TicketOutcomeError("unsupported direct-ticket record schema")
    ticket_id = _required_text(ticket.get("ticket_id"), "ticket_id")
    draw_date = _parse_draw_date(ticket.get("draw_date"), "draw_date")
    created_at = _parse_utc_timestamp(
        ticket.get("ticket_created_at_utc"), "ticket_created_at_utc"
    )
    cutoff = _parse_utc_timestamp(
        ticket.get("ticket_cutoff_at_utc"), "ticket_cutoff_at_utc"
    )
    first_kickoff = _parse_timestamp(ticket.get("first_kickoff_at"), "first_kickoff_at")
    if not created_at < cutoff < first_kickoff.astimezone(UTC):
        raise TicketOutcomeError(
            "ticket timestamps must satisfy created_at < cutoff < first kickoff"
        )
    _validate_https_url(ticket.get("cutoff_evidence_url"), "cutoff_evidence_url")
    _validate_sha256(ticket.get("cutoff_evidence_sha256"), "cutoff_evidence_sha256")
    _validate_https_url(ticket.get("schedule_evidence_url"), "schedule_evidence_url")
    _validate_sha256(ticket.get("schedule_evidence_sha256"), "schedule_evidence_sha256")

    raw_columns = ticket.get("columns")
    if not isinstance(raw_columns, list) or not 1 <= len(raw_columns) <= 31_104:
        raise TicketOutcomeError(
            "ticket columns must contain between 1 and 31,104 columns"
        )
    columns: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for index, raw_column in enumerate(raw_columns, start=1):
        if (
            not isinstance(raw_column, list)
            or len(raw_column) != 14
            or any(
                not isinstance(sign, str) or sign not in SIGNS for sign in raw_column
            )
        ):
            raise TicketOutcomeError(
                f"ticket column {index} must contain 14 valid signs"
            )
        column = tuple(raw_column)
        if column in seen:
            raise TicketOutcomeError(f"ticket contains duplicate direct column {index}")
        seen.add(column)
        columns.append(column)

    return {
        "ticket_id": ticket_id,
        "draw_date": draw_date,
        "ticket_created_at_utc": created_at,
        "ticket_cutoff_at_utc": cutoff,
        "first_kickoff_at": first_kickoff,
        "columns": columns,
    }


def score_ticket_record(
    ticket: dict[str, Any],
    reconciliation_report: dict[str, Any],
    *,
    ticket_sha256: str | None = None,
    reconciliation_sha256: str | None = None,
) -> dict[str, Any]:
    """Score persisted 14-match columns against official played/public-draw outcomes.

    This function calculates hit and coverage results only. It does not infer prizes,
    payout, expected value or profitability.
    """
    validated = _validate_ticket_record(ticket)
    outcomes = outcomes_from_reconciliation(
        reconciliation_report, validated["draw_date"]
    )
    actual = tuple(item["sign"] for item in outcomes)
    columns = validated["columns"]
    hit_counts = [
        sum(sign == actual[position] for position, sign in enumerate(column))
        for column in columns
    ]
    best_hits = max(hit_counts)
    best_columns = [
        index + 1 for index, hits in enumerate(hit_counts) if hits == best_hits
    ]
    result: dict[str, Any] = {
        "schema_version": 1,
        "ticket_id": validated["ticket_id"],
        "draw_date": validated["draw_date"],
        "ticket_created_at_utc": validated["ticket_created_at_utc"]
        .isoformat()
        .replace("+00:00", "Z"),
        "ticket_cutoff_at_utc": validated["ticket_cutoff_at_utc"]
        .isoformat()
        .replace("+00:00", "Z"),
        "first_kickoff_at": validated["first_kickoff_at"].isoformat(),
        "timestamp_order_validated": True,
        "column_count": len(columns),
        "actual_main_results": list(actual),
        "outcome_types": [item["outcome_type"] for item in outcomes],
        "public_draw_positions": [
            item["position"]
            for item in outcomes
            if item["outcome_type"] == "public_draw"
        ],
        "played_positions": [
            item["position"] for item in outcomes if item["outcome_type"] == "played"
        ],
        "hit_counts_by_column": hit_counts,
        "best_column_hits": best_hits,
        "best_columns_1_based": best_columns,
        "covered_14": actual in set(columns),
        "outcome_provenance": outcomes,
        "payout_evaluated": False,
        "profitability_evaluated": False,
    }
    if ticket_sha256 is not None:
        result["ticket_sha256"] = _validate_sha256(ticket_sha256, "ticket_sha256")
    if reconciliation_sha256 is not None:
        result["reconciliation_sha256"] = _validate_sha256(
            reconciliation_sha256, "reconciliation_sha256"
        )
    return result
