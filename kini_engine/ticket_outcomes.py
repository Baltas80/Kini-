from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

from .team_identity import normalize_team_name

SIGNS = ("1", "X", "2")
PLENO15_CATEGORIES = frozenset({"0", "1", "2", "M"})
POSITIONS = tuple(range(1, 15))
SELAE_HOSTS = {"loteriasyapuestas.es", "www.loteriasyapuestas.es"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TicketOutcomeError(ValueError):
    """Raised when ticket or official coupon outcome evidence is incomplete."""


def _require_schema_v1(record: dict[str, Any], field: str) -> None:
    version = record.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise TicketOutcomeError(f"unsupported {field} schema")


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


def _pleno15_category(goals: int) -> str:
    return str(goals) if goals <= 2 else "M"


def validate_pleno15_report(
    report: dict[str, Any],
    *,
    draw_date: str,
    expected_home: str,
    expected_away: str,
    kickoff_at: datetime,
) -> dict[str, Any]:
    """Validate an official SELAE Pleno al 15 result and its 0/1/2/M categories."""
    if not isinstance(report, dict):
        raise TicketOutcomeError("Pleno al 15 result report must be an object")
    _require_schema_v1(report, "SELAE Pleno al 15 result")
    allowed_fields = {
        "schema_version",
        "provider",
        "draw_date",
        "source_url",
        "source_sha256",
        "evidence_type",
        "verified_at_utc",
        "verification_method",
        "home",
        "away",
        "home_goals",
        "away_goals",
        "home_category",
        "away_category",
    }
    if set(report) != allowed_fields:
        missing = sorted(allowed_fields - set(report))
        unexpected = sorted(set(report) - allowed_fields)
        raise TicketOutcomeError(
            f"Pleno al 15 result fields mismatch; missing={missing}, "
            f"unexpected={unexpected}"
        )
    if report.get("provider") != "SELAE":
        raise TicketOutcomeError("Pleno al 15 result provider must be SELAE")
    expected_date = _parse_draw_date(draw_date, "draw_date")
    if _parse_draw_date(report.get("draw_date"), "Pleno result draw_date") != expected_date:
        raise TicketOutcomeError("Pleno al 15 result draw date mismatch")

    source_url = _validate_official_selae_url(
        report.get("source_url"), "Pleno al 15 source_url"
    )
    source_sha256 = _validate_sha256(
        report.get("source_sha256"), "Pleno al 15 source_sha256"
    )
    evidence_type = _required_text(report.get("evidence_type"), "evidence_type")
    if evidence_type not in {"raw_official_response", "normalized_official_extract"}:
        raise TicketOutcomeError("Pleno al 15 evidence_type is unsupported")
    verified_at = _parse_utc_timestamp(
        report.get("verified_at_utc"), "verified_at_utc"
    )
    kickoff = kickoff_at.astimezone(UTC)
    if verified_at < kickoff:
        raise TicketOutcomeError(
            "Pleno al 15 result verification must not precede its kickoff"
        )
    verification_method = _required_text(
        report.get("verification_method"), "verification_method"
    )

    home = _required_text(report.get("home"), "Pleno al 15 home")
    away = _required_text(report.get("away"), "Pleno al 15 away")
    if (
        normalize_team_name(home) != normalize_team_name(expected_home)
        or normalize_team_name(away) != normalize_team_name(expected_away)
    ):
        raise TicketOutcomeError(
            "Pleno al 15 result team identity does not match the stored coupon plan"
        )

    home_goals = report.get("home_goals")
    away_goals = report.get("away_goals")
    if (
        isinstance(home_goals, bool)
        or isinstance(away_goals, bool)
        or not isinstance(home_goals, int)
        or not isinstance(away_goals, int)
        or home_goals < 0
        or away_goals < 0
    ):
        raise TicketOutcomeError("Pleno al 15 goals must be non-negative integers")
    home_category = _pleno15_category(home_goals)
    away_category = _pleno15_category(away_goals)
    if report.get("home_category") not in PLENO15_CATEGORIES or (
        report.get("away_category") not in PLENO15_CATEGORIES
    ):
        raise TicketOutcomeError("Pleno al 15 categories must be 0, 1, 2 or M")
    if (
        report.get("home_category") != home_category
        or report.get("away_category") != away_category
    ):
        raise TicketOutcomeError(
            "Pleno al 15 categories conflict with the official goal counts"
        )

    return {
        "draw_date": expected_date,
        "source_url": source_url,
        "source_sha256": source_sha256,
        "evidence_type": evidence_type,
        "verified_at_utc": verified_at.isoformat().replace("+00:00", "Z"),
        "verification_method": verification_method,
        "home": home,
        "away": away,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_category": home_category,
        "away_category": away_category,
    }


def outcomes_from_reconciliation(
    report: dict[str, Any],
    draw_date: str,
) -> list[dict[str, Any]]:
    """Build a complete 14-sign outcome vector from the SELAE reconciliation report.

    Played fixtures use their reconciled score-derived sign. Public-draw fixtures
    use the official coupon sign, never the reported placeholder score.
    """
    expected_date = _parse_draw_date(draw_date, "draw_date")
    if not isinstance(report, dict):
        raise TicketOutcomeError("SELAE fixture reconciliation must be an object")
    _require_schema_v1(report, "SELAE fixture reconciliation")

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
    ticket_created_at_utc: str,
    ticket_cutoff_at_utc: str,
) -> dict[str, Any]:
    """Validate a participant snapshot captured before ticket creation and close."""
    expected_date = _parse_draw_date(draw_date, "draw_date")
    expected_position = _position(position, "position")
    created_at = _parse_utc_timestamp(ticket_created_at_utc, "ticket_created_at_utc")
    cutoff = _parse_utc_timestamp(ticket_cutoff_at_utc, "ticket_cutoff_at_utc")
    if created_at >= cutoff:
        raise TicketOutcomeError("ticket creation must be earlier than ticket close")
    if not isinstance(snapshot, dict):
        raise TicketOutcomeError("pre-close forecast snapshot must be an object")
    _require_schema_v1(snapshot, "pre-close forecast snapshot")
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
    if captured_at >= created_at:
        raise TicketOutcomeError(
            "participant-forecast snapshot must be captured strictly before ticket creation"
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


def _validate_coupon_plan(
    plan: dict[str, Any],
    draw_date: str,
) -> dict[str, Any]:
    """Validate a pre-kickoff coupon plan without reading realized match outcomes."""
    if not isinstance(plan, dict):
        raise TicketOutcomeError("pre-ticket coupon plan must be an object")
    _require_schema_v1(plan, "pre-ticket coupon plan")
    allowed_plan_fields = {
        "schema_version",
        "provider",
        "draw_date",
        "schedule_captured_at_utc",
        "ticket_created_at_utc",
        "schedule_evidence_url",
        "schedule_evidence_sha256",
        "ticket_cutoff_at_utc",
        "cutoff_evidence_url",
        "cutoff_evidence_sha256",
        "cutoff_evidence_captured_at_utc",
        "first_kickoff_at",
        "pleno15_home",
        "pleno15_away",
        "pleno15_kickoff_at",
        "positions",
    }
    if set(plan) != allowed_plan_fields:
        unexpected = sorted(set(plan) - allowed_plan_fields)
        missing = sorted(allowed_plan_fields - set(plan))
        raise TicketOutcomeError(
            f"pre-ticket coupon plan fields mismatch; missing={missing}, "
            f"unexpected={unexpected}"
        )
    if plan.get("provider") != "SELAE":
        raise TicketOutcomeError("pre-ticket coupon plan provider must be SELAE")
    expected_date = _parse_draw_date(draw_date, "draw_date")
    if _parse_draw_date(plan.get("draw_date"), "plan.draw_date") != expected_date:
        raise TicketOutcomeError("pre-ticket coupon plan draw date mismatch")

    schedule_url = _validate_official_selae_url(
        plan.get("schedule_evidence_url"), "schedule_evidence_url"
    )
    schedule_sha256 = _validate_sha256(
        plan.get("schedule_evidence_sha256"), "schedule_evidence_sha256"
    )
    cutoff = _parse_utc_timestamp(
        plan.get("ticket_cutoff_at_utc"), "plan.ticket_cutoff_at_utc"
    )
    schedule_captured_at = _parse_utc_timestamp(
        plan.get("schedule_captured_at_utc"), "schedule_captured_at_utc"
    )
    created_at = _parse_utc_timestamp(
        plan.get("ticket_created_at_utc"), "ticket_created_at_utc"
    )
    cutoff_url = _validate_official_selae_url(
        plan.get("cutoff_evidence_url"), "cutoff_evidence_url"
    )
    cutoff_sha256 = _validate_sha256(
        plan.get("cutoff_evidence_sha256"), "cutoff_evidence_sha256"
    )
    cutoff_evidence_captured_at = _parse_utc_timestamp(
        plan.get("cutoff_evidence_captured_at_utc"),
        "cutoff_evidence_captured_at_utc",
    )
    if cutoff_evidence_captured_at >= created_at:
        raise TicketOutcomeError(
            "ticket cutoff evidence must be captured strictly before ticket creation"
        )
    if created_at >= cutoff:
        raise TicketOutcomeError("ticket creation must be earlier than ticket close")
    if schedule_captured_at >= created_at:
        raise TicketOutcomeError(
            "coupon schedule must be captured strictly before ticket creation"
        )
    first_kickoff = _parse_timestamp(
        plan.get("first_kickoff_at"), "plan.first_kickoff_at"
    )
    pleno_home = _required_text(plan.get("pleno15_home"), "pleno15_home")
    pleno_away = _required_text(plan.get("pleno15_away"), "pleno15_away")
    pleno_kickoff = _parse_timestamp(
        plan.get("pleno15_kickoff_at"), "pleno15_kickoff_at"
    )
    if pleno_kickoff.astimezone(UTC) <= cutoff:
        raise TicketOutcomeError("Pleno al 15 kickoff must be after ticket close")
    if cutoff >= first_kickoff.astimezone(UTC):
        raise TicketOutcomeError("ticket cutoff must be earlier than first kickoff")

    raw_positions = plan.get("positions")
    if not isinstance(raw_positions, list) or len(raw_positions) != len(POSITIONS):
        raise TicketOutcomeError("pre-ticket coupon plan must cover positions 1..14")
    positions: dict[int, dict[str, Any]] = {}
    scheduled_kickoffs: list[datetime] = [pleno_kickoff.astimezone(UTC)]
    public_draw_positions: set[int] = set()
    common_fields = {
        "position",
        "fixture_status",
        "home",
        "away",
        "kickoff_at",
    }
    public_draw_fields = common_fields | {
        "status_evidence_url",
        "status_evidence_sha256",
        "status_captured_at_utc",
    }

    for raw in raw_positions:
        if not isinstance(raw, dict):
            raise TicketOutcomeError("each coupon-plan position must be an object")
        position = _position(raw.get("position"), "plan position")
        if position in positions:
            raise TicketOutcomeError(
                f"pre-ticket coupon plan contains duplicate position {position}"
            )
        status = raw.get("fixture_status")
        if status == "scheduled":
            if set(raw) != common_fields:
                raise TicketOutcomeError(
                    f"scheduled position {position} contains unsupported or missing fields"
                )
        elif status == "public_draw_expected":
            if set(raw) != public_draw_fields:
                raise TicketOutcomeError(
                    f"public-draw position {position} contains unsupported or missing fields"
                )
        else:
            raise TicketOutcomeError(
                f"position {position} fixture_status must be scheduled "
                "or public_draw_expected"
            )

        home = _required_text(raw.get("home"), f"position {position}.home")
        away = _required_text(raw.get("away"), f"position {position}.away")
        kickoff = _parse_timestamp(
            raw.get("kickoff_at"), f"position {position}.kickoff_at"
        )
        if status == "scheduled":
            if kickoff.astimezone(UTC) <= cutoff:
                raise TicketOutcomeError(
                    f"scheduled position {position} kickoff must be after ticket close"
                )
            scheduled_kickoffs.append(kickoff.astimezone(UTC))
        else:
            status_url = _validate_official_selae_url(
                raw.get("status_evidence_url"),
                f"position {position}.status_evidence_url",
            )
            status_sha256 = _validate_sha256(
                raw.get("status_evidence_sha256"),
                f"position {position}.status_evidence_sha256",
            )
            status_captured_at = _parse_utc_timestamp(
                raw.get("status_captured_at_utc"),
                f"position {position}.status_captured_at_utc",
            )
            if status_captured_at >= created_at:
                raise TicketOutcomeError(
                    f"public-draw status at position {position} must be evidenced "
                    "strictly before ticket creation"
                )
            public_draw_positions.add(position)

        positions[position] = {
            "fixture_status": status,
            "home": home,
            "away": away,
            "kickoff_at": kickoff,
        }
        if status == "public_draw_expected":
            positions[position].update(
                {
                    "status_evidence_url": status_url,
                    "status_evidence_sha256": status_sha256,
                    "status_captured_at_utc": status_captured_at,
                }
            )

    if set(positions) != set(POSITIONS):
        missing = sorted(set(POSITIONS) - set(positions))
        raise TicketOutcomeError(
            f"pre-ticket coupon plan must cover positions 1..14; missing={missing}"
        )
    if not scheduled_kickoffs:
        raise TicketOutcomeError(
            "pre-ticket coupon plan must contain at least one scheduled fixture"
        )
    if min(scheduled_kickoffs) != first_kickoff.astimezone(UTC):
        raise TicketOutcomeError(
            "first_kickoff_at does not match the earliest scheduled fixture kickoff "
            "or Pleno al 15 kickoff"
        )

    return {
        "draw_date": expected_date,
        "ticket_cutoff_at_utc": cutoff,
        "ticket_created_at_utc": created_at,
        "cutoff_evidence_url": cutoff_url,
        "cutoff_evidence_sha256": cutoff_sha256,
        "cutoff_evidence_captured_at_utc": cutoff_evidence_captured_at,
        "first_kickoff_at": first_kickoff,
        "pleno15_home": pleno_home,
        "pleno15_away": pleno_away,
        "pleno15_kickoff_at": pleno_kickoff,
        "schedule_evidence_url": schedule_url,
        "schedule_evidence_sha256": schedule_sha256,
        "schedule_captured_at_utc": schedule_captured_at,
        "positions": positions,
        "scheduled_positions": set(POSITIONS) - public_draw_positions,
        "public_draw_positions": public_draw_positions,
    }


def validate_coupon_plan(plan: dict[str, Any], draw_date: str) -> dict[str, Any]:
    """Public, strict validator for the pre-ticket schedule-only coupon plan."""
    return _validate_coupon_plan(plan, draw_date)


def build_ticket_probability_vectors(
    *,
    draw_date: str,
    coupon_plan: dict[str, Any],
    model_probabilities_by_position: Mapping[int, dict[str, float]],
    public_draw_snapshots: Mapping[int, dict[str, Any]],
) -> dict[str, Any]:
    """Build pre-kickoff vectors from a schedule-only plan and timestamped sources.

    This function deliberately does not accept the post-match reconciliation report:
    realized scores/signs are unavailable at ticket-construction time and must never
    determine which forecasts are produced.
    """
    plan = validate_coupon_plan(coupon_plan, draw_date)
    scheduled_positions = plan["scheduled_positions"]
    public_positions = plan["public_draw_positions"]

    if not isinstance(model_probabilities_by_position, Mapping):
        raise TicketOutcomeError("model probabilities must be a position mapping")
    if not isinstance(public_draw_snapshots, Mapping):
        raise TicketOutcomeError("public-draw snapshots must be a position mapping")
    model_positions = {
        _position(position, "model probability position")
        for position in model_probabilities_by_position
    }
    snapshot_positions = {
        _position(position, "public-draw snapshot position")
        for position in public_draw_snapshots
    }
    if model_positions != scheduled_positions:
        raise TicketOutcomeError(
            "football model probabilities must cover scheduled positions only; "
            f"expected={sorted(scheduled_positions)}, received={sorted(model_positions)}"
        )
    if snapshot_positions != public_positions:
        raise TicketOutcomeError(
            "pre-close participant snapshots must cover every public-draw position only; "
            f"expected={sorted(public_positions)}, received={sorted(snapshot_positions)}"
        )

    probabilities = []
    sources = []
    for position in POSITIONS:
        if position in public_positions:
            validated = validate_preclose_public_draw_snapshot(
                public_draw_snapshots[position],
                draw_date=draw_date,
                position=position,
                ticket_created_at_utc=plan["ticket_created_at_utc"]
                .isoformat()
                .replace("+00:00", "Z"),
                ticket_cutoff_at_utc=plan["ticket_cutoff_at_utc"]
                .isoformat()
                .replace("+00:00", "Z"),
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
        "draw_date": plan["draw_date"],
        "ticket_created_at_utc": plan["ticket_created_at_utc"]
        .isoformat()
        .replace("+00:00", "Z"),
        "ticket_cutoff_at_utc": plan["ticket_cutoff_at_utc"]
        .isoformat()
        .replace("+00:00", "Z"),
        "first_kickoff_at": plan["first_kickoff_at"].isoformat(),
        "pleno15_home": plan["pleno15_home"],
        "pleno15_away": plan["pleno15_away"],
        "pleno15_kickoff_at": plan["pleno15_kickoff_at"].isoformat(),
        "cutoff_evidence": {
            "source_url": plan["cutoff_evidence_url"],
            "source_sha256": plan["cutoff_evidence_sha256"],
            "captured_at_utc": plan["cutoff_evidence_captured_at_utc"]
            .isoformat()
            .replace("+00:00", "Z"),
        },
        "schedule_evidence": {
            "source_url": plan["schedule_evidence_url"],
            "source_sha256": plan["schedule_evidence_sha256"],
            "captured_at_utc": plan["schedule_captured_at_utc"]
            .isoformat()
            .replace("+00:00", "Z"),
        },
        "probabilities": probabilities,
        "probability_sources": sources,
        "public_draw_positions": sorted(public_positions),
    }


def _validate_ticket_record(ticket: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ticket, dict):
        raise TicketOutcomeError("direct-ticket record must be an object")
    _require_schema_v1(ticket, "direct-ticket record")

    required_fields = {
        "schema_version",
        "ticket_id",
        "draw_date",
        "ticket_created_at_utc",
        "ticket_cutoff_at_utc",
        "first_kickoff_at",
        "cutoff_evidence_url",
        "cutoff_evidence_sha256",
        "cutoff_evidence_captured_at_utc",
        "schedule_evidence_url",
        "schedule_evidence_sha256",
        "schedule_evidence_captured_at_utc",
        "pleno15_home",
        "pleno15_away",
        "pleno15_kickoff_at",
        "coupon_plan",
        "probability_vectors",
        "probability_sources",
        "public_draw_positions",
        "columns",
        "pleno15_combinations",
        "budget",
        "cost_eur",
    }
    if set(ticket) != required_fields:
        missing = sorted(required_fields - set(ticket))
        unexpected = sorted(set(ticket) - required_fields)
        raise TicketOutcomeError(
            f"direct-ticket fields mismatch; missing={missing}, unexpected={unexpected}"
        )

    ticket_id = _required_text(ticket.get("ticket_id"), "ticket_id")
    draw_date = _parse_draw_date(ticket.get("draw_date"), "draw_date")
    if ticket.get("draw_date") != draw_date:
        raise TicketOutcomeError("draw_date must use canonical YYYY-MM-DD format")
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

    plan = _validate_coupon_plan(ticket.get("coupon_plan"), draw_date)
    if (
        created_at != plan["ticket_created_at_utc"]
        or cutoff != plan["ticket_cutoff_at_utc"]
    ):
        raise TicketOutcomeError(
            "ticket timestamps do not match the validated coupon plan"
        )
    if first_kickoff.astimezone(UTC) != plan["first_kickoff_at"].astimezone(UTC):
        raise TicketOutcomeError(
            "first_kickoff_at does not match the validated coupon plan"
        )

    evidence_fields = (
        (
            "cutoff_evidence_url",
            "cutoff_evidence_sha256",
            "cutoff_evidence_captured_at_utc",
            "cutoff_evidence_url",
            "cutoff_evidence_sha256",
            "cutoff_evidence_captured_at_utc",
        ),
        (
            "schedule_evidence_url",
            "schedule_evidence_sha256",
            "schedule_evidence_captured_at_utc",
            "schedule_evidence_url",
            "schedule_evidence_sha256",
            "schedule_captured_at_utc",
        ),
    )
    for (
        url_field,
        digest_field,
        captured_field,
        plan_url_field,
        plan_digest_field,
        plan_captured_field,
    ) in evidence_fields:
        url = _validate_official_selae_url(ticket.get(url_field), url_field)
        digest = _validate_sha256(ticket.get(digest_field), digest_field)
        captured_at = _parse_utc_timestamp(ticket.get(captured_field), captured_field)
        if (
            url != plan[plan_url_field]
            or digest != plan[plan_digest_field]
            or captured_at != plan[plan_captured_field]
        ):
            raise TicketOutcomeError(
                f"{url_field}/{digest_field}/{captured_field} do not match coupon-plan evidence"
            )

    pleno_home = _required_text(ticket.get("pleno15_home"), "pleno15_home")
    pleno_away = _required_text(ticket.get("pleno15_away"), "pleno15_away")
    pleno_kickoff = _parse_timestamp(
        ticket.get("pleno15_kickoff_at"), "pleno15_kickoff_at"
    )
    if (
        pleno_home != plan["pleno15_home"]
        or pleno_away != plan["pleno15_away"]
        or pleno_kickoff.astimezone(UTC) != plan["pleno15_kickoff_at"].astimezone(UTC)
    ):
        raise TicketOutcomeError(
            "Pleno al 15 identity/kickoff does not match coupon plan"
        )

    raw_public_positions = ticket.get("public_draw_positions")
    expected_public_positions = sorted(plan["public_draw_positions"])
    if (
        not isinstance(raw_public_positions, list)
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in raw_public_positions
        )
        or raw_public_positions != expected_public_positions
    ):
        raise TicketOutcomeError(
            "public_draw_positions must exactly match the validated coupon plan"
        )

    raw_vectors = ticket.get("probability_vectors")
    if not isinstance(raw_vectors, list) or len(raw_vectors) != 14:
        raise TicketOutcomeError("ticket must contain 14 1/X/2 probability vectors")
    probability_vectors = [
        _validate_probability_vector(vector, f"probability_vectors[{index}]")
        for index, vector in enumerate(raw_vectors, start=1)
    ]

    raw_sources = ticket.get("probability_sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != 14:
        raise TicketOutcomeError("ticket must contain 14 probability-source records")
    probability_sources: list[dict[str, Any]] = []
    for position, source in enumerate(raw_sources, start=1):
        if (
            not isinstance(source, dict)
            or isinstance(source.get("position"), bool)
            or not isinstance(source.get("position"), int)
            or source.get("position") != position
        ):
            raise TicketOutcomeError(
                f"probability_sources[{position}] must identify coupon position {position}"
            )
        if position in plan["public_draw_positions"]:
            expected_source_fields = {
                "position",
                "source",
                "source_id",
                "captured_at_utc",
                "source_url",
                "source_sha256",
            }
            if (
                set(source) != expected_source_fields
                or source.get("source") != "preclose_participant_forecast"
            ):
                raise TicketOutcomeError(
                    f"position {position} must retain complete pre-close public-draw provenance"
                )
            source_id = _required_text(
                source.get("source_id"), f"position {position}.source_id"
            )
            source_url = _validate_official_selae_url(
                source.get("source_url"), f"position {position}.source_url"
            )
            source_digest = _validate_sha256(
                source.get("source_sha256"), f"position {position}.source_sha256"
            )
            captured_at = _parse_utc_timestamp(
                source.get("captured_at_utc"), f"position {position}.captured_at_utc"
            )
            if captured_at >= created_at:
                raise TicketOutcomeError(
                    f"position {position} public-draw forecast was not captured before ticket creation"
                )
            probability_sources.append(
                {
                    "position": position,
                    "source": "preclose_participant_forecast",
                    "source_id": source_id,
                    "captured_at_utc": captured_at,
                    "source_url": source_url,
                    "source_sha256": source_digest,
                }
            )
        else:
            expected_source_fields = {"position", "source", "model_mode"}
            if (
                set(source) != expected_source_fields
                or source.get("source") != "football_model"
                or not isinstance(source.get("model_mode"), str)
                or source.get("model_mode")
                not in {"ensemble", "ensemble_dc_ml", "dc", "ml"}
            ):
                raise TicketOutcomeError(
                    f"position {position} must identify a supported football-model forecast"
                )
            probability_sources.append(dict(source))

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

    categories = {"0", "1", "2", "M"}
    raw_pleno = ticket.get("pleno15_combinations")
    if not isinstance(raw_pleno, list) or not 1 <= len(raw_pleno) <= 16:
        raise TicketOutcomeError(
            "pleno15_combinations must contain 1 to 16 category pairs"
        )
    pleno_combinations: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, pair in enumerate(raw_pleno, start=1):
        if (
            not isinstance(pair, dict)
            or set(pair) != {"home_goals", "away_goals"}
            or not isinstance(pair.get("home_goals"), str)
            or pair.get("home_goals") not in categories
            or not isinstance(pair.get("away_goals"), str)
            or pair.get("away_goals") not in categories
        ):
            raise TicketOutcomeError(
                f"Pleno al 15 combination {index} has invalid categories"
            )
        normalized_pair = (pair["home_goals"], pair["away_goals"])
        if normalized_pair in seen_pairs:
            raise TicketOutcomeError(f"duplicate Pleno al 15 combination {index}")
        seen_pairs.add(normalized_pair)
        pleno_combinations.append(
            {"home_goals": normalized_pair[0], "away_goals": normalized_pair[1]}
        )

    budget = ticket.get("budget")
    if (
        isinstance(budget, bool)
        or not isinstance(budget, int)
        or not 1 <= budget <= 31_104
    ):
        raise TicketOutcomeError("ticket budget must be an integer from 1 to 31,104")
    if len(columns) > budget:
        raise TicketOutcomeError("ticket column count exceeds its declared budget")

    total_bets = len(columns) * len(pleno_combinations)
    if not 2 <= total_bets <= 31_104:
        raise TicketOutcomeError("ticket total bets violate SELAE's minimum/maximum")
    cost = ticket.get("cost_eur")
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not isfinite(float(cost))
        or abs(float(cost) - round(total_bets * 0.75, 2)) > 0.005
    ):
        raise TicketOutcomeError(
            "ticket cost does not match total bets at EUR 0.75 per bet"
        )

    return {
        "ticket_id": ticket_id,
        "draw_date": draw_date,
        "ticket_created_at_utc": created_at,
        "ticket_cutoff_at_utc": cutoff,
        "first_kickoff_at": first_kickoff,
        "pleno15_home": pleno_home,
        "pleno15_away": pleno_away,
        "pleno15_kickoff_at": pleno_kickoff,
        "columns": columns,
        "probability_vectors": probability_vectors,
        "probability_sources": probability_sources,
        "public_draw_positions": expected_public_positions,
        "pleno15_combinations": pleno_combinations,
        "budget": budget,
        "total_bets": total_bets,
        "cost_eur": float(cost),
    }


