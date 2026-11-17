from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kini_engine.ticket_outcomes import (
    TicketOutcomeError,
    build_ticket_probability_vectors,
    outcomes_from_reconciliation,
    score_ticket_record,
    validate_pleno15_report,
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
    plan = _coupon_plan()
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    vectors = build_ticket_probability_vectors(
        draw_date=DRAW_DATE,
        coupon_plan=plan,
        model_probabilities_by_position=model_probabilities,
        public_draw_snapshots={7: _preclose_snapshot()},
    )
    sources = []
    for source in vectors["probability_sources"]:
        if source["source"] == "football_model":
            sources.append({**source, "model_mode": "ensemble"})
        else:
            sources.append(source)
    return {
        "schema_version": 1,
        "ticket_id": "test-ticket-2026-11-08",
        "draw_date": DRAW_DATE,
        "ticket_created_at_utc": vectors["ticket_created_at_utc"],
        "ticket_cutoff_at_utc": vectors["ticket_cutoff_at_utc"],
        "first_kickoff_at": vectors["first_kickoff_at"],
        "cutoff_evidence_url": plan["cutoff_evidence_url"],
        "cutoff_evidence_sha256": plan["cutoff_evidence_sha256"],
        "cutoff_evidence_captured_at_utc": plan["cutoff_evidence_captured_at_utc"],
        "schedule_evidence_url": plan["schedule_evidence_url"],
        "schedule_evidence_sha256": plan["schedule_evidence_sha256"],
        "schedule_evidence_captured_at_utc": plan["schedule_captured_at_utc"],
        "pleno15_home": plan["pleno15_home"],
        "pleno15_away": plan["pleno15_away"],
        "pleno15_kickoff_at": vectors["pleno15_kickoff_at"],
        "coupon_plan": deepcopy(plan),
        "probability_vectors": vectors["probabilities"],
        "probability_sources": sources,
        "public_draw_positions": vectors["public_draw_positions"],
        "columns": [actual, second],
        "pleno15_combinations": [{"home_goals": "0", "away_goals": "0"}],
        "budget": 8,
        "cost_eur": 1.5,
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
        "ticket_created_at_utc": "2026-11-08T10:45:00Z",
        "schedule_evidence_url": SELAE_URL,
        "schedule_evidence_sha256": HASH_A,
        "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
        "cutoff_evidence_url": SELAE_URL,
        "cutoff_evidence_sha256": HASH_C,
        "cutoff_evidence_captured_at_utc": "2026-11-08T09:15:00Z",
        "first_kickoff_at": "2026-11-08T14:00:00+01:00",
        "pleno15_home": "Pleno Home (M)",
        "pleno15_away": "Pleno Away (M)",
        "pleno15_kickoff_at": "2026-11-08T15:00:00+01:00",
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


def _pleno15_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "SELAE",
        "draw_date": DRAW_DATE,
        "source_url": SELAE_URL,
        "source_sha256": HASH_A,
        "evidence_type": "normalized_official_extract",
        "verified_at_utc": "2026-11-08T16:00:00Z",
        "verification_method": "Synthetic unit-test fixture; no real SELAE result is asserted.",
        "home": "Pleno Home (M)",
        "away": "Pleno Away (M)",
        "home_goals": 2,
        "away_goals": 3,
        "home_category": "2",
        "away_category": "M",
    }


def test_pleno15_validator_accepts_committed_official_selae_extract() -> None:
    snapshot_path = (
        Path(__file__).parents[1]
        / "kini_engine"
        / "data"
        / "selae_official_coupon_results"
        / "2020-2021-21.json"
    )
    raw = snapshot_path.read_bytes()
    snapshot = json.loads(raw)
    pleno = snapshot["pleno"]
    report = {
        "schema_version": 1,
        "provider": "SELAE",
        "draw_date": snapshot["draw_date"],
        "source_url": snapshot["source_url"],
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_type": "normalized_official_extract",
        # Test-only timestamp; the committed historical snapshot stores a date,
        # not a trusted time-of-day attestation.
        "verified_at_utc": "2026-11-17T12:00:00Z",
        "verification_method": "Unit test of the committed normalized SELAE extract.",
        "home": pleno["home"],
        "away": pleno["away"],
        "home_goals": pleno["home_goals"],
        "away_goals": pleno["away_goals"],
        "home_category": pleno["home_category"],
        "away_category": pleno["away_category"],
    }

    validated = validate_pleno15_report(
        report,
        draw_date=snapshot["draw_date"],
        expected_home=pleno["home"],
        expected_away=pleno["away"],
        # Only a lower bound for temporal validation in this unit test.
        kickoff_at=datetime(2020, 12, 13, tzinfo=UTC),
    )

    assert validated["home_goals"] == 4
    assert validated["away_goals"] == 0
    assert validated["home_category"] == "M"
    assert validated["away_category"] == "0"
    assert validated["source_sha256"] == hashlib.sha256(raw).hexdigest()


def _pleno15_press_release_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "SELAE",
        "draw_date": DRAW_DATE,
        "source_url": "https://www.loteriasyapuestas.es/f/loterias/documentos/nota.pdf",
        "source_sha256": HASH_A,
        "evidence_type": "official_press_release_pdf",
        "verified_at_utc": "2026-11-08T16:00:00Z",
        "verification_method": "Synthetic unit-test PDF vector; no live result asserted.",
        "home_category": "2",
        "away_category": "M",
    }


