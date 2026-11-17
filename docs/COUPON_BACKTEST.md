# Coupon-level walk-forward backtest

## Purpose

The fixture-level walk-forward ledger evaluates matches independently. It is not sufficient for a 15-match Quiniela coupon when its fixtures span several calendar days: a prediction generated after the first match must not use results from that match or any later fixture in the same coupon.

This pilot introduces a coupon-level evaluation with one immutable training snapshot per coupon.

## Sources and reconciliation

- Coupon order and local kickoff timestamps are imported from HistoricalQuiniela. This is a secondary source and is not treated as authoritative.
- Its summary field labelled "Fecha" is stored only as `source_date_label_at` plus its calendar date. It is **not** a result-publication timestamp: Jornada 21/2020-21 displays 13-12-2020 22:57 even though its Pleno fixture Celta–Cádiz kicked off on 14-12-2020. The label is used only to select the corresponding SELAE draw-date URL and is never used as evidence that results were available at that time.
- The ordered 14 main fixtures, their teams, scores and 1/X/2 signs, plus the Pleno al 15 score/categories, must reconcile exactly against the corresponding public SELAE results page.
- Raw HTML from HistoricalQuiniela is retained as a workflow artifact. The archive records SHA-256 digests, source URLs and retrieval timestamps.
- The SELAE detail page returned HTTP 403 from the GitHub Actions runner. For the single pilot coupon, a normalized JSON extract of the public official SELAE page is committed at kini_engine/data/selae_official_coupon_results/2020-2021-21.json. Its SHA-256 covers the JSON extract, not raw HTML; the file records the official URL, verification date and method. This is an explicit manual-source limitation, not an automated raw-page capture.
- Team labels from HistoricalQuiniela are mapped through a season-scoped explicit alias file and the canonical Football-Data registry. Every one of the 15 fixtures must match exactly one Football-Data fixture by local calendar date, canonical home/away identity and final score.
- No fuzzy matching or silent alias substitution is allowed. A missing alias, ambiguous identity, missing fixture, duplicate candidate or score/date mismatch rejects the coupon.
- The full historical results are used only to verify fixture identity/date/result. The model training history is filtered separately to the common pre-first-kickoff cutoff.
- A coupon is rejected unless all 14 main results and the Pleno al 15 result are reconciled with SELAE, either from live official HTML or a versioned normalized official snapshot.
- Coupon archive schema version 2 deliberately has no `result_published_at` field. HistoricalQuiniela's date label must not be repurposed as a point-in-time publication timestamp.

## Temporal protocol

1. Parse all 15 local kickoff timestamps in Europe/Madrid.
2. Find the earliest kickoff.
3. Set the training cutoff to the previous local calendar day.
4. Include only completed historical matches whose source calendar date is on or before that cutoff.
5. Record the minimum and maximum source dates actually used for the fitted history. The acceptance validator independently requires the recorded range to be ordered, no later than the cutoff, and strictly before the first kickoff.
6. Fit Dixon-Coles once and use the same history snapshot for all 15 fixtures and all model candidates in that coupon.
7. Do not use historical market odds: this coupon archive does not contain verified pre-kickoff odds-capture timestamps.

The previous-calendar-day cutoff is deliberately conservative because the Football-Data historical dataset has date-only match timestamps and cannot establish the exact completion time of another match on the same day. The secondary source supplies kickoff times; the Football-Data cross-check validates each fixture's calendar date, team identity and score, but not the exact kickoff minute.

## Models and ticket evaluation

The pilot evaluates Dixon-Coles, ML and the fixed DC/ML ensemble on the first 14 matches. Pleno al 15 is estimated from Dixon-Coles' aggregated 4×4 score-category probabilities. The result records the model, selection rule, selected probability mass and training count; it is not presented as an ML forecast because ML currently emits only 1/X/2 probabilities.

Each model's probabilities are passed unchanged to the existing multiple-direct TicketOptimizer. The budget is the maximum number of 14-match columns. The evaluation records:

- single-sign hits;
- maximum hits in any generated column;
- exact 14-match coverage by the generated columns;
- Pleno al 15 category hit;
- combined 14 + Pleno coverage;
- the exact ordered list of generated 14-sign direct columns;
- doubles, triples, the Pleno category multiplier, total payable bets, unit price and cost;
- realized 14-match coverage, best-column hits and single-sign hits, recomputed from the persisted columns and actual reconciled results.

