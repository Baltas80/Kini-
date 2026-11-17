# Immutable Quiniela ticket ledger

## Purpose

The prediction ledger in `kini_engine/ledger.py` stores match-level walk-forward forecasts. It is not the operational ledger for generated Quiniela tickets.

The ticket ledger in `kini_engine/ticket_ledger.py` stores complete pre-ticket records returned by `KiniEngine.quiniela`, including the ordered 14-match columns, probability vectors, source provenance, coupon plan, Pleno al 15 selections, budget and cost.

## Storage and configuration

The implementation uses a local SQLite database:

- Default MCP path: `data/kini-tickets.sqlite3`.
- Override: `KINI_TICKET_LEDGER_PATH`.
- The database uses WAL journaling, a 30-second busy timeout and `synchronous=FULL`.
- Ticket writes use `BEGIN IMMEDIATE` transactions.
- A ticket ID is unique. Replaying the same ID with identical canonical JSON is idempotent. Reusing an ID with different content raises `TicketLedgerConflict`.
- Ticket and score rows have SQLite triggers that reject UPDATE and DELETE operations.

The engine can also receive an explicit `TicketLedger` instance. A generated record is persisted only when a strict pre-ticket coupon plan is supplied and a ledger is configured. If persistence fails, ticket generation fails rather than reporting a durable record that was not stored.

## Integrity and scoring

Each ticket is serialized as canonical UTF-8 JSON (sorted keys, compact separators, non-finite numbers rejected) and stored with its SHA-256 digest. Reads recompute the digest and revalidate the ticket structure.

A stored ticket can be scored against a schema-version-1 SELAE fixture-reconciliation report. The caller must supply the SHA-256 digest of the exact reconciliation source bytes. The ledger invokes `score_ticket_record` itself; it does not accept caller-authored score summaries. Scores are immutable and uniquely keyed by the ticket ID plus reconciliation digest. Repeating the same scoring operation is idempotent.

The score layer measures 14-match hits and exact coverage. It explicitly leaves payout and profitability unevaluated.

## MCP tools

The MCP server configures a ledger automatically and exposes:

- `predict_quiniela`: generates and persists a ticket when the strict pre-ticket plan is supplied.
- `get_ticket_record`: retrieves one record and verifies its digest.
- `list_ticket_records`: lists records, optionally by draw date.
- `score_persisted_ticket`: scores a stored record against an explicitly hashed reconciliation report and persists the score.

The local database path must be on persistent storage in a deployed environment. If the MCP server runs in an ephemeral container, mount a persistent volume at the configured path or records will be lost when the container is replaced.

## Security and operational limits

- SHA-256 detects accidental corruption and mismatched artifacts; it is not a digital signature or an independent trusted timestamp.
- SQLite triggers protect against ordinary application updates/deletes, not a database owner who can replace the file or drop its triggers.
- The default implementation is a single-host local ledger. Multiple independent application replicas should use a shared transactional database with equivalent uniqueness and append-only controls.
- Back up the database and its WAL consistently; do not copy only the main database file while a writer is active.
- The ticket record preserves declared timestamps and evidence hashes. It does not independently prove when an external source was published or captured.
- No expected prize, payout or profitability claim is produced.

## Validation

The automated tests cover:

- Validated append and read-back.
- Idempotent replay.
- Conflicting ticket-ID reuse.
- Expected-digest mismatch.
- UPDATE/DELETE rejection.
- SELAE reconciliation scoring and score replay.
- Draw-date filtering and bounded listing.
- Engine-to-ledger integration for a pre-ticket coupon plan.
