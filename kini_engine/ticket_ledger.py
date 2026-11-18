from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
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


def _validate_recorded_at(value: object, validated: dict[str, Any]) -> str:
    """Validate the host-clock append time against the ticket admission window."""
    if not isinstance(value, str) or not value.strip():
        raise TicketLedgerError(
            "recorded_at_utc must be a non-empty ISO-8601 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise TicketLedgerError(
            "recorded_at_utc must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise TicketLedgerError("recorded_at_utc must be expressed in UTC")

    recorded_at = parsed.astimezone(UTC)
    if recorded_at < validated["ticket_created_at_utc"]:
        raise TicketLedgerError("ticket ledger append must not precede ticket creation")
    if recorded_at >= validated["ticket_cutoff_at_utc"]:
        raise TicketLedgerError("ticket ledger append must occur before ticket cutoff")
    return recorded_at.isoformat().replace("+00:00", "Z")


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

    @staticmethod
    def _verify_connection(connection: sqlite3.Connection) -> dict[str, int]:
        """Verify SQLite structure and every stored ticket/score payload."""
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        if (
            len(integrity_rows) != 1
            or str(integrity_rows[0][0]).lower() != "ok"
        ):
            details = "; ".join(str(row[0]) for row in integrity_rows[:5])
            raise TicketLedgerError(
                f"SQLite integrity check failed: {details or 'no result returned'}"
            )

        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_errors:
            raise TicketLedgerError(
                f"SQLite foreign-key check failed: {len(foreign_key_errors)} violation(s)"
            )

        ticket_hashes: dict[str, str] = {}
        ticket_count = 0
        ticket_rows = connection.execute(
            """
            SELECT ticket_id, payload_json, payload_sha256, recorded_at_utc
            FROM tickets ORDER BY ticket_id
            """
        )
        for row in ticket_rows:
            ticket_id = row["ticket_id"]
            payload_json = row["payload_json"]
            digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            if digest != row["payload_sha256"]:
                raise TicketLedgerError(
                    f"stored ticket {ticket_id!r} failed its SHA-256 integrity check"
                )
            try:
                ticket = json.loads(payload_json)
            except json.JSONDecodeError as exc:
                raise TicketLedgerError(
                    f"stored ticket {ticket_id!r} is not valid JSON"
                ) from exc
            if not isinstance(ticket, dict) or ticket.get("ticket_id") != ticket_id:
                raise TicketLedgerError(
                    f"stored ticket {ticket_id!r} has an inconsistent identity"
                )
            try:
                validated = validate_ticket_record(ticket)
                _validate_recorded_at(row["recorded_at_utc"], validated)
            except (KeyError, TypeError, ValueError) as exc:
                raise TicketLedgerError(
                    f"stored ticket {ticket_id!r} failed structural validation"
                ) from exc
            ticket_hashes[ticket_id] = digest
            ticket_count += 1

        score_count = 0
        score_rows = connection.execute(
            """
            SELECT ticket_id, reconciliation_sha256, score_json, score_sha256
            FROM ticket_scores ORDER BY ticket_id, reconciliation_sha256
            """
        )
        for row in score_rows:
            ticket_id = row["ticket_id"]
            if ticket_id not in ticket_hashes:
                raise TicketLedgerError(
                    f"stored score references missing ticket {ticket_id!r}"
                )
            score_json = row["score_json"]
            digest = hashlib.sha256(score_json.encode("utf-8")).hexdigest()
            if digest != row["score_sha256"]:
                raise TicketLedgerError(
                    f"stored score for ticket {ticket_id!r} failed its SHA-256 integrity check"
                )
            try:
                score = json.loads(score_json)
            except json.JSONDecodeError as exc:
                raise TicketLedgerError(
                    f"stored score for ticket {ticket_id!r} is not valid JSON"
                ) from exc
            if (
                not isinstance(score, dict)
                or score.get("ticket_id") != ticket_id
                or score.get("ticket_sha256") != ticket_hashes[ticket_id]
            ):
                raise TicketLedgerError(
                    f"stored score for ticket {ticket_id!r} has inconsistent ticket binding"
                )
            evidence_digest = score.get(
                "score_evidence_sha256", row["reconciliation_sha256"]
            )
            try:
                evidence_digest = _sha256(
                    evidence_digest, "stored score evidence digest"
                )
            except TicketLedgerError as exc:
                raise TicketLedgerError(
                    f"stored score for ticket {ticket_id!r} has an invalid evidence digest"
                ) from exc
            if evidence_digest != row["reconciliation_sha256"]:
                raise TicketLedgerError(
                    f"stored score for ticket {ticket_id!r} has an inconsistent evidence key"
                )
            score_count += 1

        return {"ticket_count": ticket_count, "score_count": score_count}

    def verify_integrity(self) -> dict[str, Any]:
        """Validate SQLite structure and all ticket/score content hashes."""
        with closing(self._connect()) as connection:
            counts = self._verify_connection(connection)
        return {"integrity": "ok", **counts}

    def backup_to(self, destination: str | Path) -> dict[str, Any]:
        """Create a consistent, verified SQLite backup without overwriting a file."""
        target_path = Path(destination)
        if target_path.resolve() == self.path.resolve():
            raise TicketLedgerError("backup destination must differ from the source database")
        if target_path.exists():
            raise FileExistsError(f"refusing to overwrite existing backup: {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=target_path.parent,
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)

        try:
            with closing(self._connect()) as source:
                source_counts = self._verify_connection(source)
                with closing(
                    sqlite3.connect(
                        temporary_path,
                        timeout=30.0,
                        isolation_level=None,
                    )
                ) as target:
                    target.row_factory = sqlite3.Row
                    source.backup(target)
                    journal_mode = target.execute(
                        "PRAGMA journal_mode = DELETE"
                    ).fetchone()
                    if (
                        journal_mode is None
                        or str(journal_mode[0]).lower() != "delete"
                    ):
                        raise TicketLedgerError(
                            "backup could not be finalized as a standalone SQLite file"
                        )
                    backup_counts = self._verify_connection(target)

            if backup_counts != source_counts:
                raise TicketLedgerError(
                    "backup verification counts differ from the source ledger"
                )

            with temporary_path.open("rb+") as handle:
                os.fsync(handle.fileno())

            try:
                os.link(temporary_path, target_path)
            except FileExistsError:
                raise
            except OSError as exc:
                raise TicketLedgerError(
                    "backup could not be published atomically without overwriting "
                    "an existing destination; use a filesystem that supports hard links"
                ) from exc
            temporary_path.unlink()

            digest = hashlib.sha256()
            with target_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)

            return {
                "path": str(target_path.resolve()),
                "sha256": digest.hexdigest(),
                **backup_counts,
            }
        finally:
            temporary_path.unlink(missing_ok=True)

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
                original_recorded_at = _validate_recorded_at(
                    existing["recorded_at_utc"],
                    validated,
                )
                connection.commit()
                return {
                    "ticket_id": ticket_id,
                    "ticket_sha256": payload_sha256,
                    "recorded_at_utc": original_recorded_at,
                    "inserted": False,
                    "idempotent_replay": True,
                }

            recorded_at = _validate_recorded_at(_utc_now(), validated)
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
        validated = validate_ticket_record(ticket)
        _validate_recorded_at(row["recorded_at_utc"], validated)
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
        pleno15_report: dict[str, Any] | None = None,
        pleno15_sha256: str | None = None,
        official_result_snapshot: dict[str, Any] | None = None,
        official_result_snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Score a stored ticket against fixture, Pleno and optional prize evidence."""
        reconciliation_digest = _sha256(reconciliation_sha256, "reconciliation_sha256")
        if official_result_snapshot is None:
            if official_result_snapshot_sha256 is not None:
                raise TicketLedgerError(
                    "official_result_snapshot_sha256 requires an official result snapshot"
                )
            snapshot_digest = None
            if pleno15_report is None:
                if pleno15_sha256 is not None:
                    raise TicketLedgerError(
                        "pleno15_sha256 requires a Pleno al 15 result report"
                    )
                score_evidence_digest = reconciliation_digest
                pleno15_digest = None
            else:
                if pleno15_sha256 is None:
                    raise TicketLedgerError(
                        "pleno15_sha256 is required with a Pleno al 15 result report"
                    )
                pleno15_digest = _sha256(pleno15_sha256, "pleno15_sha256")
                score_evidence_digest = hashlib.sha256(
                    b"KINI-TICKET-SCORE-EVIDENCE-V1\x00"
                    + bytes.fromhex(reconciliation_digest)
                    + bytes.fromhex(pleno15_digest)
                ).hexdigest()
        else:
            if pleno15_report is None or pleno15_sha256 is None:
                raise TicketLedgerError(
                    "official prize scoring requires hashed Pleno result evidence"
                )
            if official_result_snapshot_sha256 is None:
                raise TicketLedgerError(
                    "official_result_snapshot_sha256 is required with an official result snapshot"
                )
            pleno15_digest = _sha256(pleno15_sha256, "pleno15_sha256")
            snapshot_digest = _sha256(
                official_result_snapshot_sha256, "official_result_snapshot_sha256"
            )
            score_evidence_digest = hashlib.sha256(
                b"KINI-TICKET-SCORE-EVIDENCE-V2\x00"
                + bytes.fromhex(reconciliation_digest)
                + bytes.fromhex(pleno15_digest)
                + bytes.fromhex(snapshot_digest)
            ).hexdigest()
        stored = self.get_ticket_record(ticket_id)
        if stored is None:
            raise TicketLedgerError(f"ticket {ticket_id!r} does not exist")
        score = score_ticket_record(
            stored["ticket_record"],
            reconciliation_report,
            ticket_sha256=stored["ticket_sha256"],
            reconciliation_sha256=reconciliation_digest,
            pleno15_report=pleno15_report,
            pleno15_report_sha256=pleno15_digest,
            official_result_snapshot=official_result_snapshot,
            official_result_snapshot_sha256=snapshot_digest,
        )
        if pleno15_report is not None or official_result_snapshot is not None:
            score["score_evidence_sha256"] = score_evidence_digest
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
                (ticket_id, score_evidence_digest),
            ).fetchone()
            if existing is not None:
                if existing["score_sha256"] != score_sha256:
                    connection.rollback()
                    raise TicketLedgerConflict(
                        "the same ticket/evidence bundle produced different scores"
                    )
                connection.commit()
                return {
                    "score": score,
                    "score_sha256": score_sha256,
                    "recorded_at_utc": existing["recorded_at_utc"],
                    "score_evidence_sha256": score_evidence_digest,
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
                    score_evidence_digest,
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
            "score_evidence_sha256": score_evidence_digest,
            "inserted": True,
            "idempotent_replay": False,
        }

    def score_ticket_json(
        self,
        ticket_id: str,
        reconciliation_json: str | bytes,
        *,
        pleno15_json: str | bytes | None = None,
        official_result_snapshot_json: str | bytes | None = None,
    ) -> dict[str, Any]:
        """Hash exact reconciliation, Pleno and optional official prize-snapshot bytes."""
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

        pleno_report = None
        pleno_digest = None
        if pleno15_json is not None:
            if isinstance(pleno15_json, str):
                pleno_raw = pleno15_json.encode("utf-8")
            elif isinstance(pleno15_json, bytes):
                pleno_raw = pleno15_json
            else:
                raise TypeError("pleno15_json must be UTF-8 text or bytes")
            try:
                pleno_report = json.loads(pleno_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TicketLedgerError(
                    "Pleno al 15 JSON must contain a valid UTF-8 JSON document"
                ) from exc
            if not isinstance(pleno_report, dict):
                raise TicketLedgerError("Pleno al 15 JSON root must be an object")
            pleno_digest = hashlib.sha256(pleno_raw).hexdigest()

        digest = hashlib.sha256(raw).hexdigest()
        snapshot = None
        snapshot_digest = None
        if official_result_snapshot_json is not None:
            if isinstance(official_result_snapshot_json, str):
                snapshot_raw = official_result_snapshot_json.encode("utf-8")
            elif isinstance(official_result_snapshot_json, bytes):
                snapshot_raw = official_result_snapshot_json
            else:
                raise TypeError(
                    "official_result_snapshot_json must be UTF-8 text or bytes"
                )
            try:
                snapshot = json.loads(snapshot_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TicketLedgerError(
                    "official result snapshot JSON must contain a valid UTF-8 JSON document"
                ) from exc
            if not isinstance(snapshot, dict):
                raise TicketLedgerError(
                    "official result snapshot JSON root must be an object"
                )
            snapshot_digest = hashlib.sha256(snapshot_raw).hexdigest()

        return self.score_ticket(
            ticket_id,
            report,
            reconciliation_sha256=digest,
            pleno15_report=pleno_report,
            pleno15_sha256=pleno_digest,
            official_result_snapshot=snapshot,
            official_result_snapshot_sha256=snapshot_digest,
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
                    "reconciliation_sha256": score.get(
                        "reconciliation_sha256", row["reconciliation_sha256"]
                    ),
                    "score_evidence_sha256": score.get(
                        "score_evidence_sha256", row["reconciliation_sha256"]
                    ),
                    "recorded_at_utc": row["recorded_at_utc"],
                }
            )
        return results