def validate_ticket_record(ticket: dict[str, Any]) -> dict[str, Any]:
    """Public structural validator for an immutable direct-ticket record."""
    return _validate_ticket_record(ticket)


def score_ticket_record(
    ticket: dict[str, Any],
    reconciliation_report: dict[str, Any],
    *,
    ticket_sha256: str | None = None,
    reconciliation_sha256: str | None = None,
    pleno15_report: dict[str, Any] | None = None,
    pleno15_report_sha256: str | None = None,
) -> dict[str, Any]:
    """Score 14 signs and, when supplied, official Pleno al 15 categories."""
    validated = _validate_ticket_record(ticket)
    outcomes = outcomes_from_reconciliation(
        reconciliation_report, validated["draw_date"]
    )
    if pleno15_report is None:
        if pleno15_report_sha256 is not None:
            raise TicketOutcomeError(
                "pleno15_report_sha256 requires a Pleno al 15 result report"
            )
        validated_pleno15 = None
    else:
        validated_pleno15 = validate_pleno15_report(
            pleno15_report,
            draw_date=validated["draw_date"],
            expected_home=validated["pleno15_home"],
            expected_away=validated["pleno15_away"],
            kickoff_at=validated["pleno15_kickoff_at"],
        )
    pleno15_digest = (
        _validate_sha256(pleno15_report_sha256, "pleno15_report_sha256")
        if pleno15_report_sha256 is not None
        else None
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
        "pleno15_evaluated": validated_pleno15 is not None,
        "pleno15_actual": None,
        "pleno15_hit": None,
        "covered_full_coupon": None,
        "pleno15_outcome_provenance": None,
        "payout_evaluated": False,
        "profitability_evaluated": False,
    }
    if ticket_sha256 is not None:
        result["ticket_sha256"] = _validate_sha256(ticket_sha256, "ticket_sha256")
    if reconciliation_sha256 is not None:
        result["reconciliation_sha256"] = _validate_sha256(
            reconciliation_sha256, "reconciliation_sha256"
        )
    if validated_pleno15 is not None:
        actual_pleno_pair = (
            validated_pleno15["home_category"],
            validated_pleno15["away_category"],
        )
        selected_pleno_pairs = {
            (pair["home_goals"], pair["away_goals"])
            for pair in validated["pleno15_combinations"]
        }
        pleno15_hit = actual_pleno_pair in selected_pleno_pairs
        result.update(
            {
                "pleno15_actual": {
                    "home_goals": validated_pleno15["home_goals"],
                    "away_goals": validated_pleno15["away_goals"],
                    "home_category": actual_pleno_pair[0],
                    "away_category": actual_pleno_pair[1],
                },
                "pleno15_hit": pleno15_hit,
                "covered_full_coupon": (actual in set(columns)) and pleno15_hit,
                "pleno15_outcome_provenance": validated_pleno15,
            }
        )
        if pleno15_digest is not None:
            result["pleno15_report_sha256"] = pleno15_digest
    return result
