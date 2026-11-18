# The Odds API: read-only historical coverage probe

## Purpose

`scripts/probe_the_odds_api_coverage.py` checks whether the provider has historical event and 1X2 (`h2h`) market coverage for verified Spanish LaLiga (SP1) and Segunda (SP2) fixtures.

It is a **coverage-discovery utility**, not a data-ingestion or prediction component. It does not download prices, change the Football-Data dataset, create market probabilities, or make any market eligible for model input.

## Provider contract verified on 18 November 2026

Official documentation identifies these sport keys and earliest historical coverage:

| Competition | Sport key | Earliest listed historical timestamp |
|---|---|---|
| LaLiga | `soccer_spain_la_liga` | 2020-06-06 10:05:00 UTC |
| Segunda | `soccer_spain_segunda_division` | 2020-06-06 10:05:00 UTC |

Historical featured markets use snapshots at 10-minute intervals before September 2022 and 5-minute intervals thereafter. For soccer, `h2h` is the three-way 1X2 market.

The historical **events** and **event markets** coverage-discovery endpoints are available on all plans, including the free plan, and cost one credit per request. They return event IDs, teams, kickoff times, snapshot timestamps, bookmaker keys and market keys, but no prices. The historical **odds** endpoint is paid-only and costs 10 credits per region per market per snapshot. The probe intentionally never calls it.

The published free plan lists 500 credits/month. The current entry plan that includes historical prices is USD $30/month for 20,000 credits. No subscription or paid request is initiated by this code. Recheck the provider's live terms and pricing before any purchase.

Official references:

- [Historical coverage and earliest timestamps](https://the-odds-api.com/historical-odds-data/)
- [Historical events and event-markets endpoints](https://the-odds-api.com/liveapi/guides/v4/)
- [Published plans and pricing](https://the-odds-api.com/)

## Run

PowerShell:

```powershell
$env:THE_ODDS_API_KEY = "YOUR_API_KEY"
python -m scripts.probe_the_odds_api_coverage --lead-hours 24,6,1 --region eu
```

The script reads `data/selae_fixture_crosswalk.json`, using only verified men's SP1/SP2 fixtures with timezone-aware official kickoffs. It probes each fixture at 24, 6 and 1 hour before kickoff by default. It uses the `eu` bookmaker region.

The report is written atomically to `artifacts/the_odds_api_coverage.json`. The `artifacts/` directory is gitignored; do not commit provider responses or redistribute provider data.

A different sample or smaller credit budget can be selected by editing the crosswalk or passing a different `--crosswalk` file. The horizons can be reduced, for example:

```powershell
python -m scripts.probe_the_odds_api_coverage --lead-hours 6,1
```

## Interpretation and safeguards

- The events endpoint returns the closest snapshot at or before the requested timestamp. The report records both timestamps and the staleness in seconds.
- The event-markets endpoint is queried only after exactly one normalized, case-insensitive home/away name match. Unicode normalization and whitespace normalization are allowed; accents and substantive name differences are not erased. There is no fuzzy matching.
- Unmatched and ambiguous candidates are retained in the report for manual alias review; they are not joined to the model dataset.
- The report records event and market response SHA-256 digests, API quota headers, bookmaker keys and the `h2h` availability by bookmaker.
- The maximum credit estimate is one credit per request. Empty historical-events responses may be free; actual per-request quota headers are retained where supplied.
- A sample of ten current-season fixtures is not proof of full historical coverage, bookmaker continuity or usable odds density across 2020/21–2026/27.
- Coverage metadata is not odds evidence. A later paid-data pilot would still need exact fixture reconciliation, snapshot-time validation, per-bookmaker price checks, point-in-time safeguards and a licensing review before any market benchmark or model input is changed.
- The provider's own `last_update` timestamps on actual odds responses must also be checked against the requested snapshot and kickoff. This probe does not fetch those responses.

## Test coverage

`tests/test_odds_api_coverage.py` uses mocked HTTP responses. It verifies strict timezone handling, exact team matching, snapshot ordering, response hashes, bookmaker/market extraction, request authentication via header, and that no odds endpoint is called.