The acceptance gate independently verifies that the number of direct columns is exactly 2^d × 3^t, that the selected signs form the complete Cartesian multiple, that total bets equal direct columns multiplied by the Pleno category-pair count, and that cost equals total bets multiplied by the configured price per bet. It recomputes realized coverage and hit counts from the saved columns rather than trusting summary fields.

The independent marginal coverage estimate is reported separately from realized exact coverage. It multiplies per-fixture marginal masses and therefore assumes independence; it is not a joint 14-match probability. Match dependence, multi-ticket diversification and payout modelling remain outside this pilot. No expected payout or profitability is claimed: prize distributions, pari-mutuel effects, participation-level stakes and historical payout data are not modelled in this pilot.

## Pilot scope and limitations

The first CI pilot imports and evaluates Jornada 21 of 2020/2021 only. It validates ingestion, normalized official reconciliation, canonical identity, common cutoff, model execution and optimizer integration. The official snapshot is a manually reviewed normalized extract, not the original SELAE HTML; a future full-season archive needs an accessible official endpoint or individually reviewed official snapshots.

One coupon is not a performance sample and must not be used to select a model or claim an improvement. After the pilot passes, the importer can retrieve all 63 jornadas for 2020/2021 and later seasons. Full-season expansion requires checking every official reconciliation and documenting missing, postponed or rescheduled fixtures before aggregate ticket metrics are interpreted.


## Fail-closed acceptance for multi-coupon runs

The batch runner must not report success when only Dixon-Coles completes. Before writing the result artifact it now checks every requested coupon, in archive order, and requires all three candidates (Dixon-Coles, ML and fixed DC/ML ensemble) to produce 14 valid normalized 1/X/2 vectors for every coupon.

The acceptance gate also verifies official SELAE result and Pleno reconciliation, all 15 canonical fixture identities, the previous-local-calendar-day cutoff, minimum and fitted training counts, explicit Dixon-Coles Pleno provenance, optimizer column budget, the 31,104 direct-system cap, ticket metrics and consistency of the combined 14 + Pleno coverage flag. A partial model run or malformed vector exits non-zero and no successful result artifact is written.

This is a software acceptance gate, not evidence that the models are accurate or that the ticket is profitable. Full-season expansion remains blocked until each coupon has its own official SELAE reconciliation evidence.

## Importing multiple reviewed official snapshots

The importer accepts either one `--official-snapshot` for exactly one explicit journey, or `--official-snapshot-dir` for a batch. Directory mode expects one reviewed normalized extract per journey, named `SEASON-JOURNEY.json` (for example `2020-2021-21.json`). When `--journeys` is omitted, the secondary season index supplies the candidate journey list; every corresponding official snapshot must exist or the import fails closed. Directory mode never silently falls back to a live request or another journey's snapshot.

The manifest records the snapshot path and SHA-256 per journey, and each coupon record retains the exact snapshot path, official URL, verification method and normalized-extract digest. The digest covers the JSON bytes, not the original SELAE HTML. Missing files, symlinks, invalid JSON roots, wrong draw dates, fixture-order/team/score mismatches or Pleno mismatches reject the import before the output archive is written.

Example:

```powershell
python scripts/import_historical_coupons.py --season 2020-2021 --journeys 21 22 23 --official-snapshot-dir data/selae-snapshots --output data/coupons-2020-2021.jsonl --raw-dir artifacts/coupon-source
```

This option makes multi-journey import reproducible when official pages have been independently reviewed and normalized. It does not make the snapshots official automatically and does not remove the requirement to verify every journey individually.


## Reproducible direct-ticket audit

Coupon backtest result schema version 2 stores the exact generated columns for each model candidate. Each column contains 14 ordered 1/X/2 signs. The result also stores the actual 14 main outcomes, the actual Pleno categories, selected Pleno category sets, and the price per payable bet.

The acceptance validator requires:

