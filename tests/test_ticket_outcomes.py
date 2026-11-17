from __future__ import annotations

from copy import deepcopy

import pytest

from kini_engine.ticket_outcomes import (
    TicketOutcomeError,
    build_ticket_probability_vectors,
    outcomes_from_reconciliation,
    score_ticket_record,
    validate_preclose_public_draw_snapshot,
)

DRAW_DATE = "2026-11-08"
SELAE_URL = (
    "https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/"
    "la-quiniela-premios-y-ganadores-del-08-de-noviembre-de-2026"
)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _sign(home_goals: int, away_goals: int) -> str:
    return "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"


def _reconciliation() -> dict[str, object]:
    resolved = []
    excluded = []
    for position in range(1, 15):
        if position == 7:
            excluded.append(
                {
                    "draw_date": DRAW_DATE,
                    "position": position,
                    "home": {"display_name": "Postponed Home (M)"},
                    "away": {"display_name": "Postponed Away (M)"},
                    "sign": "2",
                    "score_status": "not_played",
                    "sign_determination": "public_draw",
                    "home_goals": None,
                    "away_goals": None,
                    "reported_score_raw": "0-0",
                    "status_reason": "Fixture postponed and resolved by public draw.",
                    "source_url": SELAE_URL,
                    "raw_sha256": HASH_A,
                    "sign_evidence_url": SELAE_URL,
                    "sign_evidence_checked_at_utc": "2026-11-17T06:00:00Z",
                    "training_label_eligible": False,
                    "ticket_outcome_eligible": True,
                }
            )
            continue
        home_goals = position % 3
        away_goals = (position + 1) % 3
        resolved.append(
            {
                "draw_date": DRAW_DATE,
                "coupon_position": position,
                "home_selae_display_name": f"Home {position} (M)",
                "away_selae_display_name": f"Away {position} (M)",
                "home_goals": home_goals,
                "away_goals": away_goals,
                "target_1x2": _sign(home_goals, away_goals),
                "draw_source_url": SELAE_URL,
                "draw_raw_sha256": HASH_A,
                "training_label_eligible": True,
            }
        )
    return {
        "schema_version": 1,
        "success": True,
        "resolved_fixtures": resolved,
        "excluded_fixtures": excluded,
        "unresolved_fixtures": [],
        "unused_crosswalk_entries": [],
    }


def _ticket(report: dict[str, object]) -> dict[str, object]:
    outcomes = outcomes_from_reconciliation(report, DRAW_DATE)
    actual = [item["sign"] for item in outcomes]
    second = ["1" if sign != "1" else "2" for sign in actual]
    return {
        "schema_version": 1,
        "ticket_id": "test-ticket-2026-11-08",
        "draw_date": DRAW_DATE,
        "ticket_created_at_utc": "2026-11-08T09:30:00Z",
        "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
        "first_kickoff_at": "2026-11-08T14:00:00+01:00",
        "cutoff_evidence_url": SELAE_URL,
        "cutoff_evidence_sha256": HASH_B,
        "schedule_evidence_url": "https://www.malagacf.com/fixture-schedule",
        "schedule_evidence_sha256": HASH_C,
        "columns": [actual, second],
    }


def _preclose_snapshot() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "SELAE",
        "source_id": "participant-forecast-capture-001",
        "draw_date": DRAW_DATE,
        "position": 7,
        "captured_at_utc": "2026-11-08T10:30:00Z",
        "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
        "source_url": SELAE_URL,
        "source_sha256": HASH_B,
        "probabilities": {"1": 0.12, "X": 0.16, "2": 0.72},
    }


