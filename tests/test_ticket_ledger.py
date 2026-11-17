from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from kini_engine.ticket_ledger import (
    TicketLedger,
    TicketLedgerConflict,
    TicketLedgerError,
)

DRAW_DATE = "2026-11-08"
SELAE_URL = (
    "https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/"
    "la-quiniela-premios-y-ganadores-del-08-de-noviembre-de-2026"
)
HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.fixture(autouse=True)
def _freeze_ledger_clock(monkeypatch):
    monkeypatch.setattr(
        "kini_engine.ticket_ledger._utc_now",
        lambda: "2026-11-08T09:45:00Z",
    )


def _ticket() -> dict[str, object]:
    positions = [
        {
            "position": position,
            "fixture_status": "scheduled",
            "home": f"Home {position}",
            "away": f"Away {position}",
            "kickoff_at": "2026-11-08T14:00:00+01:00",
        }
        for position in range(1, 15)
    ]
    plan = {
        "schema_version": 1,
        "provider": "SELAE",
        "draw_date": DRAW_DATE,
        "schedule_captured_at_utc": "2026-11-08T08:30:00Z",
        "ticket_created_at_utc": "2026-11-08T09:30:00Z",
        "schedule_evidence_url": SELAE_URL,
        "schedule_evidence_sha256": HASH_B,
        "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
        "cutoff_evidence_url": SELAE_URL,
        "cutoff_evidence_sha256": HASH_A,
        "cutoff_evidence_captured_at_utc": "2026-11-08T09:00:00Z",
        "first_kickoff_at": "2026-11-08T14:00:00+01:00",
        "pleno15_home": "Pleno Home",
        "pleno15_away": "Pleno Away",
        "pleno15_kickoff_at": "2026-11-08T15:00:00+01:00",
        "positions": positions,
    }
    return {
        "schema_version": 1,
        "ticket_id": "quiniela-2026-11-08-001",
        "draw_date": DRAW_DATE,
        "ticket_created_at_utc": "2026-11-08T09:30:00Z",
        "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
        "first_kickoff_at": "2026-11-08T14:00:00+01:00",
        "cutoff_evidence_url": SELAE_URL,
        "cutoff_evidence_sha256": HASH_A,
        "cutoff_evidence_captured_at_utc": "2026-11-08T09:00:00Z",
        "schedule_evidence_url": SELAE_URL,
        "schedule_evidence_sha256": HASH_B,
        "schedule_evidence_captured_at_utc": "2026-11-08T08:30:00Z",
        "pleno15_home": "Pleno Home",
        "pleno15_away": "Pleno Away",
        "pleno15_kickoff_at": "2026-11-08T15:00:00+01:00",
        "coupon_plan": plan,
        "probability_vectors": [{"1": 0.5, "X": 0.3, "2": 0.2} for _ in range(14)],
        "probability_sources": [
            {"position": position, "source": "football_model", "model_mode": "ensemble"}
            for position in range(1, 15)
        ],
        "public_draw_positions": [],
        "columns": [["1"] * 14, ["X"] * 14],
        "pleno15_combinations": [{"home_goals": "0", "away_goals": "0"}],
        "budget": 2,
        "cost_eur": 1.5,
    }


def _reconciliation() -> dict[str, object]:
    return {
        "schema_version": 1,
        "success": True,
        "resolved_fixtures": [
            {
                "draw_date": DRAW_DATE,
                "coupon_position": position,
                "home_selae_display_name": f"Home {position}",
                "away_selae_display_name": f"Away {position}",
                "home_goals": 1,
                "away_goals": 0,
                "target_1x2": "1",
                "draw_source_url": SELAE_URL,
                "draw_raw_sha256": HASH_A,
                "training_label_eligible": True,
            }
            for position in range(1, 15)
        ],
        "excluded_fixtures": [],
        "unresolved_fixtures": [],
        "unused_crosswalk_entries": [],
    }