1. Unique columns, each containing exactly 14 valid signs.
2. One, two or three selected signs per fixture, with the observed double/triple counts matching the declared counts.
3. A complete direct multiple with exactly 2^d × 3^t columns.
4. Total payable bets equal to direct columns × (selected home Pleno categories × selected away Pleno categories), and no more than 31,104.
5. Cost equal to total payable bets × price per bet, rounded to cents.
6. Actual outcomes consistent with the canonical Football-Data score/result reconciliation.
7. covered_14, best-column hits, single-sign hits, Pleno hit, full-coupon coverage and independent coverage recomputed from the saved columns, probabilities and actual outcomes.

This makes the generated ticket reproducible and the reported coverage auditable. It does not estimate prizes, expected payout or profitability.


The current coupon backtest scope is one selected Pleno category pair (multiplier 1), matching the default prediction path. The acceptance gate also verifies SELAE's two-bet minimum, 31,104 maximum total-bet cap and current 0.75 EUR unit price. Explicit multi-category Pleno tickets remain supported by the lower-level optimizer but are rejected by this backtest until Pleno probability mass and realized category-set coverage are evaluated consistently.

## Public-draw ticket scoring and pre-close probability contract

Public-draw outcomes are now consumable by a separate ticket-level scoring layer. The implementation lives in `kini_engine/ticket_outcomes.py`; the CLI is `scripts/score_selae_ticket.py`.

The scorer consumes:
- A persisted direct-ticket record with its 14-sign columns, ticket creation time, official admission cutoff, first kickoff, and evidence URLs/digests for the cutoff and schedule.
- A schema-version-1 fixture reconciliation report produced by `scripts/reconcile_selae_fixtures.py`.

For the requested draw date, the reconciliation must account for all positions 1–14 exactly once. Every played fixture must have a score-consistent official sign and remain training-label eligible. Every public-draw fixture must have an official SELAE sign, `score_status=not_played`, `sign_determination=public_draw`, null football goals, `training_label_eligible=false` and `ticket_outcome_eligible=true`. Any unresolved fixture or unused crosswalk entry for that draw rejects scoring. The reported placeholder score is retained as provenance and is never converted into football goals or used to derive the sign.

Example ticket record:

```json
{
  "schema_version": 1,
  "ticket_id": "quiniela-2026-11-08-001",
  "draw_date": "2026-11-08",
  "ticket_created_at_utc": "2026-11-08T09:30:00Z",
  "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
  "first_kickoff_at": "2026-11-08T14:00:00+01:00",
  "cutoff_evidence_url": "https://www.loteriasyapuestas.es/example-cutoff",
  "cutoff_evidence_sha256": "<64 lowercase hex characters>",
  "schedule_evidence_url": "https://www.example.org/official-schedule",
  "schedule_evidence_sha256": "<64 lowercase hex characters>",
  "columns": [
    ["1", "X", "2", "1", "X", "2", "1", "X", "2", "1", "X", "2", "1", "X"]
  ]
}
```

Run:

```bash
python -m scripts.score_selae_ticket \
  --ticket artifacts/ticket.json \
  --reconciliation data/selae_fixture_reconciliation.json \
  --output artifacts/ticket-score.json
```

The output stores the realized 14-sign vector, outcome type per position, public-draw positions, hits per direct column, best-column hits, exact 14/14 coverage and the SHA-256 digests of both input files. It explicitly marks payout and profitability as not evaluated. It does not estimate prize tiers, pari-mutuel payout, expected value or return on stake.

### Public-draw probability use during ticket construction

Ticket scoring can use the realized official public-draw sign without any probability estimate. Ticket construction is stricter: `build_ticket_probability_vectors` accepts football-model probabilities only for played positions. Each public-draw position must have exactly one schema-version-1 SELAE participant-forecast snapshot with:
- matching draw date and coupon position;
- a stable source ID, official HTTPS source URL and source SHA-256;
- a timezone-aware UTC capture timestamp strictly earlier than ticket creation; ticket creation must itself be strictly earlier than the ticket admission cutoff;
- the exact same declared ticket cutoff;
- a finite normalized 1/X/2 probability vector.

Post-close ball counts are explicitly rejected as a substitute. There is no uniform 1/3 fallback. The returned 14 vectors are ordered for the existing direct-ticket optimizer and include per-position probability-source metadata.