def _coupon_plan() -> dict[str, object]:
    positions = []
    for position in range(1, 15):
        if position == 7:
            positions.append(
                {
                    "position": position,
                    "fixture_status": "public_draw_expected",
                    "home": "Postponed Home (M)",
                    "away": "Postponed Away (M)",
                    "kickoff_at": "2026-11-08T12:00:00+01:00",
                    "status_evidence_url": SELAE_URL,
                    "status_evidence_sha256": HASH_C,
                    "status_captured_at_utc": "2026-11-08T10:15:00Z",
                }
            )
        else:
            positions.append(
                {
                    "position": position,
                    "fixture_status": "scheduled",
                    "home": f"Home {position} (M)",
                    "away": f"Away {position} (M)",
                    "kickoff_at": "2026-11-08T14:00:00+01:00",
                }
            )
    return {
        "schema_version": 1,
        "provider": "SELAE",
        "draw_date": DRAW_DATE,
        "schedule_captured_at_utc": "2026-11-08T09:00:00Z",
        "schedule_evidence_url": SELAE_URL,
        "schedule_evidence_sha256": HASH_A,
        "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
        "first_kickoff_at": "2026-11-08T14:00:00+01:00",
        "positions": positions,
    }


def test_reconciliation_builds_complete_outcome_vector_and_preserves_public_draw() -> (
    None
):
    outcomes = outcomes_from_reconciliation(_reconciliation(), DRAW_DATE)

    assert len(outcomes) == 14
    public_draw = outcomes[6]
    assert public_draw["position"] == 7
    assert public_draw["sign"] == "2"
    assert public_draw["outcome_type"] == "public_draw"
    assert public_draw["reported_score_raw"] == "0-0"
    assert public_draw["home_goals"] is None
    assert public_draw["away_goals"] is None
    assert public_draw["training_label_eligible"] is False
    assert public_draw["ticket_outcome_eligible"] is True


def test_ticket_scoring_uses_public_draw_sign_not_reported_placeholder_score() -> None:
    report = _reconciliation()
    ticket = _ticket(report)

    result = score_ticket_record(
        ticket,
        report,
        ticket_sha256=HASH_B,
        reconciliation_sha256=HASH_C,
    )

    assert result["actual_main_results"][6] == "2"
    assert result["outcome_types"][6] == "public_draw"
    assert result["public_draw_positions"] == [7]
    assert result["first_kickoff_at"] == "2026-11-08T14:00:00+01:00"
    assert result["covered_14"] is True
    assert result["best_column_hits"] == 14
    assert result["best_columns_1_based"] == [1]
    assert result["ticket_sha256"] == HASH_B
    assert result["reconciliation_sha256"] == HASH_C
    assert result["payout_evaluated"] is False
    assert result["profitability_evaluated"] is False


def test_reconciliation_rejects_missing_or_duplicate_positions() -> None:
    report = _reconciliation()
    report["excluded_fixtures"].clear()
    with pytest.raises(TicketOutcomeError, match="cover positions 1..14"):
        outcomes_from_reconciliation(report, DRAW_DATE)

    report = _reconciliation()
    report["resolved_fixtures"].append(deepcopy(report["resolved_fixtures"][0]))
    with pytest.raises(TicketOutcomeError, match="duplicate outcome"):
        outcomes_from_reconciliation(report, DRAW_DATE)


def test_reconciliation_rejects_unresolved_fixture_for_requested_draw() -> None:
    report = _reconciliation()
    report["unresolved_fixtures"] = [
        {"draw_date": DRAW_DATE, "position": 3, "reason": "ambiguous"}
    ]
    with pytest.raises(TicketOutcomeError, match="unresolved fixtures"):
        outcomes_from_reconciliation(report, DRAW_DATE)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("training_label_eligible", True),
        ("ticket_outcome_eligible", False),
        ("score_status", "played"),
        ("sign_determination", "score"),
        ("home_goals", 0),
    ],
)
def test_public_draw_requires_non_training_ticket_outcome_contract(
    field: str, value: object
) -> None:
    report = _reconciliation()
    report["excluded_fixtures"][0][field] = value
    with pytest.raises(TicketOutcomeError, match="public-draw eligibility"):
        outcomes_from_reconciliation(report, DRAW_DATE)