def test_ticket_ledger_persists_valid_record_and_is_idempotent(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    digest = hashlib.sha256(
        json.dumps(
            ticket,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    first = ledger.append_ticket(ticket, expected_sha256=digest)
    second = ledger.append_ticket(ticket, expected_sha256=digest)

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["idempotent_replay"] is True
    assert first["ticket_sha256"] == digest
    stored = ledger.get_ticket_record(str(ticket["ticket_id"]))
    assert stored is not None
    assert stored["ticket_record"] == ticket
    assert stored["ticket_sha256"] == digest


def test_ticket_ledger_rejects_identifier_reuse_with_different_content(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    ledger.append_ticket(ticket)
    changed = {**ticket, "columns": [["2"] * 14, ["X"] * 14]}

    with pytest.raises(TicketLedgerConflict, match="different content"):
        ledger.append_ticket(changed)


def test_ticket_ledger_rejects_expected_digest_mismatch(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")

    with pytest.raises(TicketLedgerError, match="expected digest"):
        ledger.append_ticket(_ticket(), expected_sha256=HASH_B)

    assert ledger.list_ticket_records() == []


def test_ticket_ledger_rejects_updates_and_deletes(tmp_path):
    path = tmp_path / "tickets.sqlite3"
    ledger = TicketLedger(path)
    ticket = _ticket()
    ledger.append_ticket(ticket)

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE tickets SET payload_json = '{}' WHERE ticket_id = ?",
                (ticket["ticket_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM tickets WHERE ticket_id = ?",
                (ticket["ticket_id"],),
            )


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
        "home": "Pleno Home",
        "away": "Pleno Away",
        "home_goals": 2,
        "away_goals": 3,
        "home_category": "2",
        "away_category": "M",
    }


def test_ticket_ledger_scores_and_persists_pleno15_evidence_idempotently(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    ticket["pleno15_combinations"] = [{"home_goals": "2", "away_goals": "M"}]
    ledger.append_ticket(ticket)
    reconciliation_json = json.dumps(
        _reconciliation(), ensure_ascii=False, separators=(",", ":")
    )
    pleno15_json = json.dumps(
        _pleno15_report(), ensure_ascii=False, separators=(",", ":")
    )
    pleno15_digest = hashlib.sha256(pleno15_json.encode("utf-8")).hexdigest()

    first = ledger.score_ticket_json(
        str(ticket["ticket_id"]),
        reconciliation_json,
        pleno15_json=pleno15_json,
    )
    second = ledger.score_ticket_json(
        str(ticket["ticket_id"]),
        reconciliation_json,
        pleno15_json=pleno15_json,
    )

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["idempotent_replay"] is True
    assert first["score"]["pleno15_evaluated"] is True
    assert first["score"]["pleno15_hit"] is True
    assert first["score"]["covered_full_coupon"] is True
    assert first["score"]["pleno15_report_sha256"] == pleno15_digest
    assert first["score"]["score_evidence_sha256"] == first["score_evidence_sha256"]
    listed = ledger.list_ticket_scores(str(ticket["ticket_id"]))
    assert len(listed) == 1
    assert (
        listed[0]["reconciliation_sha256"]
        == hashlib.sha256(reconciliation_json.encode("utf-8")).hexdigest()
    )
    assert listed[0]["score_evidence_sha256"] == first["score_evidence_sha256"]


def test_ticket_ledger_requires_pleno15_digest_when_scoring_report(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    ledger.append_ticket(ticket)
    with pytest.raises(TicketLedgerError, match="pleno15_sha256 is required"):
        ledger.score_ticket(
            str(ticket["ticket_id"]),
            _reconciliation(),
            reconciliation_sha256=HASH_A,
            pleno15_report=_pleno15_report(),
        )


def test_ticket_ledger_scores_and_persists_result_idempotently(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    ledger.append_ticket(ticket)
    reconciliation_json = json.dumps(
        _reconciliation(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    reconciliation_digest = hashlib.sha256(
        reconciliation_json.encode("utf-8")
    ).hexdigest()

    first = ledger.score_ticket_json(
        str(ticket["ticket_id"]),
        reconciliation_json,
    )
    second = ledger.score_ticket_json(
        str(ticket["ticket_id"]),
        reconciliation_json,
    )

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["idempotent_replay"] is True
    assert first["score"]["covered_14"] is True
    assert first["score"]["best_column_hits"] == 14
    assert first["score"]["reconciliation_sha256"] == reconciliation_digest
    assert first["score"]["payout_evaluated"] is False
    assert len(ledger.list_ticket_scores(str(ticket["ticket_id"]))) == 1


def test_ticket_ledger_rejects_scoring_unknown_ticket_or_invalid_digest(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")

    with pytest.raises(TicketLedgerError, match="does not exist"):
        ledger.score_ticket(
            "missing-ticket",
            _reconciliation(),
            reconciliation_sha256=HASH_A,
        )

    ticket = _ticket()
    ledger.append_ticket(ticket)
    with pytest.raises(TicketLedgerError, match="reconciliation_sha256"):
        ledger.score_ticket(
            str(ticket["ticket_id"]),
            _reconciliation(),
            reconciliation_sha256="not-a-digest",
        )


def test_ticket_ledger_lists_by_draw_date_and_enforces_limit(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    first = _ticket()
    ledger.append_ticket(first)
    second = {**_ticket(), "ticket_id": "quiniela-2026-11-08-002"}
    ledger.append_ticket(second)

    assert len(ledger.list_ticket_records(draw_date=DRAW_DATE)) == 2
    assert ledger.list_ticket_records(draw_date="2026-11-09") == []
    assert len(ledger.list_ticket_records(limit=1)) == 1
    with pytest.raises(ValueError, match="limit"):
        ledger.list_ticket_records(limit=True)
    with pytest.raises(ValueError, match="draw_date"):
        ledger.list_ticket_records(draw_date="2026-11-08T00:00:00")


def test_ticket_ledger_score_json_rejects_invalid_or_non_object_payload(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    ledger.append_ticket(ticket)

    with pytest.raises(TicketLedgerError, match="valid UTF-8 JSON"):
        ledger.score_ticket_json(str(ticket["ticket_id"]), "{not-json")

    with pytest.raises(TicketLedgerError, match="root must be an object"):
        ledger.score_ticket_json(str(ticket["ticket_id"]), "[]")

    assert ledger.list_ticket_scores(str(ticket["ticket_id"])) == []


def test_ticket_ledger_rejects_append_at_or_after_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kini_engine.ticket_ledger._utc_now",
        lambda: "2026-11-08T11:00:00Z",
    )
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")

    with pytest.raises(TicketLedgerError, match="before ticket cutoff"):
        ledger.append_ticket(_ticket())

    assert ledger.list_ticket_records() == []


def test_ticket_ledger_rejects_append_before_declared_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kini_engine.ticket_ledger._utc_now",
        lambda: "2026-11-08T09:29:59Z",
    )
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")

    with pytest.raises(TicketLedgerError, match="must not precede ticket creation"):
        ledger.append_ticket(_ticket())

    assert ledger.list_ticket_records() == []


def test_ticket_ledger_idempotent_replay_after_cutoff_keeps_original_timestamp(
    tmp_path,
    monkeypatch,
):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    monkeypatch.setattr(
        "kini_engine.ticket_ledger._utc_now",
        lambda: "2026-11-08T10:59:59Z",
    )
    first = ledger.append_ticket(ticket)

    monkeypatch.setattr(
        "kini_engine.ticket_ledger._utc_now",
        lambda: "2026-11-08T11:00:00Z",
    )
    second = ledger.append_ticket(ticket)

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["idempotent_replay"] is True
    assert second["recorded_at_utc"] == first["recorded_at_utc"]


def test_ticket_ledger_rejects_legacy_late_record_on_read(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    payload_json = json.dumps(
        ticket,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            """
            INSERT INTO tickets (
                ticket_id, draw_date, ticket_created_at_utc,
                ticket_cutoff_at_utc, first_kickoff_at, payload_json,
                payload_sha256, recorded_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket["ticket_id"],
                ticket["draw_date"],
                ticket["ticket_created_at_utc"],
                ticket["ticket_cutoff_at_utc"],
                ticket["first_kickoff_at"],
                payload_json,
                payload_sha256,
                "2026-11-08T11:00:00Z",
            ),
        )

    with pytest.raises(TicketLedgerError, match="before ticket cutoff"):
        ledger.get_ticket_record(str(ticket["ticket_id"]))


def _official_prize_snapshot_for_ledger_test(
    ticket: dict[str, object],
    pleno_report: dict[str, object],
) -> dict[str, object]:
    pdf_url = (
        "https://www.loteriasyapuestas.es/f/loterias/documentos/"
        "Quiniela/Notas%20de%20prensa/test.pdf"
    )
    return {
        "schema_version": 1,
        "source": "SELAE",
        "draw_date": DRAW_DATE,
        "source_url": SELAE_URL,
        "verified_at": DRAW_DATE,
        "verification_method": (
            "Synthetic ledger unit-test snapshot; no real SELAE result is asserted."
        ),
        "snapshot_type": "normalized_json_extract_not_raw_html",
        "supporting_sources": [
            {"role": "official_selae_result_page", "url": SELAE_URL},
            {"role": "official_selae_press_release_pdf", "url": pdf_url},
        ],
        "fixtures": [
            {
                "number": position,
                "home": f"Home {position}",
                "away": f"Away {position}",
                "home_goals": 1,
                "away_goals": 0,
                "result": "1",
            }
            for position in range(1, 15)
        ],
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
                    "status": "awarded",
                }
                for name, winners, prize in [
                    ("pleno_al_15", 1, 100.0),
                    ("14", 2, 20.0),
                    ("13", 5, 5.0),
                    ("12", 10, 2.0),
                    ("11", 100, 1.0),
                    ("10", 200, 0.0),
                ]
            ],
        },
    }


def test_ticket_ledger_scores_official_prize_snapshot_idempotently(tmp_path):
    ledger = TicketLedger(tmp_path / "tickets.sqlite3")
    ticket = _ticket()
    ticket["pleno15_combinations"] = [{"home_goals": "2", "away_goals": "M"}]
    ledger.append_ticket(ticket)
    reconciliation_json = json.dumps(
        _reconciliation(), ensure_ascii=False, separators=(",", ":")
    )
    pleno15_json = json.dumps(
        _pleno15_report(), ensure_ascii=False, separators=(",", ":")
    )
    snapshot = _official_prize_snapshot_for_ledger_test(ticket, _pleno15_report())
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    expected_snapshot_digest = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

    first = ledger.score_ticket_json(
        str(ticket["ticket_id"]),
        reconciliation_json,
        pleno15_json=pleno15_json,
        official_result_snapshot_json=snapshot_json,
    )
    second = ledger.score_ticket_json(
        str(ticket["ticket_id"]),
        reconciliation_json,
        pleno15_json=pleno15_json,
        official_result_snapshot_json=snapshot_json,
    )

    assert first["inserted"] is True
    assert second["idempotent_replay"] is True
    assert first["score"]["official_result_snapshot_sha256"] == (
        expected_snapshot_digest
    )
    assert first["score"]["prize_tier_counts"]["pleno_al_15"] == 1
    assert first["score"]["conditional_published_prize_reference_eur"] == "120.00"
    assert first["score"]["payout_evaluated"] is False
    assert len(ledger.list_ticket_scores(str(ticket["ticket_id"]))) == 1
