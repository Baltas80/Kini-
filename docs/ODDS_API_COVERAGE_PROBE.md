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

The script combines `data/selae_fixture_crosswalk.json` (ten current coupon fixtures) with `data/odds_api_coverage_historical_sample.json` (six independently verified fixtures from 2020/21 through 2025/26). Both inputs contain only men's SP1/SP2 fixtures with timezone-aware official kickoffs. The default probe checks 24, 6 and 1 hour before kickoff and uses the `eu` bookmaker region.\n\n### Historical kickoff audit — 18 November 2026\n\nA cross-check against the official LaLiga matchday results and Valencia CF's published match schedule found that Valencia–Valladolid on 8 March 2025 was scheduled for **18:30 CET** (17:30 UTC), not 17:30 CET. The bundled sample now stores `2025-03-08T18:30:00+01:00` and uses the [official LaLiga matchday results](https://www.laliga.com/laliga-easports/resultados/2024-25/jornada-27) as evidence. A regression test asserts the UTC instant to prevent a repeat. This correction affects only coverage-probe metadata, not historical model inputs. Sources: [Valencia CF schedule](https://www.valenciacf.com/cuando-y-donde-ver-en-directo-el-valencia-cf-real-valladolid-cf), [LaLiga results](https://www.laliga.com/laliga-easports/resultados/2024-25/jornada-27).

The report is written atomically to `artifacts/the_odds_api_coverage.json`. The `artifacts/` directory is gitignored; do not commit provider responses or redistribute provider data.

A different sample or smaller credit budget can be selected by editing either source file or passing `--crosswalk` and `--historical-sample`. The bundled sample is capped at 16 fixtures and three horizons (96 requests/credits maximum, two requests per fixture/horizon). The horizons can be reduced, for example:

```powershell
python -m scripts.probe_the_odds_api_coverage --lead-hours 6,1
```

## Interpretation and safeguards

- The events endpoint returns the closest snapshot at or before the requested timestamp. The report records both timestamps and the staleness in seconds.
- The event-markets endpoint is queried only after exactly one normalized, case-insensitive home/away name match with the provider kickoff within **90 minutes** of the independently verified official kickoff. Participant matches outside this tolerance are reported as `kickoff_mismatch`; no markets request is sent. Unicode normalization and whitespace normalization are allowed; accents and substantive name differences are not erased. There is no fuzzy matching.
- A snapshot requested at or after the provider's scheduled kickoff is not counted as pre-kickoff coverage. The report marks it `snapshot_not_pre_kickoff` and skips the event-markets request.
- Unmatched and ambiguous candidates are retained in the report for manual alias review; they are not joined to the model dataset.
- The report records event and market response SHA-256 digests, API quota headers, bookmaker keys and the `h2h` availability by bookmaker, plus the kickoff delta, matching tolerance and whether the snapshot is strictly pre-kickoff.
- The maximum credit estimate is one credit per request. Empty historical-events responses may be free; actual per-request quota headers are retained where supplied.
- The 16-fixture sample spans the current coupon and six historical SP1 seasons, but it is not a coverage census, does not establish bookmaker continuity and does not prove usable odds density across 2020/21–2026/27.
- Coverage metadata is not odds evidence. A later paid-data pilot would still need exact fixture reconciliation, snapshot-time validation, per-bookmaker price checks, point-in-time safeguards and a licensing review before any market benchmark or model input is changed.
- The provider's own `last_update` timestamps on actual odds responses must also be checked against the requested snapshot and kickoff. This probe does not fetch those responses.

## Test coverage

`tests/test_odds_api_coverage.py` uses mocked HTTP responses. It verifies strict timezone handling, exact team matching, snapshot ordering, response hashes, bookmaker/market extraction, request authentication via header, and that no odds endpoint is called.

## GitHub Actions execution (prepared)

The repository includes a manual workflow, `.github/workflows/odds-api-coverage-probe.yml`, for running the bounded coverage check without exposing the raw provider response.

1. Add a repository Actions secret named `THE_ODDS_API_KEY` under **Settings → Secrets and variables → Actions**. Never put the key in a workflow input, command argument, commit or log.
2. Once this workflow is present on the repository's default branch, open **Actions → The Odds API coverage probe → Run workflow**.
3. Keep the default `eu` region and `24,6,1` hour horizons for the first run.

The workflow serializes runs, accepts only one region, combines the ten current fixtures with six historical fixtures, and caps the total at 16 fixtures and three horizons (maximum 96 coverage requests/credits). It calls only the historical events and event-markets endpoints and does **not** call the paid historical-odds endpoint. It writes aggregate counts to the Actions job summary, does not upload an artifact containing event IDs or bookmaker-level records, and removes the raw local report after summarization.

GitHub only exposes `workflow_dispatch` after the workflow file reaches the default branch. This change is currently prepared on the open PR branch; it has not been merged. No live request was sent in this implementation run because no API key was supplied. The local PowerShell command above remains available for a manual run from a machine with the key.

## Validation of the manual workflow

- Commit: [713a87c](https://github.com/Baltas80/Kini-/commit/713a87cc9f0930e0ab4743ed2bf229c77801178e).
- CI [44229519439](https://github.com/Baltas80/Kini-/actions/runs/44229519439): Actionlint, Ruff lint/format and **437 tests passed** (25 upstream NumPy/penaltyblog deprecation warnings).
- Historical data [44229519448](https://github.com/Baltas80/Kini-/actions/runs/44229519448): 5,322 completed fixtures, 56 canonical team IDs, 10,644/10,644 references resolved, zero unresolved references or duplicate/conflicting fixtures; integrity passed.
- Historical-model [44229519480](https://github.com/Baltas80/Kini-/actions/runs/44229519480) and coupon [44229519461](https://github.com/Baltas80/Kini-/actions/runs/44229519461) jobs were correctly skipped by their change filters; no new model result is claimed.
- The live probe remains pending because this workflow must first reach the default branch and requires the repository secret `THE_ODDS_API_KEY`. No provider request was sent by the validation runs.
