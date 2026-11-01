# Phase 1 audit — data integrity and temporal validation

Date: 2026-11-01
Repository: Baltas80/Kini-
Base branch reviewed: master
Status: static audit; no historical CSV is committed, so no empirical backtest result is claimed.

## Confirmed findings

### P0 — same-calendar-day leakage in walk-forward evaluation
In kini_engine/backtest.py, matches were sorted and the training cutoff advanced one fixture at a time. If multiple fixtures share a date, later fixtures on that date can be predicted after earlier same-day results have entered training. For historical data whose date field does not encode kickoff time, this is look-ahead bias.

Action: group fixtures by calendar date, train only on dates strictly earlier than the forecast date, and add regression tests proving that same-day fixtures share the same training history. Refit cadence should count forecast dates, not individual fixtures.

### P0 — empirical data audit blocked
The README describes scripts/build_history.py, which downloads external data and writes data/historical_spain.csv. That generated CSV is not committed. Therefore duplicate counts, missingness, season coverage, team-name consistency, score/result consistency, and actual model metrics cannot be established from the repository snapshot.

Required next action: obtain the generated dataset in a controlled runtime; record source URLs, retrieval timestamp, row counts, date range, duplicate fixtures, missing columns/values, score/result disagreements, and league/season counts before model evaluation.

### P1 — model comparison uses different sample sizes
In the prior compare_walk_forward, market metrics were computed only for matches with market odds, while model metrics were computed over all forecast matches. Direct comparison can therefore be confounded by sample composition.

Recommended action: retain overall metrics and add a common_sample section evaluating each available model and market on exactly the matches with market probabilities.

### P1 — CSV loader does not automatically enforce validation
load_matches_csv does not call validate_matches; malformed scores, invalid date strings, duplicated fixtures, or disagreement between FTR and goals can pass through unless callers remember to validate explicitly. Validation currently does not check date parseability, duplicates, or consistency between result and score.

Recommended follow-up: extend validation and make the CLI data-loading path fail fast before fitting.

### P1 — H2H adjustment maps outcomes to the wrong current-match perspective
In kini_engine/core.py::context_adjust, H2H values are constructed as if the current home team's historical home wins were current home wins and its historical away wins were current away wins. For a fixed current fixture, H2H home/draw/away outcomes should be determined by the current home and away teams, independent of which side hosted the historical match. The current calculation can misclassify historical evidence.

Recommended follow-up: fix the perspective mapping and add asymmetric H2H regression cases before enabling context adjustments.

### P1 — RPS definition needs scrutiny
The implementation documents RPS as an ordinal score with order 1 < X < 2. These outcomes are nominal rather than ordinal, so RPS is not an ideal primary 1X2 metric. Use multiclass Brier and log-loss as primary metrics; treat ECE as a secondary diagnostic and report the binning scheme and sample size.

## Validation status

- Static source review: completed for core.py, dataio.py, backtest.py, tuning.py, data builder, CI workflow, and existing tests.
- Historical data profiling: blocked until the generated external CSV is available.
- Full test suite / GitHub Actions on this branch: pending.
- Model performance or calibration claims: none made.

## Acceptance criteria for Phase 1

1. Same-date fixtures cannot enter one another's training history.
2. Walk-forward output records the number of evaluated fixtures and exact date range.
3. Model-vs-market metrics include a same-fixture common-sample comparison.
4. Data validation rejects invalid dates, duplicate fixtures, incomplete scores, and inconsistent result labels.
5. A dataset profile artifact records source, retrieval date, coverage, missingness, duplicates, and label consistency.
6. Tests and CI pass; empirical model comparisons are reported only after the dataset audit succeeds.
