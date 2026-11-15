# SELAE fixture reconciliation

**Status:** reconciliation tooling implemented and covered by deterministic tests. No production SELAE-to-Football-Data fixture mapping is asserted yet. The checked-in crosswalk is intentionally empty.

## Why a separate crosswalk is required

A SELAE escrutinio is a coupon/result record, not a complete fixture schedule. Its `draw_date` is the draw date and must not be treated as the kickoff date. The importer also preserves the SELAE display name and optional `(M)`/`(F)` marker, but these do not prove a competition, season, kickoff time or canonical club identity.

The reconciliation step therefore requires a separately reviewed fixture-level crosswalk. It never guesses from date proximity, fuzzy name similarity, score, coupon sign or the category marker alone.

## Crosswalk contract

The manifest is `data/selae_fixture_crosswalk.json`:

```json
{
  "schema_version": 1,
  "provider": "SELAE",
  "entries": [
    {
      "draw_date": "2026-11-08",
      "position": 1,
      "football_data_date": "2026-11-07",
      "football_data_date": "2026-11-07",
      "home_selae_display_name": "Atletico de Madrid (M)",
      "away_selae_display_name": "Barcelona (M)",
      "home_football_data_name": "Ath Madrid",
      "away_football_data_name": "Barcelona",
      "competition_id": "SP1",
      "season": "2627",
      "gender": "men",
      "kickoff_at": "2026-11-08T18:30:00+01:00",
      "source_fixture_id": "provider-specific-stable-fixture-id",
      "schedule_source": "Name of the independently checked schedule source",
      "evidence_url": "https://example.org/fixture/evidence",
      "evidence_checked_at_utc": "2026-11-15T09:00:00Z"
    }
  ]
}
```

The example above documents the field shape only; it is not a verified mapping and must not be copied into the production manifest without checking the actual fixture source.

Each entry must:
- Identify one SELAE draw date and coupon position (1–14), with no duplicate key.
- Match both SELAE display names exactly after Unicode NFKC, case folding and whitespace collapse. Accents and punctuation remain significant.
- Supply the corresponding exact Football-Data team labels.
- Supply a competition and season that exist in the canonical registry.
- Declare `gender` as `men` or `women`; any SELAE `(M)`/`(F)` marker must agree.
- Supply an ISO-8601 kickoff timestamp with an explicit timezone offset.
- Supply a stable, unique source fixture identifier. Use the provider's fixture ID when available; otherwise use a unique official fixture-page URL. Duplicate source identifiers and duplicate canonical match keys (competition, kickoff instant, home ID and away ID) are rejected.
- Supply `football_data_date`, the exact calendar date recorded in the historical Football-Data CSV. It is kept separate from the independently sourced local kickoff timestamp because the CSV `Time` column's timezone convention is not relied upon by this join.
- Supply the schedule source, an HTTPS evidence URL and a UTC evidence-check timestamp.

The Football-Data labels are resolved through `TeamIdentityRegistry` with exact source, competition, season and gender scope. Unknown or ambiguous aliases remain unresolved. The current registry covers only Football-Data SP1/SP2 male teams; women, cup, European and other competitions remain unresolved until independently sourced identities and historical data are added.

## Run

First build the historical Football-Data dataset and import one or more official SELAE escrutinio pages. The importer belongs to the separate SELAE ingestion change:

```bash
python scripts/build_history.py
python scripts/import_selae_results.py --dates 2026-11-08
```

Then reconcile the imported JSONL against the exact historical dataset rows:

```bash
python -m scripts.reconcile_selae_fixtures \
  --draws data/selae_quiniela_draws.jsonl \
  --crosswalk data/selae_fixture_crosswalk.json \
  --historical data/historical_spain.csv \
  --output data/selae_fixture_reconciliation.json
```

The report includes resolved, unresolved, excluded and unused crosswalk entries, the SHA-256 of the historical dataset and the number of indexed rows. A fixture is eligible only when its exact Football-Data competition, season, date and team labels identify one row and both full-time goals agree with SELAE. Missing, duplicate or score-conflicting rows remain unresolved. The command exits non-zero if any played fixture lacks a verified mapping, any crosswalk entry is unused, or no eligible played fixture exists.

To export candidate training labels, add `--labels-output data/selae_training_labels.jsonl`. The export is refused unless the entire supplied coupon sample has been reconciled: no unresolved played fixtures and no unused crosswalk rows. Non-played fixtures whose coupon sign was determined by public draw are excluded and never become football training labels.

## Leakage and training boundary

The reconciled output contains historical targets (`home_goals`, `away_goals`, `target_1x2`) and provenance. These are labels, not pre-match features. `kickoff_at`, competition, season and team IDs are resolved from the independent crosswalk; the coupon draw date is retained separately.

This tool does **not** add SELAE records to the model's training set or alter forecasts. A downstream training integration must use kickoff time as the temporal boundary, construct every feature from information available strictly before kickoff, and keep same-day outcomes out of one another's training history. It must also validate that the matched source fixture is unique in the training dataset.

## Current state and limitations

- The manifest currently contains ten independently verified entries for coupon positions 1–10 on 8 November 2026. Official schedule evidence was checked at the respective clubs (Málaga CF, Osasuna, Real Madrid, Real Betis, Real Sociedad, RC Celta, Villarreal CF, Cádiz CF, Girona FC and Real Sporting).
- All ten entries match one exact SP1/2627 or SP2/2627 row in the historical Football-Data artifact, including exact home/away labels, calendar date and full-time score.
- For the full coupon, 13 fixtures were played and one was resolved by public draw. Ten of the 13 played fixtures are now reconciled; the three women's fixtures remain unresolved because the current historical identity registry does not contain Liga F. The public-draw fixture is excluded.
- PR #7 supplies the SELAE JSONL importer contract; this reconciliation change is developed separately on top of the canonical identity registry branch. It can be run once both changes are available in the working tree.
- The current identity registry is limited to Football-Data SP1/SP2. It cannot resolve Liga F, cup, European or other out-of-scope fixtures.
- Football-Data's match CSV `Time` column is not used as an authoritative timezone-aware kickoff. The join uses the explicit `football_data_date`, competition, season, exact team labels and full-time goals; the timezone-aware `kickoff_at` is sourced independently from the official schedule evidence. Football-Data's match CSV does not provide a fully verified per-fixture odds-capture timestamp, so this join does not make the market benchmark timestamp-verified.
- A successful identity join does not prove model performance, calibration, profitability or the absence of leakage in downstream features.