The ticket record's timestamp ordering is checked, but the timestamps and evidence documents are declarations supplied with the ticket artifact; the scorer does not cryptographically timestamp or independently authenticate a local ticket. A historical performance study must preserve the original ticket artifact and independently review the cutoff/schedule evidence. One scored ticket is an outcome audit, not a performance sample.

The scorer is intentionally limited to the 14 main matches. It does not score Pleno al 15, validate the total stake, or calculate prize tiers. Pleno remains covered by the existing coupon-level backtest path; a combined 14+Pleno ticket ledger is a separate pending integration.

A pre-close snapshot accepted by the construction helper has this shape:

```json
{
  "schema_version": 1,
  "provider": "SELAE",
  "source_id": "stable-capture-id",
  "draw_date": "2026-11-08",
  "position": 7,
  "captured_at_utc": "2026-11-08T10:30:00Z",
  "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
  "source_url": "https://www.loteriasyapuestas.es/example-preclose-snapshot",
  "source_sha256": "<64 lowercase hex characters>",
  "probabilities": {"1": 0.12, "X": 0.16, "2": 0.72}
}
```

The construction helper also requires the first scheduled kickoff and rejects a cutoff at or after it. The snapshot timestamp, cutoff and first kickoff are validated as declared timestamps; the corresponding evidence URLs and digests still require independent review.



## Pre-ticket schedule plan: strict separation from realized outcomes

The probability builder must run before the first kickoff. It therefore consumes a **schedule-only coupon plan**, never the post-match fixture-reconciliation report used by `score_ticket_record`.

The plan is schema version 1 and contains exactly these root fields:

- `provider`: `SELAE`;
- `draw_date`;
- `schedule_captured_at_utc`;
- `ticket_created_at_utc`;
- `schedule_evidence_url` and `schedule_evidence_sha256`;
- `ticket_cutoff_at_utc`;
- `first_kickoff_at`;
- `positions`: exactly one record for each position 1–14.

A scheduled position contains only `position`, `fixture_status="scheduled"`, `home`, `away` and timezone-aware `kickoff_at`. Its kickoff must be after ticket close. A position already known to be resolved by public draw before ticket close uses `fixture_status="public_draw_expected"` and must additionally carry an official SELAE status-evidence URL, SHA-256 and timezone-aware capture timestamp strictly before ticket creation. The declared first kickoff must equal the earliest kickoff among scheduled positions.

Example (abbreviated to one public-draw position; the actual plan must contain all 14):

```json
{
  "schema_version": 1,
  "provider": "SELAE",
  "draw_date": "2026-11-08",
  "schedule_captured_at_utc": "2026-11-08T09:00:00Z",
  "ticket_created_at_utc": "2026-11-08T10:45:00Z",
  "schedule_evidence_url": "https://www.loteriasyapuestas.es/example-schedule",
  "schedule_evidence_sha256": "<64 lowercase hex characters>",
  "ticket_cutoff_at_utc": "2026-11-08T11:00:00Z",
  "first_kickoff_at": "2026-11-08T14:00:00+01:00",
  "positions": [
    {
      "position": 7,
      "fixture_status": "public_draw_expected",
      "home": "Postponed Home",
      "away": "Postponed Away",
      "kickoff_at": "2026-11-08T12:00:00+01:00",
      "status_evidence_url": "https://www.loteriasyapuestas.es/example-postponement-notice.pdf",
      "status_evidence_sha256": "<64 lowercase hex characters>",
      "status_captured_at_utc": "2026-11-08T10:15:00Z"
    }
  ]
}
```

The strict validator rejects unknown fields, including any actual score, result sign, target label or post-match reconciliation collection. Football-model vectors must cover scheduled positions only. Every public-draw-expected position must have exactly one official SELAE participant-forecast snapshot captured strictly before ticket creation. Final ball counts remain post-close metadata and are not accepted as pre-ticket probabilities.

The post-match path remains separate: `score_ticket_record` consumes the fully reconciled official outcomes, including the realized public-draw sign, to score already persisted ticket columns. This separation prevents realized results from determining which forecasts are generated.

The schedule/status timestamps and hashes are still declared evidence metadata; the code verifies structure, hashes and ordering but does not independently timestamp or authenticate local captures. No historical pre-close public-draw forecast sample is currently available, so this change closes a code-path leakage risk but does not create new historical public-draw probabilities or performance metrics.


