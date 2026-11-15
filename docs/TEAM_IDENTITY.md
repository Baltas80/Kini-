# Canonical team identity registry

**Status:** exact Football-Data identities implemented and validated against the current historical artifact. Cross-provider aliases and SELAE coupon resolution remain intentionally incomplete.

## Scope and provenance

The file `kini_engine/data/team_identity_registry.json` is a versioned metadata registry generated from the validated `historical_spain.csv` artifact produced by historical-data-validation run [43672336819](https://github.com/Baltas80/Kini-/actions/runs/43672336819).

- Source: Football-Data.co.uk.
- Competitions: `SP1` (LaLiga) and `SP2` (Segunda).
- Seasons: `2021`, `2122`, `2223`, `2324`, `2425`, `2526`, `2627`.
- Fixtures in source artifact: 5,311.
- Unique provider team labels: 56.
- Home/away team references: 10,622.
- CSV SHA-256: `a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab`.
- GitHub artifact SHA-256: `c194edf11b0733a203a9559e20e8a2b7e43a8d35a4108eacd2c4da6dae49174d`.

The stable `team_id` is an internal key. `canonical_name` is the registry's selected Football-Data display label; it is not a claim that the label is the club's legal or official name. Competition/season participations record only observations in this source artifact.

## Resolution policy

The API is `TeamIdentityRegistry.resolve(name, source=..., competition_id=..., season=..., gender=...)`.

1. Aliases are provider-scoped. A Football-Data alias does not automatically resolve a same-spelled SELAE or other-provider label.
2. Matching is exact after Unicode NFKC normalization, case folding and whitespace collapse.
3. Accents and punctuation are preserved. `Málaga` does not silently match `Malaga`; spelling variants require an explicit, reviewed alias.
4. If competition and season are supplied, the exact participation pair must exist for that team.
5. Unknown labels return `None`; multiple exact candidates raise `AmbiguousTeamIdentityError`.
6. No fuzzy matching, edit-distance threshold, date proximity or model-based guess is used.

The default registry contains only the 56 male-team labels observed in Football-Data SP1/SP2. No SELAE alias is pre-populated. SELAE `(M)/(F)` markers are preserved by the coupon importer, but are not treated as a verified competition or identity mapping here. Female teams, cup/European teams and teams outside the current historical source remain unresolved until a suitable source-specific alias and competition scope are independently verified.

## Validation

Run after building the historical dataset:

    python -m scripts.validate_team_identity_registry --csv data/historical_spain.csv

The validator checks both home and away labels using the source, competition and season fields. It exits non-zero on any unresolved or ambiguous reference. It does not modify the source CSV, coupon records, model features or training joins.

Tests:

    pytest -q tests/test_team_identity.py

## Integration boundary

This registry is an identity layer only. It is not yet wired into model fitting or historical training features. The next data-integration step is to establish independently verified source aliases, kickoff dates, competition IDs and season context for each SELAE fixture. Only resolved fixtures may be joined to training data; unresolved records must remain visible and excluded from model fitting.


## SELAE cross-provider reconciliation

The canonical registry deliberately contains no inferred SELAE aliases. A separate fixture-level crosswalk is required because an escrutinio draw date is not a kickoff date, and coupon display labels/category markers do not establish competition or team identity.

The reconciliation contract and CLI are documented in [SELAE_RECONCILIATION.md](SELAE_RECONCILIATION.md). Every played coupon fixture must match an exact SELAE display-name pair and resolve both Football-Data labels under an explicit competition, season and gender. The crosswalk must also contain a timezone-aware kickoff timestamp and independent HTTPS schedule evidence. Unknown, ambiguous, out-of-scope or mismatched records are excluded and reported; no fuzzy matching is used.

The current crosswalk contains ten independently verified mappings from the 8 November 2026 coupon (positions 1–10), each supported by an official club schedule page and an exact SP1/2627 or SP2/2627 Football-Data row. Only the three women's fixtures remain unresolved; the postponed public-draw fixture is excluded. No full-coupon training-label export is permitted while any played fixture remains unresolved. Even after reconciliation, goals and 1/X/2 are target labels only, and downstream features must be computed strictly before kickoff.
