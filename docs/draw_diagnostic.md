# OOS draw diagnostic (X)

Diagnostic-only analysis of authentic forecast-ledger rows. It does not refit models,
alter probabilities, or make betting recommendations.

## Run

After generating an immutable forecast ledger using the project's `compare` command
and `--ledger-jsonl`, run:

```bash
python scripts/analyze_draw_oos.py path/to/forecast-ledger.jsonl --output-dir draw-diagnostic
```

Outputs:
- `draw_diagnostic.json`: metrics and bins in machine-readable form.
- `draw_diagnostic.md`: summary report.

For each probability mode, the report includes:
- observed draw prevalence and mean P(X);
- binary P(X) Brier and log loss;
- X top-1 selection precision and draw recall, with Wilson intervals;
- X inclusion in the top-two signs (double-style diagnostic);
- fixed-width P(X) calibration bins;
- league and season segmentation, only if these fields exist in the ledger.

The report also calculates descriptive paired differences in binary P(X) Brier and
log loss against the eligible market consensus, restricted to identical fixture IDs.
Eligible market rows are also reported separately; the market row count is not forced
to match the full model sample.

This version does not compute xG/strength/disagreement segments, temporal block-bootstrap
intervals or paired significance tests. It does not infer missing features from outcomes
or probabilities, and it makes no payout/ROI claim.

The script checks ledger structure, duplicate fixture IDs, probability-vector validity
and manifest row count, but the project's canonical ledger reader should still be
used for full schema validation when possible.