def test_public_draw_rejects_unofficial_sign_evidence() -> None:
    report = _reconciliation()
    report["excluded_fixtures"][0]["sign_evidence_url"] = "https://example.com/draw.pdf"
    with pytest.raises(TicketOutcomeError, match="official SELAE host"):
        outcomes_from_reconciliation(report, DRAW_DATE)


def test_ticket_rejects_creation_after_cutoff_or_cutoff_after_first_kickoff() -> None:
    report = _reconciliation()
    ticket = _ticket(report)
    ticket["ticket_created_at_utc"] = "2026-11-08T11:00:00Z"
    with pytest.raises(TicketOutcomeError, match="created_at < cutoff"):
        score_ticket_record(ticket, report)

    ticket = _ticket(report)
    ticket["ticket_cutoff_at_utc"] = "2026-11-08T13:30:00Z"
    with pytest.raises(TicketOutcomeError, match="created_at < cutoff"):
        score_ticket_record(ticket, report)


def test_ticket_rejects_duplicate_columns_and_invalid_signs() -> None:
    report = _reconciliation()
    ticket = _ticket(report)
    ticket["columns"].append(ticket["columns"][0].copy())
    with pytest.raises(TicketOutcomeError, match="duplicate direct column"):
        score_ticket_record(ticket, report)

    ticket = _ticket(report)
    ticket["columns"][0][0] = "D"
    with pytest.raises(TicketOutcomeError, match="14 valid signs"):
        score_ticket_record(ticket, report)


def test_ticket_requires_cutoff_and_schedule_provenance() -> None:
    report = _reconciliation()
    ticket = _ticket(report)
    ticket["schedule_evidence_sha256"] = "not-a-hash"
    with pytest.raises(TicketOutcomeError, match="schedule_evidence_sha256"):
        score_ticket_record(ticket, report)


def test_build_probability_vectors_uses_preclose_plan_not_realized_outcomes() -> None:
    plan = _coupon_plan()
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    result = build_ticket_probability_vectors(
        draw_date=DRAW_DATE,
        coupon_plan=plan,
        model_probabilities_by_position=model_probabilities,
        public_draw_snapshots={7: _preclose_snapshot()},
    )

    assert len(result["probabilities"]) == 14
    assert result["probabilities"][6] == {"1": 0.12, "X": 0.16, "2": 0.72}
    assert result["probability_sources"][6]["source"] == "preclose_participant_forecast"
    assert result["probability_sources"][6]["captured_at_utc"] == "2026-11-08T10:30:00Z"
    assert result["public_draw_positions"] == [7]
    assert result["schedule_evidence"]["source_sha256"] == HASH_A
    assert "actual_main_results" not in result


def test_probability_builder_does_not_accept_post_match_reconciliation_report() -> None:
    report = _reconciliation()
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="coupon plan fields mismatch"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=report,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_outcome_fields_in_pre_ticket_plan() -> None:
    plan = _coupon_plan()
    plan["positions"][0]["home_goals"] = 2
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="unsupported or missing fields"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_requires_snapshot_for_every_public_draw_position() -> None:
    plan = _coupon_plan()
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="snapshots must cover"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={},
        )