def test_ticket_scoring_evaluates_pleno15_from_official_pdf_vector() -> None:
    report = _reconciliation()
    ticket = _ticket(report)
    ticket["pleno15_combinations"] = [{"home_goals": "2", "away_goals": "M"}]

    result = score_ticket_record(
        ticket,
        report,
        pleno15_report=_pleno15_press_release_report(),
        pleno15_report_sha256=HASH_B,
    )

    assert result["pleno15_evaluated"] is True
    assert result["pleno15_hit"] is True
    assert result["covered_full_coupon"] is True
    assert result["pleno15_actual"] == {
        "home_category": "2",
        "away_category": "M",
    }
    assert result["pleno15_outcome_provenance"]["team_identity_source"] == (
        "ticket_plan_draw_date_binding"
    )


def test_ticket_scoring_evaluates_official_pleno15_categories() -> None:
    report = _reconciliation()
    ticket = _ticket(report)
    ticket["pleno15_combinations"] = [{"home_goals": "2", "away_goals": "M"}]

    result = score_ticket_record(
        ticket,
        report,
        pleno15_report=_pleno15_report(),
        pleno15_report_sha256=HASH_B,
    )

    assert result["covered_14"] is True
    assert result["pleno15_evaluated"] is True
    assert result["pleno15_actual"] == {
        "home_goals": 2,
        "away_goals": 3,
        "home_category": "2",
        "away_category": "M",
    }
    assert result["pleno15_hit"] is True
    assert result["covered_full_coupon"] is True
    assert result["pleno15_report_sha256"] == HASH_B
    assert result["pleno15_outcome_provenance"]["evidence_type"] == (
        "normalized_official_extract"
    )


def test_ticket_scoring_reports_pleno15_miss_separately_from_14_coverage() -> None:
    report = _reconciliation()
    result = score_ticket_record(
        _ticket(report),
        report,
        pleno15_report=_pleno15_report(),
    )

    assert result["covered_14"] is True
    assert result["pleno15_evaluated"] is True
    assert result["pleno15_hit"] is False
    assert result["covered_full_coupon"] is False


def test_ticket_scoring_marks_pleno15_unassessed_without_official_evidence() -> None:
    report = _reconciliation()
    result = score_ticket_record(_ticket(report), report)

    assert result["covered_14"] is True
    assert "pleno15_evaluated" not in result
    assert "pleno15_actual" not in result
    assert "pleno15_hit" not in result
    assert "covered_full_coupon" not in result


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_url", "https://example.com/result", "official SELAE host"),
        ("draw_date", "2026-11-09", "draw date mismatch"),
        ("home", "Different Team", "team identity"),
        ("home_category", "1", "categories conflict"),
        ("home_category", ["2"], "categories must be 0, 1, 2 or M"),
        ("verified_at_utc", "2026-11-08T13:00:00Z", "must not precede"),
        ("evidence_type", "unverified_summary", "evidence_type"),
    ],
)
def test_ticket_scoring_rejects_invalid_pleno15_evidence(
    field: str, value: object, message: str
) -> None:
    report = _reconciliation()
    pleno = _pleno15_report()
    pleno[field] = value
    with pytest.raises(TicketOutcomeError, match=message):
        score_ticket_record(_ticket(report), report, pleno15_report=pleno)


