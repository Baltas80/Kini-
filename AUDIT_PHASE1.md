# Phase 1 audit — data integrity and temporal validation

Date: 2026-11-14  
Repository: Baltas80/Kini-  
Working branch: `audit/phase-1-temporal-validation`  
Base branch: `master`  
Status: temporal validation and non-empty model backtests validated; historical input validation and optimizer safeguards implemented and CI-tested; current-season ingestion/profile validation is running separately in PR #5.

## P0 — temporal validation and non-empty model forecasts

The walk-forward evaluator groups fixtures by calendar date. Every fixture on a date uses training data strictly earlier than that date. Refit cadence counts forecast dates, not individual fixtures.

The ML training matrix is also built using only results from dates strictly earlier than each training fixture. Inference features use the history available before the forecast date. A regression test covers same-calendar-day exclusion.

The earlier ML inference failure was traced to a one-dimensional input being passed to XGBoost. Inference now supplies a matrix with shape `(1, 15)`. The first-forecast diagnostic reported a training matrix of `(300, 15)`, finite features, probabilities `[0.4751575, 0.3782731, 0.1465693]`, sum `1.0`, and `ML_DIAGNOSTIC_OK`.

## Historical backtest evidence

GitHub Actions run: [43626020678](https://github.com/Baltas80/Kini-/actions/runs/43626020678)  
Validated code commit: `14ecc87539731bccff1408ef16b6fc6038cd6c35`

- Generated historical rows: 5,052.
- Initial training sample: 300 matches.
- Test sample: 4,752 matches.
- Test period: 2020-12-11 through 2026-05-31.
- Prediction errors: 0 for Dixon-Coles, ML and ensemble.
- All three models and the market were evaluated on the same 4,752 fixtures.
- The workflow's non-empty prediction acceptance step passed.

| Model | Accuracy | Multiclass Brier | Log Loss | RPS* | ECE** |
|---|---:|---:|---:|---:|---:|
| Dixon-Coles | 0.4806 | 0.6178 | 1.0295 | 0.2082 | 0.0116 |
| ML | 0.4339 | 0.6471 | 1.0731 | 0.2201 | 0.0518 |
| Ensemble | 0.4823 | 0.6146 | 1.0244 | 0.2069 | 0.0142 |
| Market | **0.5072** | **0.5993** | **1.0021** | **0.2003** | 0.0257 |

* RPS is secondary because 1/X/2 are nominal outcomes rather than a naturally ordinal scale.  
** ECE is the expected calibration error of maximum-confidence predictions, using 10 equal-width bins.

### Interpretation

- The ensemble is currently the strongest of the three model configurations on Brier and Log Loss, but only marginally better than Dixon-Coles.
- The market baseline beats every model on accuracy, Brier and Log Loss.
- ML is materially weaker and has the largest ECE. Its inclusion in the ensemble must be justified by later out-of-sample weight tuning, not assumed to add value.
- Dixon-Coles currently has the lowest ECE, but calibration alone does not compensate for its worse overall probabilistic scores.
- These are historical results, not evidence of future profitability.

The Football-Data odds columns do not include a capture timestamp. The market comparison is therefore a useful benchmark, but it does not establish that those exact prices were available at every possible operational betting cutoff.

## P1 — historical input validation

Implemented on this branch:

- Strict date parsing for ISO and Football-Data date formats.
- Rejection of missing teams, identical home/away teams and duplicate fixtures.
- Rejection of incomplete or missing final scores in the completed-history loader.
- Rejection of fractional, negative or non-finite goals.
- Rejection of unknown result labels.
- Rejection of result labels that conflict with the final score.
- Validation is applied by `load_matches_csv` before returning historical matches.

## P6 — optimizer input and dynamic-programming validation

Implemented on this branch:

- Rejects malformed, non-finite, negative, out-of-range or non-normalized 1/X/2 probabilities.
- Rejects boolean or non-positive column budgets.
- Documents that `joint_coverage` assumes independent match outcomes.
- Distinguishes full-ticket coverage from expected prize or expected profit.
- Adds an exhaustive small-budget comparison proving that the dynamic programme returns the maximum covered probability for the tested budget-4 search space.

GitHub Actions CI: [43626025664](https://github.com/Baltas80/Kini-/actions/runs/43626025664) — 26 tests passed, 4 warnings.

This does not yet establish expected payout, economic value, correlation-aware coverage or real ticket-price constraints. Those remain open.

## P1 — resilient source ingestion and dataset profile

PR #5: [Robustecer la ingesta histórica de Football-Data](https://github.com/Baltas80/Kini-/pull/5)  
Branch: `feat/resilient-history-ingestion`  
Latest commit at this report: `278423e7a6b2fc0674565311cd6dc0915586efa3`

That branch contains bounded HTTP retries, validated per-season/league caching, atomic writes, chronological sorting, duplicate removal and the 2026/27 season. It generates a dataset profile with source URLs, profile-generation time, cache-file timestamps/age, date coverage, missingness, duplicate counts, score/result consistency and league/season counts.

The earlier CI import and JSON-serialization failures have been corrected. CI passed at the preceding commit `eac2849` (15 tests). The latest commit adds cache provenance and workflow assertions for 2026/27 coverage and non-empty model predictions; its CI and historical run are pending. Do not mark the profile or current-season coverage validated until those latest runs complete and the profile artifact is inspected.

## Remaining work

1. Confirm PR #5 CI and the 2026/27 ingestion/backtest; inspect the generated profile and artifact rather than relying only on job success.
2. Audit team aliases, cross-season duplicates, missing values and score/result consistency across the downloaded data.
3. Establish the operational timestamp/cutoff for market odds or clearly constrain comparisons to the source's available pre-match quote semantics.
4. Tune ensemble weights using training-only temporal validation; test whether ML adds incremental value. Do not optimize weights on the final test period.
5. Evaluate calibration methods on a strictly prior calibration window and report Brier/Log Loss before and after.
6. Extend optimizer validation to realistic Quiniela costs, 14-match constraints, Pleno al 15 treatment, and sensitivity to cross-match dependence; do not claim expected profitability without a defensible payout model.

## Phase 1 acceptance status

1. Same-date fixtures cannot enter one another's training history — **validated**.
2. Walk-forward reports test count and date coverage — **validated**.
3. Model/market comparison uses a common fixture sample — **validated**.
4. Historical input validation rejects invalid dates, duplicates, incomplete scores and inconsistent labels — **implemented and CI-tested**.
5. Dataset profile records source, retrieval/cache provenance, coverage, missingness, duplicates and label consistency — **implemented on PR #5; latest end-to-end validation pending**.
6. Tests and CI pass; empirical comparisons are only reported after non-empty model backtests — **validated on PR #6 branch**.

## Integration status

PR #6 remains open and draft. PR #5 remains open. No PR has been merged. The `master` branch remains at `ef331c3a3f50220b5d2b1a71900a2d7003b259c4`.
