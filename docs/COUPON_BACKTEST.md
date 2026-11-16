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
5. Fit Dixon-Coles once and use the same history snapshot for all 15 fixtures and all model candidates in that coupon.
6. Do not use historical market odds: this coupon archive does not contain verified pre-kickoff odds-capture timestamps.

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

The independent marginal coverage estimate is reported separately from realized exact coverage. No expected payout or profitability is claimed: prize distributions, pari-mutuel effects, participation-level stakes and historical payout data are not modelled in this pilot.

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
