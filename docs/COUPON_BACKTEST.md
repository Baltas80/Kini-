# Coupon-level walk-forward backtest

## Purpose

The fixture-level walk-forward ledger evaluates matches independently. It is not sufficient for a 15-match Quiniela coupon when its fixtures span several calendar days: a prediction generated after the first match must not use results from that match or any later fixture in the same coupon.

This pilot introduces a coupon-level evaluation with one immutable training snapshot per coupon.

## Sources and reconciliation

- Coupon order, local kickoff timestamps, scores and signs are imported from HistoricalQuiniela. This is a secondary source and is not treated as authoritative.
- The ordered 14 main fixtures, their teams, scores and 1/X/2 signs, plus the Pleno al 15 score/categories, must reconcile exactly against the corresponding public SELAE results page.
- Raw HTML is retained as a workflow artifact. The archive records SHA-256 digests, source URLs and retrieval timestamps.
- Team names are compared after Unicode/whitespace normalization only. No fuzzy matching or silent alias substitution is allowed.
- A coupon is rejected unless all 14 main results and the Pleno al 15 result are reconciled with SELAE.

## Temporal protocol

1. Parse all 15 local kickoff timestamps in Europe/Madrid.
2. Find the earliest kickoff.
3. Set the training cutoff to the previous local calendar day.
4. Include only completed historical matches whose source calendar date is on or before that cutoff.
5. Fit Dixon-Coles once and use the same history snapshot for all 15 fixtures and all model candidates in that coupon.
6. Do not use historical market odds: this coupon archive does not contain verified pre-kickoff odds-capture timestamps.

The previous-calendar-day cutoff is deliberately conservative because the Football-Data historical dataset has date-only match timestamps and cannot establish the exact completion time of another match on the same day.

## Models and ticket evaluation

The pilot evaluates Dixon-Coles, ML and the fixed DC/ML ensemble on the first 14 matches. Pleno al 15 is estimated from the Dixon-Coles score grid and is explicitly labelled as such; it is not presented as an ML forecast.

Each model's probabilities are passed unchanged to the existing multiple-direct TicketOptimizer. The budget is the maximum number of 14-match columns. The evaluation records:

- single-sign hits;
- maximum hits in any generated column;
- exact 14-match coverage by the generated columns;
- Pleno al 15 category hit;
- combined 14 + Pleno coverage;
- doubles, triples, total bets and cost.

The independent marginal coverage estimate is reported separately from realized exact coverage. No expected payout or profitability is claimed: prize distributions, pari-mutuel effects, participation-level stakes and historical payout data are not modelled in this pilot.

## Pilot scope and limitations

The first CI pilot imports and evaluates Jornada 21 of 2020/2021 only. It validates ingestion, official reconciliation, common cutoff, model execution and optimizer integration. One coupon is not a performance sample and must not be used to select a model or claim an improvement.

After the pilot passes, the importer can retrieve all 63 jornadas for 2020/2021 and later seasons. Full-season expansion requires checking every official reconciliation and documenting missing, postponed or rescheduled fixtures before aggregate ticket metrics are interpreted.