### Ticket-creation time is the point-in-time boundary

The pre-ticket plan also records `ticket_created_at_utc`. The schedule capture, public-draw status evidence and participant-forecast snapshots must all be strictly earlier than this creation instant, not merely earlier than the admission cutoff. The required order is:

`schedule_captured_at_utc < ticket_created_at_utc < ticket_cutoff_at_utc < first_kickoff_at`

Each public-draw status and participant snapshot must also satisfy `captured_at_utc < ticket_created_at_utc`. This prevents a ticket artifact created at 09:30 from being justified with information captured at 10:30 even if the official admission cutoff is 11:00. The timestamp ordering remains declared metadata until an independently trusted timestamping mechanism is integrated.

## Integrated pre-ticket generation path — 2026-11-17

The schema-v1 plan now also requires:

- `cutoff_evidence_url`, `cutoff_evidence_sha256` and `cutoff_evidence_captured_at_utc`, with official SELAE HTTPS provenance and capture strictly before ticket creation;
- `pleno15_home`, `pleno15_away` and timezone-aware `pleno15_kickoff_at`;
- `first_kickoff_at` equal to the earliest kickoff among scheduled positions 1–14 and the Pleno al 15 fixture. A position marked `public_draw_expected` is excluded from football prediction and from the played-fixture first-kickoff candidates.

The public API is now connected to the builder:

```python
result = engine.quiniela(
    fixtures,  # 14 main fixtures plus Pleno al 15, each with an aware kickoff
    budget=8,
    coupon_plan=plan,
    public_draw_snapshots={7: participant_snapshot},
)
ticket_record = result["ticket_record"]
```

Each of the 14 main fixtures must match the plan's home/away labels (NFKC, case and whitespace normalization only), coupon position and timezone-aware kickoff. The Pleno al 15 teams and kickoff are checked separately. Unknown aliases are not fuzzy-matched.

For every `public_draw_expected` position, `KiniEngine.quiniela` skips `_predict_one` entirely. Its 1/X/2 vector must come from the matching pre-ticket SELAE participant snapshot. The other main positions use the football model. The resulting 14 vectors, in coupon order, are passed unchanged to `TicketOptimizer`. The Pleno al 15 match remains a separate football-model distribution.

The returned `ticket_record` is a JSON-serializable schema-v1 direct-ticket record accepted by `score_ticket_record`. It carries the original coupon plan, schedule and cutoff evidence URLs/hashes/capture times, per-position probability vectors and source metadata, public-draw positions, Pleno identity/kickoff, all direct columns, budget and cost. `ticket_record_sha256` hashes the canonical serialized record. When no `ticket_id` is supplied, a deterministic ID is derived from the generation payload. The engine returns this record; it does not write to disk or claim that a remote MCP client has durably stored it. The caller must persist the returned JSON unchanged alongside the original source artifacts.

The MCP `predict_quiniela` tool exposes the same arguments. Because JSON object keys are strings, public-draw snapshot positions are supplied as keys such as `"7"`; the tool validates and converts them to integer positions before calling the engine.

The timestamps and hashes remain declared metadata: structural validation does not independently authenticate the local capture time or source bytes. The change closes the code-path integration gap, not the absence of a historical, independently timestamped participant-forecast ledger.

## Operational immutable ticket history

Generated pre-ticket records can be persisted in the SQLite ledger described in [TICKET_LEDGER.md](TICKET_LEDGER.md). The ledger stores the exact generated columns and probability/source provenance, rejects conflicting reuse of ticket IDs, and can append reproducible 14-match scoring results against hashed SELAE reconciliation reports. It does not calculate prizes or profitability, and the configured database must reside on persistent storage in deployment.


## Training-window provenance

Each coupon result now records `training_history_min_date` and `training_history_max_date` from the exact rows passed to the model fit. The batch acceptance validator rejects missing, reversed or post-cutoff ranges and requires the latest training source date to precede the first kickoff. This makes the actual date window visible in the artifact instead of recording only a row count and a declared cutoff.

The date-range fields are audit metadata derived from the filtered input dataset. They do not independently authenticate match completion timestamps; the dataset's date-only limitation and previous-local-calendar-day cutoff remain in force.
