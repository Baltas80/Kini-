# Coupon-level walk-forward backtest

## Purpose

The fixture-level walk-forward ledger evaluates matches independently. It is not sufficient for a 15-match Quiniela coupon when its fixtures span several calendar days: a prediction generated after the first match must not use results from that match or any later fixture in the same coupon.

This pilot introduces a coupon-level evaluation with one immutable training snapshot per coupon.

## Sources and reconciliation

- Coupon order and local kickoff timestamps are imported from HistoricalQuiniela. This is a secondary source and is not treated as authoritative.
- Its summary field labelled "Fecha" is stored only as `source_date_label_at` plus its calendar date. It is **not** a result-publication timestamp: Jornada 21/2020-21 displays 13-12-2020 22:57 even though its Pleno fixture Celta–Cádiz kicked off on 14-12-2020. The label is used only to select the corresponding SELAE draw-date URL and is never used as evidence that results were available at that time.
- The ordered 14 main fixtures, their teams, scores and 1/X/2 signs, plus the Pleno al 15 score/categories, must reconcile exactly against the corresponding public SELAE results page.
- Raw HTML from HistoricalQuiniela is retained as a workflow artifact. The archive records SHA-256 digests, source URLs and retrieval timestamps.
- The SELAE detail page returned HTTP 403 from the GitHub Actions runner. The current six-coupon pilot therefore uses individually reviewed normalized extracts for 2020/2021 Jornadas 19, 21, 22, 25 and 29, plus 2021/2022 Jornada 1, under `kini_engine/data/selae_official_coupon_results/`. Each digest covers the exact JSON extract bytes, not raw SELAE HTML or PDF bytes. Prize distributions for Jornadas 19, 22, 25, 29 and 2021/2022 Jornada 1 are transcribed from official SELAE press-release PDFs; Jornada 21 remains result-only. The original PDF bytes were not captured, so no raw-PDF digest is claimed. This is an explicit manual-source limitation, not an automated raw-page capture.
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

The current CI pilot imports and evaluates six coupons across two seasons: 2020/2021 Jornadas 19, 21, 22, 25 and 29, plus 2021/2022 Jornada 1. It validates ingestion, normalized official reconciliation, canonical identity, common cutoff, model execution and optimizer integration for five nearby draws in one season and one separate-season draw. The official snapshots are manually reviewed normalized extracts, not original SELAE HTML/PDF captures; a full-season archive still requires individually reviewed official snapshots or a reliable official endpoint.

Six coupons across two seasons remain far too few for model selection, hit-rate estimation, payout performance or profitability claims. The importer can retrieve all 63 jornadas for 2020/2021 and 68 for 2021/2022, but full-season expansion requires official reconciliation for every draw and explicit handling of missing, postponed or rescheduled fixtures before aggregate ticket metrics are interpreted.


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

Coupon backtest result schema version 3 stores the exact generated columns for each model candidate and adds the explicit `training_history_min_date` / `training_history_max_date` fitted-window provenance. Each column contains 14 ordered 1/X/2 signs. The result also stores the actual 14 main outcomes, the actual Pleno categories, selected Pleno category sets, and the price per payable bet. The acceptance gate rejects legacy result schema version 2; the separate coupon archive remains schema version 2.

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

Generated pre-ticket records can be persisted in the SQLite ledger described in [TICKET_LEDGER.md](TICKET_LEDGER.md). The ledger stores the exact generated columns and probability/source provenance, rejects conflicting reuse of ticket IDs, and can append reproducible 14-match and official prize-tier scoring results against hashed SELAE evidence. The separate prize-scoring module exposes conditional published-unit-prize references only; actual payout, expected value and profitability remain unevaluated. The configured database must reside on persistent storage in deployment.


## Training-window provenance

Each coupon result now records `training_history_min_date` and `training_history_max_date` from the exact rows passed to the model fit. The batch acceptance validator rejects missing, reversed or post-cutoff ranges and requires the latest training source date to precede the first kickoff. This makes the actual date window visible in the artifact instead of recording only a row count and a declared cutoff.

The date-range fields are audit metadata derived from the filtered input dataset. They do not independently authenticate match completion timestamps; the dataset's date-only limitation and previous-local-calendar-day cutoff remain in force.


## First end-to-end coupon pilot result — 2026-11-17