def test_ticket_scoring_rejects_press_release_report_without_pdf_url() -> None:
    report = _reconciliation()
    pleno = _pleno15_press_release_report()
    pleno["source_url"] = "https://www.loteriasyapuestas.es/es/la-quiniela"

    with pytest.raises(TicketOutcomeError, match="official PDF"):
        score_ticket_record(_ticket(report), report, pleno15_report=pleno)


def test_ticket_scoring_rejects_pleno15_report_digest_without_report() -> None:
    report = _reconciliation()
    with pytest.raises(TicketOutcomeError, match="requires a Pleno"):
        score_ticket_record(
            _ticket(report),
            report,
            pleno15_report_sha256=HASH_B,
        )


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
    assert result["cutoff_evidence"]["source_sha256"] == HASH_C
    assert result["pleno15_home"] == "Pleno Home (M)"
    assert result["pleno15_away"] == "Pleno Away (M)"
    assert result["pleno15_kickoff_at"] == "2026-11-08T15:00:00+01:00"
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


def test_probability_builder_rejects_model_probability_for_public_draw_position() -> (
    None
):
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
    with pytest.raises(
        TicketOutcomeError, match="schedule must be captured strictly before"
    ):
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
    with pytest.raises(
        TicketOutcomeError, match="status.*strictly before ticket creation"
    ):
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
    with pytest.raises(TicketOutcomeError, match="strictly before ticket creation"):
        validate_preclose_public_draw_snapshot(
            snapshot,
            draw_date=DRAW_DATE,
            position=7,
            ticket_created_at_utc="2026-11-08T10:45:00Z",
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
            ticket_created_at_utc="2026-11-08T10:45:00Z",
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
            ticket_created_at_utc="2026-11-08T10:45:00Z",
            ticket_cutoff_at_utc="2026-11-08T11:00:00Z",
        )


