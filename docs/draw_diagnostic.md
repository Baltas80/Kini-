# OOS draw diagnostic (X)

Diagnostic-only analysis of an authentic **snapshot-aligned** prediction ledger. The
script does not refit models, modify probabilities, or make betting recommendations.

## Input contract

Use `snapshot-aligned-prediction-ledger.jsonl` produced by the
`snapshot_aligned_market_backtest` path. A conventional daily walk-forward ledger is
intentionally rejected because its forecast origin is not the same as the market
snapshot origin.

The script reads the file with `kini_engine.ledger.read_prediction_ledger`, including
the canonical manifest, row schema, probability-vector, duplicate-fixture and
SHA/schema checks. It then independently enforces:

- `forecast_as_of_date == market_snapshot_date < fixture_date`;
- both training cutoffs are strictly earlier than the market snapshot;
- market eligibility and market probabilities exist for every row;
- all manifest model modes exist in every row;
- exactly one model fit is referenced per fixture and a consistent training-history
  fingerprint is used within each snapshot.

## Run

```bash
python scripts/analyze_draw_oos.py \
  path/to/snapshot-aligned-prediction-ledger.jsonl \
  --output-dir draw-diagnostic \
  --bootstrap-samples 5000 \
  --seed 20261118
```

Outputs:
- `draw_diagnostic.json`: full metrics, calibration bins, segmentations,
  paired comparisons and bootstrap intervals.
- `draw_diagnostic.md`: compact human-readable report.

## Metrics

For market and each model:
- draw prevalence and mean P(X);
- binary P(X) Brier and log loss;
- X top-1 precision/recall and Wilson intervals;
- X top-2 precision/recall and Wilson intervals;
- fixed-width P(X) reliability bins;
- descriptive segmentation by competition and season when present.

Model-market comparisons use the exact same ordered fixture rows. Confidence intervals
are computed with a paired calendar-month block bootstrap, resampling complete months
rather than individual fixtures. The number of blocks, replicate count and seed are
recorded in the JSON output.

## Interpretation limits

Snapshot alignment is by the documented calendar date; it does not establish the exact
intraday timestamp at which a historical odds quote became available. The bootstrap
intervals are conditional on this dataset, period and month-block definition. No xG,
strength, DC/ML disagreement, payout, ROI or ticket-optimization claims are inferred.