Run [44090714917](https://github.com/Baltas80/Kini-/actions/runs/44090714917), artifact ID `14332295130`, code revision `70a8288bb28d9a8199636c35ff57e918a43484e1`.

The single pilot coupon was `2020-2021:21` (Jornada 21), with first kickoff `2020-12-12T14:00:00+01:00`. The common training cutoff was `2020-12-11`; the fitted history contained 303 matches from `2020-09-12` through `2020-12-11`. The full historical dataset contained 5,322 rows and had SHA-256 `7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44`.

All three candidates completed all 14 main-match predictions with no model failures. Each generated an 8-column ticket (3 doubles, 0 triples), 8 payable bets and a cost of €6.00 at €0.75 per bet.

| Candidate | Single-sign hits | Best direct column | Exact 14/14 coverage | Pleno hit | Full 15/15 coverage |
|---|---:|---:|---|---|---|
| Dixon-Coles | 7/14 | 7/14 | No | No | No |
| ML | 5/14 | 6/14 | No | No | No |
| Fixed DC/ML ensemble | 7/14 | 8/14 | No | No | No |

The Dixon-Coles Pleno prediction was category pair `1–1`, with aggregated probability mass `0.13002176742050037`; the reconciled SELAE result was `M–0`. It did not hit.

This is a single-coupon integration smoke test, not a performance sample. It does not justify selecting the ensemble, estimating long-run hit rates, or claiming profitability. The official result source is a manually reviewed normalized SELAE JSON extract, not raw official HTML. Prize tiers, realized payout and return on stake are not included. The secondary coupon archive supplies kickoff metadata; the model's historical match dataset has date-only timestamps, so the documented previous-local-calendar-day cutoff remains the conservative temporal boundary.


## Schema-v3 verification run — 2026-11-17

Run [44091537438](https://github.com/Baltas80/Kini-/actions/runs/44091537438), artifact ID `14332240705`, code revision `7d1cd819e304907ed17e8157a6c765e184c63287`. The emitted result declares `schema_version: 3`; the batch writer and fail-closed validator use the shared `COUPON_BACKTEST_RESULT_SCHEMA_VERSION` constant. The pilot passed all acceptance steps and reproduced the same one-coupon metrics above: 303 training matches, 14 predictions per model, 8 columns/€6 per candidate, no exact 14/14 coverage, no Pleno hit and no full 15/15 coverage. The fitted date range is `2020-09-12`–`2020-12-11`.

This rerun verifies the result-contract migration, not a new performance sample.


## Second independently reviewed historical coupon — Jornada 19, 2020-12-06

A second coupon is now represented by a normalized SELAE result extract at `kini_engine/data/selae_official_coupon_results/2020-2021-19.json`. It contains all 14 ordered main fixtures and the Eibar–Valencia Pleno al 15 result (0–0, categories 0–0). The official result page and the official SELAE press-release PDF are recorded as supporting sources. The 14 match identities, scores and dates were cross-checked against the HistoricalQuiniela Jornada 19 page and the Football-Data SP1/SP2 historical dataset.

The official press release reports €3,491,465.25 in Quiniela revenue, no winners in the Pleno al 15 or 14 categories (both rollovers), and unit prizes of €7,077.29 (13), €460.21 (12), €49.97 (11) and €10.06 (10). These values are preserved in the normalized extract as source evidence; the current backtest does **not** yet consume them to calculate payouts or return on stake.

The earliest main fixture kicked off on 2020-12-05 at 14:00 Europe/Madrid. The conservative previous-local-calendar-day cutoff is 2020-12-04, with 277 completed Football-Data matches in the validated 5,322-row source snapshot. The coupon pilot minimum is therefore set to 250 matches, below the observed 277 but still explicitly enforced. This is an engineering smoke-test threshold, not a claim of statistically sufficient model training.

The pilot now imports journeys 19 and 21 together and requires two independently reviewed SELAE snapshots, 30 reconciled fixtures, and 14 predictions from each of Dixon-Coles, ML and the fixed DC/ML ensemble for each coupon. It reuses the immutable validated historical-data artifact from the PR base branch instead of downloading Football-Data again for every PR run. Manual workflow dispatch performs a fresh, fail-closed history build.

This expands the end-to-end sample from one to two coupons. It remains far too small for model selection, hit-rate estimation, payout performance or profitability claims. The next separate task is to validate the stored prize-distribution schema and implement exact-column payout scoring without assuming that a 14-match hit and a Pleno hit are interchangeable.


## Multi-coupon pilot validation — 2026-11-17

Final run [44102306745](https://github.com/Baltas80/Kini-/actions/runs/44102306745), artifact ID `14336777336`, code revision `b2c1d9b5b04858f22058c5ff84ba2289d878ece3`. The pilot used the validated 5,322-row Football-Data artifact (SHA-256 `7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44`) from the PR base branch, rather than downloading the source files again.

Both official snapshots reconciled successfully: Jornada 19 (2020-12-06) and Jornada 21 (2020-12-13). The first coupon had 277 training matches through 2020-12-04; the second had 303 through 2020-12-11. Each of DC, ML and fixed DC/ML ensemble emitted 14 forecasts for each coupon. All six evaluations produced eight columns, three doubles, zero triples and €6.00 cost; no 14/14, Pleno or full 15/15 coverage occurred.

| Coupon | Model | Single-sign hits | Best direct column |
|---|---|---:|---:|
| 2020-2021:19 | Dixon-Coles | 5 | 6 |
| 2020-2021:19 | ML | 6 | 7 |
| 2020-2021:19 | Fixed DC/ML ensemble | 4 | 7 |
| 2020-2021:21 | Dixon-Coles | 7 | 7 |
| 2020-2021:21 | ML | 5 | 6 |
| 2020-2021:21 | Fixed DC/ML ensemble | 7 | 8 |

The two coupons are adjacent and their training windows overlap substantially. These results validate the import/reconciliation/prediction/optimizer pipeline, not model quality. They are not sufficient for model selection, hit-rate estimation or profitability claims.

CI [44102306450](https://github.com/Baltas80/Kini-/actions/runs/44102306450) passed with 391 tests and 25 warnings. Historical data validation [44102306414](https://github.com/Baltas80/Kini-/actions/runs/44102306414) passed. The historical model backtest job was skipped by its change filter and is not represented as a new full backtest.

The official prize distribution for Jornada 19 is captured in the normalized SELAE extract, but payout scoring is not implemented. The next step is to validate that prize schema and calculate realized payout for every exact direct column and Pleno combination; only then should the archive be expanded for a larger multi-season sample.


## Final source-metadata revalidation — 2026-11-17

The Jornada 19 official result URL was normalized to the SELAE route generated by `selae_result_url` (day `6`, without a leading zero). The normalized snapshot now records both Football-Data SP1 and SP2 source URLs, in addition to the SELAE result page, SELAE press-release PDF and HistoricalQuiniela kickoff schedule. The exact normalized snapshot SHA-256 is `c92f06377823af0d42369cfeae5f498e9f999f1229b18676cc78eaf8fac03058`; Jornada 21 remains `293660df4bbdd044c944998b2979935451dd19c8dcde5639a6a2f5fc76a35488`.

- Final coupon pilot [44103113026](https://github.com/Baltas80/Kini-/actions/runs/44103113026): **success**, artifact ID `14337585593`, code revision `590af9d7da44828845e51d484dcfa7c2805eec62`. Both coupons, 30 fixture reconciliations and six 14-prediction model evaluations passed acceptance; metrics were unchanged from the preceding two-coupon run.
- Final CI [44103113010](https://github.com/Baltas80/Kini-/actions/runs/44103113010): **391 passed**, 25 warnings; lint, formatting and workflow validation passed.
- Final historical-data validation [44103113152](https://github.com/Baltas80/Kini-/actions/runs/44103113152): **success**, using the validated PR-base dataset artifact.
- Historical model workflow [44103112931](https://github.com/Baltas80/Kini-/actions/runs/44103112931): workflow succeeded, but the predictive-model backtest job was skipped by its change filter. No new full historical model backtest is claimed.

PR #10 remains open and draft. No merge or `master` modification occurred.


## Jornada 22 expansion — 2026-11-17

The pilot is configured for three coupons: Jornada 19 (2020-12-06), Jornada 21 (2020-12-13) and Jornada 22 (2020-12-20). Jornada 22's normalized SELAE extract records all 14 ordered outcomes and the Eibar–Real Madrid Pleno al 15 (1–3, categories 1–M). Its official press-release PDF reports €3,973,360.50 revenue, one Pleno winner, three 14-category winners, and the remaining four prize tiers; Elige8 reports €95,926 revenue, 26 winners and €2,029.20 per winner.

Sources for Jornada 22:
- [Official SELAE result page](https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-20-de-diciembre-de-2020)
- [Official SELAE press-release PDF](https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/NOTA_DE_PRENSA_DE_LA_QUINIELA_DE_FECHA_20_12_20.pdf)
- [HistoricalQuiniela schedule and kickoff timestamps](https://www.historicoquiniela.com/historico/2020-2021/22)
- Football-Data 2020/2021 [SP1](https://www.football-data.co.uk/mmz4281/2021/SP1.csv) and [SP2](https://www.football-data.co.uk/mmz4281/2021/SP2.csv) are used as independent date/team/score reconciliation sources, not as kickoff-time evidence.

HistoricalQuiniela reports the first Jornada 22 kickoff on 19 December 2020 at 14:00 local time; the conservative training cutoff is therefore 18 December 2020. The workflow must still prove that at least 250 completed training matches exist by that cutoff and reconcile all 15 fixtures to Football-Data before any model output is accepted. The pilot is not considered expanded successfully until all three models produce 14 valid forecasts for each of the three coupons and the optimizer's cost/coverage checks pass.


The first three-coupon execution confirmed the official result/Pleno extracts and exact Football-Data reconciliation for all 15 Jornada 22 fixtures, but stopped before modelling because the strict alias crosswalk lacked the source label `Cartagena`. The crosswalk now maps it explicitly to the canonical Football-Data identity `team:es:cartagena`, and a regression test verifies the mapping. The failed run is retained as evidence of the missing-alias defect; it is not counted as a successful pilot. A new run on the corrected branch must pass the full import, common-cutoff model evaluation and acceptance gate.


## Three-coupon pilot — validated 2026-11-17

The corrected pilot passed in [GitHub Actions run 44135127064](https://github.com/Baltas80/Kini-/actions/runs/44135127064), on functional code revision `e71cd2319682f8c50748090a5f76084756a0bf69`. The later HEAD `1c6447957bf39d0fb2055f118ff62491130b8b40` contains only test-formatting and documentation changes; its CI passed separately.

Acceptance evidence:
- Three official SELAE snapshots: Jornadas 19, 21 and 22.
- 45/45 fixtures reconciled in order to Football-Data (14 main fixtures plus Pleno per coupon).
- All three official result/Pleno snapshots verified; the exact normalized JSON bytes are hashed into the archive.
- Nine successful model/coupon evaluations: DC, ML and fixed DC/ML ensemble on each of three coupons.
- Fourteen 1/X/2 predictions per model/coupon (126 forecasts total), no model errors or empty prediction sets.
- Training histories are strictly pre-first-kickoff: 277 matches through 2020-12-04; 303 through 2020-12-11; 325 through 2020-12-18.
- Each ticket uses eight direct columns, three doubles, zero triples, eight payable bets and €6.00 cost per coupon.

| Coupon | First kickoff (Europe/Madrid) | Training cutoff | Training matches | DC single/best | ML single/best | Ensemble single/best |
|---|---|---|---:|---:|---:|---:|
| 2020-2021:19 | 2020-12-05 14:00 | 2020-12-04 | 277 | 5 / 6 | 6 / 7 | 4 / 7 |
| 2020-2021:21 | 2020-12-12 14:00 | 2020-12-11 | 303 | 7 / 7 | 5 / 6 | 7 / 8 |
| 2020-2021:22 | 2020-12-19 14:00 | 2020-12-18 | 325 | 6 / 7 | 7 / 7 | 6 / 7 |

`single/best` means correct signs in the model's single-sign forecast / maximum hits among the eight generated columns. Mean best-column hits were 6.67 (DC), 6.67 (ML) and 7.33 (ensemble); mean single-sign hits were 6.00, 6.00 and 5.67 respectively. None of the nine evaluations covered all 14 main signs, none hit the selected Pleno pair, and none covered the complete 15-match coupon.

The selected Pleno pairs were 0–1 for Jornada 19 (actual 0–0), 1–1 for Jornada 21 (actual M–0), and 0–1 for Jornada 22 (actual 1–M). This is a separate Dixon–Coles category-pair forecast; it is not an ML Pleno prediction.

The model candidates each cost €6 per coupon, or €18 over the three coupons. This is ticket cost only. The official prize table in the Jornada 22 snapshot is not applied as actual payout: no sales receipt/official participation is evidenced, and hypothetical extra entries could change pari-mutuel winner counts. `payout_evaluated` and `profitability_evaluated` remain false.

The three draws are a small, temporally adjacent pipeline sample. They are not sufficient for model selection, calibrated-performance claims, hit-rate estimation, or profitability claims. This coupon workflow does not calculate Brier Score or Log Loss; the full fixture-level historical model workflow was skipped by its change filter in this run.

Artifact: [quiniela-coupon-pilot, ID 14350339610](https://github.com/Baltas80/Kini-/actions/runs/44135127064/artifacts/14350339610), ZIP SHA-256 `281741eab1469ed978952154a732cd605d8784746bac3138c26042496bd5d894`.

Jornada 22 normalized snapshot SHA-256: `71f0577f4c8deb6e0560a29169d858fb0eac4a37ab7333f32e5f5126c11b2f8c`. The raw SELAE PDF bytes were not captured, so this is not a PDF hash.


## Latest HEAD revalidation — 2026-11-17

The final documentation HEAD `6c396e3ddb7f11faecc8e9e0405abcf8ba404d43` was revalidated:
- CI [44135733444](https://github.com/Baltas80/Kini-/actions/runs/44135733444): Actionlint, Ruff lint/format and **406 tests passed**, 25 upstream deprecation warnings.
- Historical data [44135733521](https://github.com/Baltas80/Kini-/actions/runs/44135733521): 5,322 completed fixtures; 56 canonical team IDs; 10,644 resolved team references; zero unresolved teams and zero score/result mismatches; all 14 source files were within 168 hours.
- Coupon workflow [44135733610](https://github.com/Baltas80/Kini-/actions/runs/44135733610): change filter correctly skipped the pilot because the last successful three-coupon functional run remains valid and intervening changes were tests/documentation only.
- Historical model workflow [44135733492](https://github.com/Baltas80/Kini-/actions/runs/44135733492): model backtest skipped by its change filter; no new full model comparison is claimed.

The accepted three-coupon evidence remains run 44135127064 on functional code revision `e71cd2319682f8c50748090a5f76084756a0bf69`. No model or coupon implementation changed after that revision; later commits only corrected test formatting and updated documentation.


## Jornada 25 and four-coupon pilot — validated 2026-11-17

This section supersedes the earlier three-coupon pilot totals and the historical note that official prize-schema validation had not yet been implemented.

### Jornada 25 source reconciliation

Jornada 25 (draw date 2021-01-03) was added from the official SELAE result page and press-release PDF. Its 14 ordered main fixtures and Valencia–Cádiz Pleno al 15 (1–1) were checked against the HistoricalQuiniela Jornada 25 schedule and kickoff timestamps and the validated Football-Data 2020/2021 SP1/SP2 dataset. HistoricalQuiniela supplies the Europe/Madrid kickoff times; Football-Data is used for date/team/score reconciliation only. All 15 fixture rows matched exactly. The only new season-scoped alias was Ponferradina → Ponferradina, now covered by a canonical-registry regression test.

Sources:
- [Official SELAE result page](https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-03-de-enero-de-2021)
- [Official SELAE press-release PDF](https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/NOTA_DE_PRENSA_DE_LA_QUINIELA_DE_FECHA_3_1_21.pdf)
- [HistoricalQuiniela Jornada 25 schedule and kickoff times](https://www.historicoquiniela.com/historico/2020-2021/25)
- Football-Data 2020/2021 [SP1](https://www.football-data.co.uk/mmz4281/2021/SP1.csv) and [SP2](https://www.football-data.co.uk/mmz4281/2021/SP2.csv)

The official press release reports €2,669,930.25 Quiniela revenue; Pleno al 15: 1 winner at €200,244.77; 14: 14 winners at €30,513.49; 13: 275 at €728.16; 12: 3,660 at €54.71; 11: 30,768 at €6.51; 10: 143,371 at €1.68. The published combined P15 + first-category amount is €230,758.26, equal to the Pleno and 14 unit amounts combined. Elige8 reports €73,222.50 revenue, 286 winners and €140.81 per winner. These figures are stored in the normalized snapshot and validated by the prize-scoring tests.

The PDF was available as official parsed source text, but its original bytes were not retrievable in this run. No raw-PDF SHA-256 is claimed. The snapshot digest covers only the normalized JSON bytes.

### Four-coupon model/optimizer smoke test

Final pilot: [GitHub Actions run 44147170147](https://github.com/Baltas80/Kini-/actions/runs/44147170147), artifact ID 14356852772, ZIP SHA-256 aa924ae1dcc73f06732b39a6091c5fa15278735dd25943cb4b737992e50bd1ef. The validated historical dataset contained 5,322 fixtures, SHA-256 7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44.

Acceptance evidence: four official SELAE snapshots; 60/60 ordered fixtures reconciled to Football-Data; 12 successful model/coupon evaluations (DC, ML and fixed DC/ML ensemble for each coupon); 14 forecasts per evaluation (168 forecasts total); zero failed models or empty prediction sets. Every candidate used eight direct columns, three doubles, zero triples, eight payable bets and €6.00 per coupon (€24.00 per model across the four draws).

| Coupon | First kickoff (Europe/Madrid) | Training cutoff | Training matches | DC single/best | ML single/best | Ensemble single/best |
|---|---|---|---:|---:|---:|---:|
| 2020-2021:19 | 2020-12-05 14:00 | 2020-12-04 | 277 | 5 / 6 | 6 / 7 | 4 / 7 |
| 2020-2021:21 | 2020-12-12 14:00 | 2020-12-11 | 303 | 7 / 7 | 5 / 6 | 7 / 8 |
| 2020-2021:22 | 2020-12-19 14:00 | 2020-12-18 | 325 | 6 / 7 | 7 / 7 | 6 / 7 |
| 2020-2021:25 | 2021-01-02 14:00 | 2021-01-01 | 364 | 8 / 9 | 7 / 8 | 8 / 8 |

Mean single-sign/best-column hits were 6.50 / 7.25 (DC), 6.25 / 7.00 (ML) and 6.25 / 7.50 (ensemble). The Jornada 25 cutoff is strictly before the first kickoff; its latest training match was 2020-12-31. The dataset profile and importer therefore preserve the declared temporal boundary for this coupon.

No candidate covered 14/14 main signs, no complete 15/15 coupon was covered, and none of the four Dixon–Coles Pleno pair predictions matched the official pair. The four draws are temporally close with overlapping training histories; these are descriptive pipeline-smoke-test outputs, not an independent or sufficiently large performance sample. They do not justify model ranking, long-run hit-rate estimates or profitability claims. This coupon workflow does not calculate Brier Score, Log Loss or a market comparison.

The separate prize_scoring layer now validates official prize distributions, classifies each expanded direct bet and exposes conditional published-unit-prize references. It does not establish that a stored pre-ticket was actually purchased/entered, and it does not estimate a counterfactual pari-mutuel payout or ROI. Actual payout and profitability remain unevaluated.

Validation on the final code/test head:
- CI [44147170232](https://github.com/Baltas80/Kini-/actions/runs/44147170232): Actionlint, Ruff lint/format passed; **410 tests passed**, 25 upstream NumPy/penaltyblog deprecation warnings.
- Historical data validation [44147170149](https://github.com/Baltas80/Kini-/actions/runs/44147170149): **5,322 completed fixtures**, 56 canonical team IDs, 10,644/10,644 resolved team references, zero unresolved/ambiguous references, zero duplicate/conflicting fixtures, and 14 source files within the 168-hour snapshot window.
- Historical model workflow [44147170145](https://github.com/Baltas80/Kini-/actions/runs/44147170145): the workflow succeeded but its model-backtest job was skipped by the change filter because no predictive-model code changed. No new full historical model metrics are claimed.

PR #10 remains open/draft on feat/immutable-ticket-ledger, stacked on the existing feature branch. No merge and no changes to master.

**Next priority:** expand the official coupon/prize archive across additional draws and seasons only where every ordered fixture can be independently reconciled. Preserve raw PDF byte digests whenever source bytes are actually retrievable; do not infer them from normalized JSON hashes.


## Jornada 29 and five-coupon pilot — validated 2026-11-17

### Jornada 29 source reconciliation

Jornada 29 (draw date 2021-01-24) was added from the official SELAE result page and its official press-release PDF. The 14 ordered main fixtures and the Athletic Club–Getafe Pleno al 15 (5–1; categories M–1) were checked against the HistoricalQuiniela Jornada 29 schedule and its Europe/Madrid kickoff timestamps, then reconciled one-to-one against the validated Football-Data 2020/2021 SP1/SP2 dataset. All 15 fixtures matched by competition, date, explicit team alias and full-time score. The only new aliases were Girona → Girona and Castellón → Castellon; both resolve to their canonical Football-Data team IDs through the existing registry.

HistoricalQuiniela gives the first kickoff as 2021-01-23 14:00 Europe/Madrid. The training cutoff is therefore 2021-01-22, with 417 completed historical matches from 2020-09-12 through 2021-01-22. The latest validated historical dataset contains 5,322 fixtures and has SHA-256 `7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44`.

Sources:
- [Official SELAE result page](https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-24-de-enero-de-2021)
- [Official SELAE press-release PDF](https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/NOTA_DE_PRENSA_DE_LA_QUINIELA_DE_FECHA_24_1_21.pdf)
- [HistoricalQuiniela Jornada 29 schedule and kickoff times](https://www.historicoquiniela.com/historico/2020-2021/29)
- Football-Data 2020/2021 [SP1](https://www.football-data.co.uk/mmz4281/2021/SP1.csv) and [SP2](https://www.football-data.co.uk/mmz4281/2021/SP2.csv)

The official press release reports €3,149,695.50 Quiniela revenue; Pleno al 15 and 14 both had zero winners and rolled over; 13: 40 winners at €5,905.68; 12: 609 at €387.89; 11: 4,756 at €49.67; 10: 25,968 at €10.92. Elige8 reports €83,271.50 revenue, 66 winners and €693.93 per winner. These values are in the normalized SELAE snapshot and covered by a strict prize-validation regression test.

The official PDF text was retrievable through the official indexed PDF page, but its original bytes were not captured. No raw-PDF digest is claimed. Jornada 29 normalized snapshot SHA-256: `4794789c451a10a3a8b7cf82b3fb9ea0e857007280e42546312b0c695205c34e`.

### Five-coupon common-cutoff pilot

Final run: [GitHub Actions 44156981828](https://github.com/Baltas80/Kini-/actions/runs/44156981828), on functional code revision `a2dd2cac50278c53b3d64997cf3125058b99dd73`. Evidence artifact: [quiniela-coupon-pilot, ID 14360688825](https://github.com/Baltas80/Kini-/actions/runs/44156981828/artifacts/14360688825), ZIP SHA-256 `4e7d5f21f8dcf4c871606db3fe24b3ff7eb2af02d908b6c381a3406723ad98b2`.

Acceptance evidence:
- Five official SELAE snapshots: Jornadas 19, 21, 22, 25 and 29.
- 75/75 ordered main-plus-Pleno fixtures reconciled to Football-Data.
- Fifteen successful model/coupon evaluations: Dixon–Coles, ML and fixed DC/ML ensemble on each coupon.
- Fourteen 1/X/2 forecasts per evaluation: 210 forecasts total; zero failed evaluations and zero empty prediction sets.
- Every candidate used eight direct columns, three doubles, zero triples, eight payable bets and €6.00 cost per coupon.
- The new Jornada 29 training set is strictly pre-first-kickoff: 417 matches through 2021-01-22.

| Coupon | First kickoff (Europe/Madrid) | Training cutoff | Training matches | DC single/best | ML single/best | Ensemble single/best |
|---|---|---|---:|---:|---:|---:|
| 2020-2021:19 | 2020-12-05 14:00 | 2020-12-04 | 277 | 5 / 6 | 6 / 7 | 4 / 7 |
| 2020-2021:21 | 2020-12-12 14:00 | 2020-12-11 | 303 | 7 / 7 | 5 / 6 | 7 / 8 |
| 2020-2021:22 | 2020-12-19 14:00 | 2020-12-18 | 325 | 6 / 7 | 7 / 7 | 6 / 7 |
| 2020-2021:25 | 2021-01-02 14:00 | 2021-01-01 | 364 | 8 / 9 | 7 / 8 | 8 / 8 |
| 2020-2021:29 | 2021-01-23 14:00 | 2021-01-22 | 417 | 4 / 6 | 5 / 6 | 5 / 5 |

Across the five draws, mean single-sign/best-column hits were 6.00/7.00 (DC), 6.00/6.80 (ML) and 6.00/7.00 (fixed ensemble). No candidate covered 14/14 main signs, no full 15/15 coupon was covered, and none of the five Dixon–Coles Pleno category-pair predictions matched the official pair. These adjacent draws share overlapping training histories; this remains a pipeline smoke test, not a statistically adequate sample for model ranking, calibrated-performance claims or future hit-rate estimates.

The pilot does not calculate Brier Score, Log Loss or a market comparison. The historical model workflow [44156982053](https://github.com/Baltas80/Kini-/actions/runs/44156982053) correctly skipped its expensive backtest job under the change filter; no new full historical model metrics are claimed. Actual payout and profitability remain unevaluated: the archive has official published prize tiers, but no evidence that these hypothetical tickets were purchased or entered, and pari-mutuel winner counts cannot be inferred.

Final validation on the report HEAD:
- CI [44156981868](https://github.com/Baltas80/Kini-/actions/runs/44156981868): Actionlint, Ruff lint/format and **412 tests passed**, with 25 upstream NumPy/penaltyblog deprecation warnings.
- Historical data validation [44156981922](https://github.com/Baltas80/Kini-/actions/runs/44156981922): 5,322 completed fixtures; 56 canonical team IDs; 10,644/10,644 team references resolved; zero unresolved/ambiguous identities, zero duplicates removed and zero score/result mismatches. All 14 source files were within the 168-hour freshness limit (maximum observed cache age approximately 8.84 hours).

PR #10 remains open/draft and stacked on `feat/selae-fixture-reconciliation`. No merge and no changes to `master`.

**Next priority:** add a fully reconciled coupon from a different season, then continue expanding the archive without treating adjacent same-season smoke-test draws as independent statistical evidence.

## Cross-season extension — Jornada 1 2021/2022 and six-coupon pilot — validated 2026-11-17

### Official source and fixture reconciliation

- SELAE result page: [La Quiniela, 15 August 2021](https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-15-de-agosto-de-2021). It publishes the ordered 14 signs and the Elche–Athletic Club Pleno al 15 result (0–0).
- SELAE prize source: [official press-release PDF for 15 August 2021](https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/NOTA_DE_PRENSA_DE_LA_QUINIELA_DE_FECHA_15_8_21.pdf). The normalized snapshot transcribes the revenue and prize tiers; the original PDF bytes were not captured.
- Secondary schedule cross-check: [HistoricalQuiniela, 2021/2022 Jornada 1](https://www.historicoquiniela.com/historico/2021-2022/1). It supplies the 15 Europe/Madrid kickoff times and confirms the order, scores and Pleno categories. It is not treated as an official result source.
- The 14 main fixtures and Pleno were reconciled 15/15 against the validated Football-Data 2021/2022 SP1/SP2 dataset. The season-scoped alias map adds explicit mappings for all 30 coupon labels, including `R. Sociedad B → Sociedad B`, `Sporting → Sp Gijon`, `Burgos → Burgos` and `Tenerife → Tenerife`; no fuzzy matching is used.
- Normalized SELAE snapshot: `kini_engine/data/selae_official_coupon_results/2021-2022-1.json`, SHA-256 `5b43ae76cf11a35bbc1fa7467129f44f1acea2a0c183f96d3afdfdcef1d0426c`.

### Temporal cutoff

The earliest fixture was R. Sociedad B–Leganés on 14/08/2021 at 17:00 Europe/Madrid. The coupon's training cutoff was therefore 13/08/2021. The fitted history contained **845 completed matches**, with maximum source date 13/08/2021. No fixture on or after the first kickoff entered the training history. HistoricalQuiniela's draw-date label (15/08/2021, 00:02) is retained only as source metadata, not as a result-publication timestamp.

### Jornada 1 model and ticket result

Actual 14-sign sequence: `XXX2211X111XX2`; Pleno al 15: `0-0`.

| Candidate | Single-sign hits | Best generated column | 14/14 covered | Pleno hit | Full coupon covered | Cost |
|---|---:|---:|---|---|---|---:|
| Dixon–Coles | 7/14 | 7/14 | No | No | No | €6.00 |
| ML | 4/14 | 6/14 | No | No | No | €6.00 |
| Fixed DC/ML ensemble | 6/14 | 7/14 | No | No | No | €6.00 |

The Dixon–Coles Pleno selector chose home category 0 / away category 1 with probability mass 0.147828; the actual categories were 0/0. Every candidate generated eight 14-match columns (three doubles, no triples), eight payable bets and a €6.00 coupon cost.

### Six-coupon aggregate

Run [44168093977](https://github.com/Baltas80/Kini-/actions/runs/44168093977) passed its fail-closed acceptance gate: six official coupons across two seasons, 90/90 SELAE results, 90/90 canonical fixture reconciliations, 18 model/coupon evaluations and 252 1/X/2 forecasts, with zero failed or empty model evaluations.

| Candidate | Evaluated | Failed | Mean single-sign hits | Mean best-column hits | 14/14 coupons | Full coupons | Total cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dixon–Coles | 6 | 0 | 6.17 | 7.00 | 0/6 | 0/6 | €36.00 |
| ML | 6 | 0 | 5.67 | 6.67 | 0/6 | 0/6 | €36.00 |
| Fixed DC/ML ensemble | 6 | 0 | 6.00 | 7.00 | 0/6 | 0/6 | €36.00 |

These are realized ticket-hit diagnostics on six selected historical draws, not proper probabilistic scoring, not an unbiased hit-rate estimate and not evidence for selecting a model. The five 2020/2021 draws are close together; the single 2021/2022 draw adds cross-season coverage but does not establish season-level stability. No prize return, expected payout or profitability was evaluated.

### Reproducibility and validation

- Coupon artifact: [run 44168093977 / artifact 14367600025](https://github.com/Baltas80/Kini-/actions/runs/44168093977/artifacts/14367600025), ZIP SHA-256 `9fdfa18b2b5732de5dc4448424327befcac92f6bbbd803e6061af1f801691b9c`.
- Coupon archive SHA-256: `c755c7e075e4aef6fcc81c0d8cce10b7061b634a4c247b61b0657a55f61559cd`.
- Backtest JSON SHA-256: `34dd72b428fb13d007bf8c6330e66f1210d1118a50ea002ca9a0bdf0b71f6355`.
- Historical dataset: 5,322 fixtures, SHA-256 `7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44`.
- [CI run 44168094027](https://github.com/Baltas80/Kini-/actions/runs/44168094027): Ruff lint/format and **415 tests passed**, with 25 upstream deprecation warnings.
- [Historical-data validation run 44168093971](https://github.com/Baltas80/Kini-/actions/runs/44168093971): 5,322 completed fixtures, 56 canonical teams, 10,644/10,644 resolved team references, zero duplicates, zero conflicting duplicates, zero invalid result labels and zero score/result mismatches.
- [Historical-model workflow 44168093999](https://github.com/Baltas80/Kini-/actions/runs/44168093999) passed its change-detection job and correctly skipped the expensive backtest because no model/backtest implementation changed after the successful full model benchmark on commit `b9978dd`. The model benchmark baseline remains run 44112316408; this coupon run does not replace it.

### Remaining limitations and next step

Exact per-fixture odds-capture timestamps are still unavailable; the market comparison uses the documented snapshot schedule. The ticket evaluator can score caller-supplied joint scenarios but does not estimate a calibrated cross-match dependence distribution. Expected payout, pari-mutuel ROI and proof of ticket purchase/participation remain out of scope. Football-Data's free-data terms do not grant commercial-use or AI-training permission.

Next: add further independently reconciled 2021/2022 coupons (starting with Jornadas 2 and 3) to broaden cross-season testing. Keep the six-coupon results as pipeline evidence only; do not promote an ensemble or claim profitability from them.