def test_probability_builder_rejects_schedule_captured_after_ticket_creation() -> None:
    plan = _coupon_plan()
    plan["schedule_captured_at_utc"] = "2026-11-08T10:50:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="schedule.*before ticket creation"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_probability_builder_rejects_public_draw_status_captured_after_ticket_creation() -> (
    None
):
    plan = _coupon_plan()
    plan["positions"][6]["status_captured_at_utc"] = "2026-11-08T10:50:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }
    with pytest.raises(TicketOutcomeError, match="status.*before ticket creation"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_preclose_snapshot_rejects_capture_after_ticket_creation() -> None:
    snapshot = _preclose_snapshot()
    snapshot["captured_at_utc"] = "2026-11-08T10:50:00Z"
    with pytest.raises(TicketOutcomeError, match="strictly before ticket creation"):
        validate_preclose_public_draw_snapshot(
            snapshot,
            draw_date=DRAW_DATE,
            position=7,
            ticket_created_at_utc="2026-11-08T10:45:00Z",
            ticket_cutoff_at_utc="2026-11-08T11:00:00Z",
        )


def test_coupon_plan_uses_pleno15_kickoff_for_first_kickoff() -> None:
    plan = _coupon_plan()
    plan["pleno15_kickoff_at"] = "2026-11-08T13:00:00+01:00"
    plan["first_kickoff_at"] = "2026-11-08T13:00:00+01:00"
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

    assert result["first_kickoff_at"] == "2026-11-08T13:00:00+01:00"
    assert result["pleno15_kickoff_at"] == "2026-11-08T13:00:00+01:00"


def test_coupon_plan_rejects_pleno15_kickoff_at_or_before_ticket_cutoff() -> None:
    plan = _coupon_plan()
    plan["pleno15_kickoff_at"] = "2026-11-08T10:30:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }

    with pytest.raises(TicketOutcomeError, match="Pleno al 15 kickoff must be after"):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_coupon_plan_rejects_first_kickoff_that_ignores_earlier_pleno15() -> None:
    plan = _coupon_plan()
    plan["pleno15_kickoff_at"] = "2026-11-08T13:00:00+01:00"
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


def test_coupon_plan_rejects_cutoff_evidence_captured_after_ticket_creation() -> None:
    plan = _coupon_plan()
    plan["cutoff_evidence_captured_at_utc"] = "2026-11-08T10:45:00Z"
    model_probabilities = {
        position: {"1": 0.5, "X": 0.3, "2": 0.2}
        for position in range(1, 15)
        if position != 7
    }

    with pytest.raises(
        TicketOutcomeError,
        match="cutoff evidence must be captured strictly before ticket creation",
    ):
        build_ticket_probability_vectors(
            draw_date=DRAW_DATE,
            coupon_plan=plan,
            model_probabilities_by_position=model_probabilities,
            public_draw_snapshots={7: _preclose_snapshot()},
        )


def test_ticket_record_rejects_missing_probability_vectors() -> None:
    ticket = _ticket(_reconciliation())
    ticket["probability_vectors"].pop()
    with pytest.raises(TicketOutcomeError, match="14 1/X/2 probability vectors"):
        score_ticket_record(ticket, _reconciliation())


def test_ticket_record_rejects_probability_source_that_conflicts_with_coupon_plan() -> (
    None
):
    ticket = _ticket(_reconciliation())
    ticket["probability_sources"][6] = {
        "position": 7,
        "source": "football_model",
        "model_mode": "ensemble",
    }
    with pytest.raises(TicketOutcomeError, match="pre-close public-draw provenance"):
        score_ticket_record(ticket, _reconciliation())


def test_ticket_record_rejects_pleno_identity_mismatch() -> None:
    ticket = _ticket(_reconciliation())
    ticket["pleno15_home"] = "Different team"
    with pytest.raises(TicketOutcomeError, match="Pleno al 15 identity/kickoff"):
        score_ticket_record(ticket, _reconciliation())


def test_ticket_record_rejects_invalid_pleno_category_pair() -> None:
    ticket = _ticket(_reconciliation())
    ticket["pleno15_combinations"][0]["home_goals"] = "3"
    with pytest.raises(TicketOutcomeError, match="invalid categories"):
        score_ticket_record(ticket, _reconciliation())


def test_ticket_record_rejects_budget_or_cost_inconsistency() -> None:
    ticket = _ticket(_reconciliation())
    ticket["budget"] = 1
    with pytest.raises(TicketOutcomeError, match="exceeds its declared budget"):
        score_ticket_record(ticket, _reconciliation())

    ticket = _ticket(_reconciliation())
    ticket["cost_eur"] = 2.0
    with pytest.raises(TicketOutcomeError, match="cost does not match"):
        score_ticket_record(ticket, _reconciliation())


def _official_prize_snapshot_for_test(
    ticket: dict[str, object],
    reconciliation: dict[str, object],
    pleno_report: dict[str, object],
) -> dict[str, object]:
    outcomes = outcomes_from_reconciliation(reconciliation, DRAW_DATE)
    positions = ticket["coupon_plan"]["positions"]
    fixtures = []
    for position, outcome, plan_fixture in zip(
        range(1, 15), outcomes, positions, strict=True
    ):
        sign = outcome["sign"]
        home_goals, away_goals = (
            (1, 0) if sign == "1" else (0, 1) if sign == "2" else (0, 0)
        )
        fixtures.append(
            {
                "number": position,
                "home": plan_fixture["home"],
                "away": plan_fixture["away"],
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result": sign,
            }
        )
    pdf_url = (
        "https://www.loteriasyapuestas.es/f/loterias/documentos/"
        "Quiniela/Notas%20de%20prensa/test.pdf"
    )
    categories = [
        ("pleno_al_15", 1, 100.0, "awarded"),
        ("14", 2, 20.0, "awarded"),
        ("13", 5, 5.0, "awarded"),
        ("12", 10, 2.0, "awarded"),
        ("11", 100, 1.0, "awarded"),
        ("10", 200, 0.0, "awarded"),
    ]
    return {
        "schema_version": 1,
        "source": "SELAE",
        "draw_date": DRAW_DATE,
        "source_url": SELAE_URL,
        "verified_at": DRAW_DATE,
        "verification_method": (
            "Synthetic unit-test snapshot; no real SELAE result is asserted."
        ),
        "snapshot_type": "normalized_json_extract_not_raw_html",
        "supporting_sources": [
            {"role": "official_selae_result_page", "url": SELAE_URL},
            {"role": "official_selae_press_release_pdf", "url": pdf_url},
        ],
        "fixtures": fixtures,
        "pleno": {
            "number": 15,
            "home": ticket["pleno15_home"],
            "away": ticket["pleno15_away"],
            "home_goals": pleno_report["home_goals"],
            "away_goals": pleno_report["away_goals"],
            "home_category": pleno_report["home_category"],
            "away_category": pleno_report["away_category"],
        },
        "prize_distribution": {
            "source_type": (
                "official_selae_press_release_pdf_transcribed_to_normalized_extract"
            ),
            "source_url": pdf_url,
            "revenue_eur": 1000.0,
            "categories": [
                {
                    "category": name,
                    "winner_count": winners,
                    "unit_prize_eur": prize,
                    "status": status,
                }
                for name, winners, prize, status in categories
            ],
        },
    }


def test_official_prize_scoring_expands_columns_by_pleno_pairs() -> None:
    reconciliation = _reconciliation()
    ticket = _ticket(reconciliation)
    pleno_report = _pleno15_report()
    ticket["pleno15_combinations"] = [
        {"home_goals": "2", "away_goals": "M"},
        {"home_goals": "0", "away_goals": "0"},
    ]
    ticket["cost_eur"] = 3.0
    snapshot = _official_prize_snapshot_for_test(
        ticket, reconciliation, pleno_report
    )
    snapshot_raw = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":")
    ).encode()
    snapshot_digest = hashlib.sha256(snapshot_raw).hexdigest()

    result = score_ticket_record(
        ticket,
        reconciliation,
        pleno15_report=pleno_report,
        pleno15_report_sha256=HASH_B,
        official_result_snapshot=snapshot,
        official_result_snapshot_sha256=snapshot_digest,
    )

    assert result["prize_tiers_evaluated"] is True
    assert result["prize_tier_counts"] == {
        "pleno_al_15": 1,
        "14": 2,
        "13": 0,
        "12": 0,
        "11": 0,
        "10": 0,
    }
    assert result["conditional_published_prize_reference_eur"] == "140.00"
    assert result["conditional_prize_reference_complete"] is True
    assert result["official_result_snapshot_sha256"] == snapshot_digest
    assert result["payout_evaluated"] is False
    assert result["profitability_evaluated"] is False


