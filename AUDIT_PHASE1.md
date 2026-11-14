# Phase 1 audit — data integrity, temporal validation and model comparison

Date: 2026-11-14  
Repository: Baltas80/Kini-  
Working branch: `audit/phase-1-temporal-validation`  
Base branch: `master`  
Current branch HEAD before this documentation update: `6e9d0aca5a844b2ae0a1a9db2e32d4f23ae2a4b1`

## Executive status

- **P0 backtesting:** validated. Dixon-Coles, ML and ensemble each generated 5,011/5,011 test predictions; zero prediction errors.
- **P1 historical ingestion:** validated. The robust Football-Data ingestion from PR #5 is now included in this branch and produced 5,311 complete matches with a passing integrity profile.
- **P2 temporal validation:** validated for same-calendar-day exclusion, date-based refit cadence and strictly pre-match ML feature history.
- **P6 ticket optimizer:** input checks, budget constraints, exhaustive small-budget DP comparison, minimum stake and Pleno al 15 aggregation are implemented and CI-tested.
- **Predictive performance:** market remains better than all model configurations on accuracy, Brier and Log Loss.
- **Not complete:** ensemble weight tuning, independent model-only ensemble comparison, temporal calibration, odds cutoff provenance, correlation-aware ticket coverage and expected-payout modelling.

## P0/P2 — walk-forward and ML integrity

The evaluator groups fixtures by calendar date. Every fixture on a date uses training data strictly earlier than that date; results from another match on the forecast date cannot enter training. Refit cadence counts forecast dates rather than individual fixtures.

ML training features for each historical training fixture use results from strictly earlier dates. Inference features use the history available before the current forecast date. The model is cached per training-history snapshot and refitted when that snapshot changes.

The earlier ML inference failure was traced to passing a one-dimensional vector to XGBoost. Inference now supplies a matrix of shape `(1, 15)`. The first-forecast diagnostic on the current branch reported:
- 5,311 source matches.
- 300 initial training matches, 126 home wins, 81 draws and 93 away wins.
- Training feature matrix `(300, 15)`, all finite.
- First forecast probabilities `[0.4015053, 0.4211001, 0.1773946]`, sum `1.0`.
- `ML_DIAGNOSTIC_OK`.

## Current historical dataset — validated

PR #5 ingestion was incorporated into PR #6's audit branch using merge commit `6e9d0aca5a844b2ae0a1a9db2e32d4f23ae2a4b1`. The merge preserves PR #6's temporal backtest workflow while bringing in the resilient source downloader, profile, tests and independent data-validation workflow.

Source: Football-Data, Primera and Segunda, seven season codes (2020/21 through 2026/27), 14 source CSVs.

