from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .ticket_outcomes import (
    score_ticket_record,
    validate_ticket_record,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class TicketLedgerError(ValueError):
    """Raised when an immutable ticket-ledger operation cannot be completed."""


class TicketLedgerConflict(TicketLedgerError):
    """Raised when an existing immutable identifier is reused for different data."""


def _canonical_json(value: dict[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise TicketLedgerError("ledger records must be finite JSON objects") from exc


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise TicketLedgerError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TicketLedger:
    """SQLite-backed append-only ledger for generated Quiniela tickets and scores.

    Ticket and score rows are immutable. Replaying the same identifier and bytes is
    idempotent; reusing an identifier for different bytes is rejected.
    """

    def __init__(self, path: str | Path = "data/kini-tickets.sqlite3") -> None:
        if str(path) == ":memory:":
            raise ValueError("ticket ledger requires a durable filesystem path")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    draw_date TEXT NOT NULL,
                    ticket_created_at_utc TEXT NOT NULL,
                    ticket_cutoff_at_utc TEXT NOT NULL,
                    first_kickoff_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
                    recorded_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ticket_scores (
                    ticket_id TEXT NOT NULL,
                    reconciliation_sha256 TEXT NOT NULL
                        CHECK(length(reconciliation_sha256) = 64),
                    score_json TEXT NOT NULL,
                    score_sha256 TEXT NOT NULL CHECK(length(score_sha256) = 64),
                    recorded_at_utc TEXT NOT NULL,
                    PRIMARY KEY(ticket_id, reconciliation_sha256),
                    FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id)
                );

                CREATE TRIGGER IF NOT EXISTS tickets_no_update
                BEFORE UPDATE ON tickets
                BEGIN
                    SELECT RAISE(ABORT, 'ticket ledger is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS tickets_no_delete
                BEFORE DELETE ON tickets
                BEGIN
                    SELECT RAISE(ABORT, 'ticket ledger is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS ticket_scores_no_update
                BEFORE UPDATE ON ticket_scores
                BEGIN
                    SELECT RAISE(ABORT, 'ticket score ledger is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS ticket_scores_no_delete
                BEFORE DELETE ON ticket_scores
                BEGIN
                    SELECT RAISE(ABORT, 'ticket score ledger is append-only');
                END;
                """
            )

    def append_ticket(
        self,
        ticket: dict[str, Any],
        *,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Persist one validated ticket without overwriting any existing record."""
        validated = validate_ticket_record(ticket)
        payload_json = _canonical_json(ticket)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if expected_sha256 is not None:
            expected = _sha256(expected_sha256, "expected_sha256")
            if expected != payload_sha256:
                raise TicketLedgerError(
                    "ticket SHA-256 does not match the supplied expected digest"
                )

        ticket_id = validated["ticket_id"]
        recorded_at = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT payload_sha256, recorded_at_utc
                FROM tickets WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != payload_sha256:
                    connection.rollback()
                    raise TicketLedgerConflict(
                        f"ticket_id {ticket_id!r} already exists with different content"
                    )
                connection.commit()
                return {
                    "ticket_id": ticket_id,
                    "ticket_sha256": payload_sha256,
                    "recorded_at_utc": existing["recorded_at_utc"],
                    "inserted": False,
                    "idempotent_replay": True,
                }

            connection.execute(
                """
                INSERT INTO tickets (
                    ticket_id, draw_date, ticket_created_at_utc,
                    ticket_cutoff_at_utc, first_kickoff_at, payload_json,
                    payload_sha256, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    validated["draw_date"],
                    validated["ticket_created_at_utc"]
                    .isoformat()
                    .replace("+00:00", "Z"),
                    validated["ticket_cutoff_at_utc"]
                    .isoformat()
                    .replace("+00:00", "Z"),
                    validated["first_kickoff_at"].isoformat(),
                    payload_json,
                    payload_sha256,
                    recorded_at,
                ),
            )
            connection.commit()

        return {
            "ticket_id": ticket_id,
            "ticket_sha256": payload_sha256,
            "recorded_at_utc": recorded_at,
            "inserted": True,
            "idempotent_replay": False,
        }

    def get_ticket_record(self, ticket_id: str) -> dict[str, Any] | None:
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            raise ValueError("ticket_id must be a non-empty string")
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT ticket_id, payload_json, payload_sha256, recorded_at_utc
                FROM tickets WHERE ticket_id = ?
                """,
                (ticket_id.strip(),),
            ).fetchone()
        if row is None:
            return None

        payload_json = row["payload_json"]
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if payload_sha256 != row["payload_sha256"]:
            raise TicketLedgerError(
                f"stored ticket {ticket_id!r} failed its SHA-256 integrity check"
            )
        try:
            ticket = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise TicketLedgerError(
                f"stored ticket {ticket_id!r} is not valid JSON"
            ) from exc
        if not isinstance(ticket, dict) or ticket.get("ticket_id") != row["ticket_id"]:
            raise TicketLedgerError(
                f"stored ticket {ticket_id!r} has an inconsistent identity"
            )
        validate_ticket_record(ticket)
        return {
            "ticket_record": ticket,
            "ticket_sha256": payload_sha256,
            "recorded_at_utc": row["recorded_at_utc"],
        }

    def list_ticket_records(
        self,
        *,
        draw_date: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise ValueError("limit must be an integer from 1 to 1000")
        if draw_date is not None:
            if not isinstance(draw_date, str):
                raise TypeError("draw_date must be an ISO date string")
            try:
                normalized_date = date.fromisoformat(draw_date).isoformat()
            except ValueError as exc:
                raise ValueError("draw_date must be an ISO date") from exc
            if normalized_date != draw_date:
                raise ValueError("draw_date must use canonical YYYY-MM-DD format")
        else:
            normalized_date = None

        with closing(self._connect()) as connection:
            if normalized_date is None:
                rows = connection.execute(
                    """
                    SELECT ticket_id FROM tickets
                    ORDER BY recorded_at_utc DESC, ticket_id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT ticket_id FROM tickets WHERE draw_date = ?
                    ORDER BY recorded_at_utc DESC, ticket_id DESC LIMIT ?
                    """,
                    (normalized_date, limit),
                ).fetchall()

        records = []
        for row in rows:
            record = self.get_ticket_record(row["ticket_id"])
            if record is None:
                raise TicketLedgerError(
                    "ticket disappeared while listing ledger records"
                )
            records.append(record)
        return records

    def score_ticket(
        self,
        ticket_id: str,
        reconciliation_report: dict[str, Any],
        *,
        reconciliation_sha256: str,
    ) -> dict[str, Any]:
        """Score a stored ticket and persist the result against exact source bytes."""
        reconciliation_digest = _sha256(
            reconciliation_sha256, "reconciliation_sha256"
        )
        stored = self.get_ticket_record(ticket_id)
        if stored is None:
            raise TicketLedgerError(f"ticket {ticket_id!r} does not exist")
        score = score_ticket_record(
            stored["ticket_record"],
            reconciliation_report,
            ticket_sha256=stored["ticket_sha256"],
            reconciliation_sha256=reconciliation_digest,
        )
        score_json = _canonical_json(score)
        score_sha256 = hashlib.sha256(score_json.encode("utf-8")).hexdigest()
        recorded_at = _utc_now()

        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT score_sha256, recorded_at_utc FROM ticket_scores
                WHERE ticket_id = ? AND reconciliation_sha256 = ?
                """,
                (ticket_id, reconciliation_digest),
            ).fetchone()
            if existing is not None:
                if existing["score_sha256"] != score_sha256:
                    connection.rollback()
                    raise TicketLedgerConflict(
                        "the same ticket/reconciliation pair produced different scores"
                    )
                connection.commit()
                return {
                    "score": score,
                    "score_sha256": score_sha256,
                    "recorded_at_utc": existing["recorded_at_utc"],
                    "inserted": False,
                    "idempotent_replay": True,
                }

            connection.execute(
                """
                INSERT INTO ticket_scores (
                    ticket_id, reconciliation_sha256, score_json,
                    score_sha256, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    reconciliation_digest,
                    score_json,
                    score_sha256,
                    recorded_at,
                ),
            )
            connection.commit()

        return {
            "score": score,
            "score_sha256": score_sha256,
            "recorded_at_utc": recorded_at,
            "inserted": True,
            "idempotent_replay": False,
        }

    def score_ticket_json(
        self,
        ticket_id: str,
        reconciliation_json: str | bytes,
    ) -> dict[str, Any]:
        """Hash exact reconciliation JSON bytes before scoring a stored ticket."""
        if isinstance(reconciliation_json, str):
            raw = reconciliation_json.encode("utf-8")
        elif isinstance(reconciliation_json, bytes):
            raw = reconciliation_json
        else:
            raise TypeError("reconciliation_json must be UTF-8 text or bytes")
        try:
            report = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TicketLedgerError(
                "reconciliation JSON must contain a valid UTF-8 JSON document"
            ) from exc
        if not isinstance(report, dict):
            raise TicketLedgerError("reconciliation JSON root must be an object")
        digest = hashlib.sha256(raw).hexdigest()
        return self.score_ticket(
            ticket_id,
            report,
            reconciliation_sha256=digest,
        )

    def list_ticket_scores(self, ticket_id: str) -> list[dict[str, Any]]:
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            raise ValueError("ticket_id must be a non-empty string")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT reconciliation_sha256, score_json, score_sha256, recorded_at_utc
                FROM ticket_scores WHERE ticket_id = ?
                ORDER BY recorded_at_utc, reconciliation_sha256
                """,
                (ticket_id.strip(),),
            ).fetchall()

        results = []
        for row in rows:
            payload = row["score_json"]
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if digest != row["score_sha256"]:
                raise TicketLedgerError(
                    f"stored score for ticket {ticket_id!r} failed its "
                    "SHA-256 integrity check"
                )
            try:
                score = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise TicketLedgerError(
                    "stored ticket score is not valid JSON"
                ) from exc
            results.append(
                {
                    "score": score,
                    "score_sha256": digest,
                    "reconciliation_sha256": row["reconciliation_sha256"],
                    "recorded_at_utc": row["recorded_at_utc"],
                }
            )
        return results