def test_official_prize_scoring_does_not_price_a_rollover_tier() -> None:
    reconciliation = _reconciliation()
    ticket = _ticket(reconciliation)
    pleno_report = _pleno15_report()
    ticket["pleno15_combinations"] = [
        {"home_goals": "2", "away_goals": "M"}
    ]
    snapshot = _official_prize_snapshot_for_test(
        ticket, reconciliation, pleno_report
    )
    pleno_tier = next(
        item
        for item in snapshot["prize_distribution"]["categories"]
        if item["category"] == "pleno_al_15"
    )
    pleno_tier.update(
        {"winner_count": 0, "unit_prize_eur": None, "status": "rollover"}
    )
    snapshot_raw = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":")
    ).encode()

    result = score_ticket_record(
        ticket,
        reconciliation,
        pleno15_report=pleno_report,
        pleno15_report_sha256=HASH_B,
        official_result_snapshot=snapshot,
        official_result_snapshot_sha256=hashlib.sha256(snapshot_raw).hexdigest(),
    )

    assert result["prize_tier_counts"]["pleno_al_15"] == 1
    assert result["conditional_prize_reference_complete"] is False
    assert result["conditional_published_prize_reference_eur"] is None
    assert result["payout_evaluated"] is False


def test_official_prize_scoring_rejects_snapshot_result_conflict() -> None:
    reconciliation = _reconciliation()
    ticket = _ticket(reconciliation)
    pleno_report = _pleno15_report()
    snapshot = _official_prize_snapshot_for_test(
        ticket, reconciliation, pleno_report
    )
    snapshot["fixtures"][0]["result"] = "X"
    snapshot_raw = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":")
    ).encode()

    with pytest.raises(TicketOutcomeError, match="conflicts with its score"):
        score_ticket_record(
            ticket,
            reconciliation,
            pleno15_report=pleno_report,
            pleno15_report_sha256=HASH_B,
            official_result_snapshot=snapshot,
            official_result_snapshot_sha256=hashlib.sha256(snapshot_raw).hexdigest(),
        )