GitHub Actions:
- [Historical data validation — push](https://github.com/Baltas80/Kini-/actions/runs/43631064265)
- [Historical data validation — pull request](https://github.com/Baltas80/Kini-/actions/runs/43631069244)

Validated profile:
- Rows before filtering: 5,311.
- Rows after complete-score filtering: 5,311.
- Rows after deduplication: 5,311.
- Date coverage: 2020-09-12 through 2026-11-09.
- Missing team names: 0.
- Missing or incomplete final scores: 0.
- Duplicate fixtures removed: 0.
- Conflicting duplicate fixtures: 0.
- Invalid result labels: 0.
- Score/result mismatches: 0.
- `integrity_passed: true`.
- 2026/27 coverage: LaLiga 119 matches; Segunda 140 matches.

The profile records source URLs, cache timestamps/age, missingness, date coverage and league/season counts. This validates the downloaded CSVs and the checks implemented by the ingestion pipeline; it does not prove that all possible team aliases or external schedule omissions have been resolved.

## Current model backtest — validated

GitHub Actions run: [43631064256](https://github.com/Baltas80/Kini-/actions/runs/43631064256)  
Code commit evaluated: `6e9d0aca5a844b2ae0a1a9db2e32d4f23ae2a4b1`

- Generated history: 5,311 completed fixtures.
- Initial training sample: 300 matches.
- Test sample: 5,011 fixtures.
- Test period: 2020-12-11 through 2026-11-09.
- Refit cadence: every 30 forecast dates.
- Prediction errors: 0 for Dixon-Coles, ML and ensemble.
- All three models and the market have 5,011 observations on the common sample.
- Workflow acceptance: `BACKTEST_ACCEPTANCE_OK: 5011 fixtures for dc, ml, ensemble`.

| Model | Accuracy | Multiclass Brier | Log Loss | RPS* | ECE** |
|---|---:|---:|---:|---:|---:|
| Dixon-Coles | 0.4817 | 0.6167 | 1.0278 | 0.2082 | 0.0114 |
| ML | 0.4404 | 0.6452 | 1.0709 | 0.2198 | 0.0453 |
| Ensemble | 0.4825 | 0.6134 | 1.0226 | 0.2069 | 0.0117 |
| Market | **0.5085** | **0.5980** | **1.0002** | **0.2002** | 0.0261 |

* RPS is secondary because 1/X/2 are nominal outcomes rather than a naturally ordinal scale.  
** ECE is maximum-confidence expected calibration error with 10 equal-width bins; it is not a complete class-wise calibration assessment.

### Interpretation

- The market outperforms all three model configurations on accuracy, Brier and Log Loss.
- The ensemble is marginally better than Dixon-Coles on Brier and Log Loss, but not enough to establish a meaningful advantage.
- ML remains materially weaker than Dixon-Coles and market.
- The current `ensemble` is **not a pure model-only ensemble**: its configured blend can include market probabilities (and LAE probabilities when available). Football-Data historical input supplies market odds but no LAE feed. A separate DC+ML-only blend should be evaluated before describing the ensemble as independent of the market.
- ECE values alone do not establish calibration quality; class-wise reliability and calibration on a strictly prior window remain necessary.
- These historical results do not demonstrate future profitability.

Football-Data odds columns do not carry a capture timestamp. Their exact availability at an operational betting cutoff is not established; the market comparison is a historical benchmark, not proof of executable prices at a specified time.

## P1 — historical input validation

Implemented in `kini_engine/dataio.py` and covered by tests:
- Strict parsing of ISO and Football-Data date formats.
- Rejection of missing teams, identical home/away teams and duplicate fixtures.
- Rejection of incomplete or missing final scores.
- Rejection of fractional, negative or non-finite goals.
- Rejection of unknown result labels.
- Rejection of labels inconsistent with final scores.
- Duplicate keys include date, competition and normalized team names.

The ingestion pipeline adds bounded HTTP retries, division-response validation, per-season/per-league cache, stale-cache fallback, atomic writes, chronological sorting, deduplication and a quality/provenance profile.

## P6 — ticket optimizer and Pleno al 15

Implemented and CI-tested:
- Reject malformed, non-finite, out-of-range or non-normalized 1/X/2 probabilities.
- Validate positive integer column budgets and enforce the configured minimum of two columns.
- Treat budget as the maximum number of 14-match columns.
- Report a configurable reference price of 0.75 EUR per column.
- Verify the dynamic programme against exhaustive search for a small budget.
- Aggregate the score grid into the 16 Pleno al 15 categories (0, 1, 2, M for each team) and expose the most likely category.
- Explicitly document that full-ticket coverage assumes independent match outcomes and is not expected prize or expected profit.

Rule and price references are documented in `docs/QUINIELA_RULES.md`. The price/minimum reference is based on SELAE's 2024 annual report and must be checked against current official rules before real submission. The optimizer does not yet handle all reduced-system, Elige 8 or retailer-specific constraints.

## CI

Current branch head CI:
- [Push CI](https://github.com/Baltas80/Kini-/actions/runs/43631064279)
- [Pull-request CI](https://github.com/Baltas80/Kini-/actions/runs/43631069299)
- **35 tests passed, 4 warnings.**

Warnings include pandas DataFrame fragmentation during ingestion and GitHub Actions Node.js deprecation notices. They do not fail validation, but the ingestion warning can be removed by assigning the metadata columns in one operation.

## Remaining work — priority order

1. **Separate ensembles:** implement and compare a DC+ML-only blend against the current market-blended ensemble. Learn weights only from prior out-of-sample predictions; do not tune on the final test period.
2. **Calibration:** add rolling/temporal calibration evaluation (including class-wise reliability) and compare Brier/Log Loss before and after without contaminating test data.
3. **Odds provenance:** establish a usable pre-match cutoff or explicitly constrain the market benchmark to the available Football-Data semantics.
4. **Data identity:** audit team aliases, renamed clubs and cross-season continuity; profile checks currently normalize text but do not maintain a canonical team-identity registry.
5. **Ticket economics:** test cross-match dependence and realistic system/reduced-bet constraints. Do not claim expected payout or profitability without a defensible payout model and prize-pool data.
6. **Ingestion efficiency:** remove the pandas fragmentation warning by assigning `League`, `Season` and `SourceURL` together; preserve current validation and tests.

## Phase 1 acceptance status

1. Same-date fixtures excluded from one another's training history — **validated**.
2. Walk-forward test count and date coverage reported — **validated**.
3. Model/market comparison uses the same 5,011 fixtures — **validated**.
4. Historical input validation rejects malformed dates, duplicate fixtures, incomplete scores and inconsistent labels — **implemented and CI-tested**.
5. Source/cache provenance and current-season coverage — **validated on 5,311 fixtures**.
6. Non-empty Dixon-Coles, ML and ensemble backtests — **validated, 5,011 predictions each**.
7. Optimizer probability validation and small-budget DP exactness — **implemented and CI-tested**.
8. Independent model-only ensemble, temporal calibration, timestamped odds and expected-payout model — **pending**.

## Integration status

- PR #5 (resilient ingestion): [open](https://github.com/Baltas80/Kini-/pull/5).
- PR #6 (temporal validation and models): [open, draft](https://github.com/Baltas80/Kini-/pull/6).
- PR #6 branch includes PR #5 as the second parent of the merge commit. For the cleanest eventual integration, merge PR #5 first and then PR #6.
- No PR has been merged.
- `master` remains at `ef331c3a3f50220b5d2b1a71900a2d7003b259c4` and has not been modified.