def test_probability_builder_rejects_model_probability_for_public_draw_position() -> None:
    plan = _coupon_plan()
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2} for position in range(1, 15)
    }
    with pytest.raises(TicketOutcomeError, match="scheduled positions only"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_schedule_captured_at_or_after_cutoff() -> None:
    plan = _coupon_plan()
    plan["schedule_captured_at_utc"] = "2026-11-08T11:00:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="schedule must be captured strictly before"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_public_draw_status_evidence_after_cutoff() -> None:
    plan = _coupon_plan()
    plan["positions"][6]["status_captured_at_utc"] = "2026-11-08T11:00:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="status.*strictly before ticket close"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_missing_or_duplicate_schedule_positions() -> None:
    plan = _coupon_plan()
    plan["positions"].pop()
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="cover positions 1..14"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )

    plan = _coupon_plan()
    plan["positions"][1]["position"] = 1
    with pytest.raises(TicketOutcomeError, match="duplicate position"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_scheduled_kickoff_at_or_before_cutoff() -> None:
    plan = _coupon_plan()
    plan["positions"][0]["kickoff_at"] = "2026-11-08T10:30:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="kickoff must be after ticket close"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_first_kickoff_not_matching_schedule() -> None:
    plan = _coupon_plan()
    plan["first_kickoff_at"] = "2026-11-08T15:00:00+01:00"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="earliest scheduled fixture kickoff"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_cutoff_after_first_kickoff() -> None:
    plan = _coupon_plan()
    plan["first_kickoff_at"] = "2026-11-08T10:00:00Z"
    for item in plan["positions"]:
        if item["fixture_status"] == "scheduled":
            item["kickoff_at"] = "2026-11-08T10:00:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="earlier than first kickoff"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_preclose_snapshot_rejects_capture_at_or_after_close() -> None:
    snapshot = _preclose_snapshot()
    snapshot["captured_at_utc"] = "2026-11-08T11:00:00Z"
    with pytest.raises(TicketOutcomeError, match="strictly before ticket close"):
        validate_preclose_public_draw_snapshot(
            snapshot,
            draw_date=DRAW_DATE,
            position=7,
            ticket_cutoff_at_utc="2026-11-08T11:00:00Z",
        )


def test_preclose_snapshot_rejects_post_close_ball_counts() -> None:
    snapshot = _preclose_snapshot()
    snapshot["ball_counts"] = {"1": 12, "X": 16, "2": 72}
    with pytest.raises(TicketOutcomeError, match="post-close ball counts"):
        validate_preclose_public_draw_snapshot(
            snapshot,
            draw_date=DRAW_DATE,
            position=7,
            ticket_cutoff_at_utc="2026-11-08T11:00:00Z",
        )


def test_preclose_snapshot_rejects_probability_vector_with_wrong_sum() -> None:
    snapshot = _preclose_snapshot()
    snapshot["probabilities"] = {"1": 0.4, "X": 0.4, "2": 0.4}
    with pytest.raises(TicketOutcomeError, match="sum to one"):
        validate_preclose_public_draw_snapshot(
            snapshot,
            draw_date=DRAW_DATE,
            position=7,
            ticket_cutoff_at_utc="2026-11-08T11:00:00Z",
        )


def test_probability_builder_rejects_cutoff_after_first_kickoff() -> None:
    report = _reconciliation()
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="earlier than first kickoff"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            reconciliation_report=report,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
            ticket_cutoff_at_utc="2026-11-08T11:00:00Z",
            first_kickoff_at="2026-11-08T10:00:00Z",
        )


def test_reconciliation_rejects_boolean_schema_version() -> None:
    report = _reconciliation()
    report["schema_version"] = True
    with pytest.raises(TicketOutcomeError, match="unsupported"):
        outcomes_from_reconciliation(report, DRAW_DATE)


def test_ticket_rejects_boolean_schema_version() -> None:
    report = _reconciliation()
    ticket = _ticket(report)
    ticket["schema_version"] = True
    with pytest.raises(TicketOutcomeError, match="unsupported"):
        score_ticket_record(ticket, report)


def test_preclose_snapshot_rejects_boolean_schema_version() -> None:
    snapshot = _preclose_snapshot()
    snapshot["schema_version"] = True
    with pytest.raises(TicketOutcomeError, match="unsupported"):
        validate_preclose_public_draw_snapshot(
            snapshot,
            draw_date=DRAW_DATE,
            position=7,
            ticket_cutoff_at_utc="2026-11-08T11:00:00Z",
        )
