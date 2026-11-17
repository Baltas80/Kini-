# Immutable Quiniela ticket ledger

## Purpose

The prediction ledger in `kini_engine/ledger.py` stores match-level walk-forward forecasts. It is not the operational ledger for generated Quiniela tickets.

The ticket ledger in `kini_engine/ticket_ledger.py` stores complete pre-ticket records returned by `KiniEngine.quiniela`, including the ordered 14-match columns, probability vectors, source provenance, coupon plan, Pleno al 15 selections, budget and cost.

## Storage and configuration

The implementation uses a local SQLite database:

- Default MCP path: `data/kini-tickets.sqlite3`.
- Override: `KINI_TICKET_LEDGER_PATH`.
- The database uses WAL journaling, a 30-second busy timeout and `synchronous=FULL`.
- Ticket writes use `BEGIN IMMEDIATE` transactions. The ledger-generated `recorded_at_utc` must be at or after the declared ticket creation time and strictly before the ticket cutoff; a new late append is rejected.
- An identical idempotent replay checks the original stored append time rather than the current clock, so a valid record remains replayable after cutoff.
- A ticket ID is unique. Replaying the same ID with identical canonical JSON is idempotent. Reusing an ID with different content raises `TicketLedgerConflict`.
- Ticket and score rows have SQLite triggers that reject UPDATE and DELETE operations.

The engine can also receive an explicit `TicketLedger` instance. A generated record is persisted only when a strict pre-ticket coupon plan is supplied and a ledger is configured. If persistence fails, ticket generation fails rather than reporting a durable record that was not stored.

## Integrity and scoring

Each ticket is serialized as canonical UTF-8 JSON (sorted keys, compact separators, non-finite numbers rejected) and stored with its SHA-256 digest. Reads recompute the digest and revalidate the ticket structure.

A stored ticket can be scored against a schema-version-1 SELAE fixture-reconciliation report. The MCP scoring tool accepts the exact UTF-8 JSON document and computes its SHA-256 digest internally; Python callers can use `score_ticket_json` for the same behavior. The lower-level `score_ticket` method is available when the exact source-byte digest has already been computed by a trusted reader. The ledger invokes `score_ticket_record` itself; it does not accept caller-authored score summaries. Scores are immutable and uniquely keyed by ticket ID plus the digest of all scoring evidence. When no Pleno report is supplied, the legacy reconciliation digest remains the key; when Pleno is supplied, a domain-separated digest combines both source-document hashes. Repeating the same scoring operation is idempotent.

The score layer measures 14-match hits and exact coverage. Pleno al 15 can be scored separately when a complete official SELAE result-evidence document is supplied. It validates the two teams against the stored coupon plan, the draw date, official SELAE URL, evidence digest, verification timestamp, exact goals and the official categories (`0`, `1`, `2`, `M`, where `M` means three or more goals). The Pleno evidence is hashed independently and combined with the fixture-reconciliation digest to form the immutable score-evidence key. Without that evidence, Pleno fields remain explicitly unassessed; they are never inferred from the 14-match reconciliation. Payout and profitability remain unevaluated.

Official source: [SELAE — Cómo jugar a La Quiniela](https://www.loteriasyapuestas.es/es/centro-de-ayuda/como-se-juega/como-jugar-a-la-quiniela). The official help page states that three or more goals are represented by `M`; exact 0, 1 and 2 goals retain their corresponding categories.

## MCP tools

The MCP server configures a ledger automatically and exposes:

- `predict_quiniela`: generates and persists a ticket when the strict pre-ticket plan is supplied.
- `get_ticket_record`: retrieves one record and verifies its digest.
- `list_ticket_records`: lists records, optionally by draw date.
- `score_persisted_ticket`: accepts the exact SELAE fixture-reconciliation JSON text and, optionally, a separate exact SELAE Pleno al 15 result JSON text. It hashes both byte streams internally and persists the combined scoring result.
- `list_ticket_scores`: retrieves the immutable scoring history for one ticket.

The CLI `scripts/score_selae_ticket.py` accepts `--pleno15` alongside `--reconciliation` to evaluate the 15th match. The Pleno result document uses schema version 1 with `provider=SELAE`, draw date, official result URL, source-artifact SHA-256, evidence type, verification timestamp/method, exact home/away identity, goals and categories. The verifier checks that the evidence was verified no earlier than the Pleno kickoff.

The local database path must be on persistent storage in a deployed environment. If the MCP server runs in an ephemeral container, mount a persistent volume at the configured path or records will be lost when the container is replaced.

## Security and operational limits

- SHA-256 detects accidental corruption and mismatched artifacts; it is not a digital signature or an independent trusted timestamp.
- SQLite triggers protect against ordinary application updates/deletes, not a database owner who can replace the file or drop its triggers.
- The default implementation is a single-host local ledger. Multiple independent application replicas should use a shared transactional database with equivalent uniqueness and append-only controls.
- Back up the database and its WAL consistently; do not copy only the main database file while a writer is active.
- The ticket record preserves declared timestamps and evidence hashes. The append-window check uses the host clock; it is not a trusted timestamp, digital signature or independent proof of when an external source was published or captured.
- No expected prize, payout or profitability claim is produced.

## Validation

The automated tests cover:

- Validated append and read-back.
- Idempotent replay.
- Conflicting ticket-ID reuse.
- Expected-digest mismatch.
- UPDATE/DELETE rejection.
- SELAE 14-match reconciliation scoring and score replay.
- Official Pleno al 15 category validation, team/date matching, exact evidence hashing and full-coupon coverage scoring.
- Draw-date filtering and bounded listing.
- Engine-to-ledger integration for a pre-ticket coupon plan.


## Strict ticket-record contract

The ticket validator requires the complete engine-generated schema, not just timestamps and 14 columns. It revalidates the embedded coupon plan, matches the ticket's duplicated cutoff/schedule/Pleno metadata to that plan, validates all 14 normalized probability vectors and their position-specific source provenance, checks public-draw positions against the plan, and validates the selected Pleno category pairs.

It also checks that the declared column budget is not exceeded, that the expanded direct-bet count (14-match columns multiplied by Pleno category pairs) respects SELAE's 2–31,104 range, and that the recorded cost matches the current EUR 0.75 per direct bet. The record remains a pre-ticket forecast record; realized outcomes are not allowed into this schema.


## Pleno al 15 result evidence

A separate official result document is optional at scoring time. Its exact JSON bytes are hashed by `score_ticket_json`; the nested `source_sha256` identifies the raw official response or normalized official extract that was reviewed. Supported `evidence_type` values are `raw_official_response` and `normalized_official_extract`. The result must match the stored draw date, home/away teams and Pleno kickoff, and the reported categories must agree with the goals (`0`, `1`, `2`, or `M` for 3+). Without a Pleno document, the result deliberately omits Pleno scoring fields so historical 14-match score records remain byte-for-byte idempotent; absence means Pleno has not been assessed.

This evidence is a verified result record, not a trusted timestamp or digital signature. A normalized extract is not equivalent to retaining the original SELAE HTML. The score layer still does not calculate prize tiers, prize money, expected payout or profitability.
