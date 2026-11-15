# Phase 1 audit — data integrity, temporal validation and model comparison

Date: 2026-11-15  
Repository: Baltas80/Kini-  
Working branch: `audit/phase-1-temporal-validation`  
Base branch: `master`  
Backtest code commit evaluated: `a21aedd7eb42f0e5f3d19238a4106909448136a2`  
Latest fully validated model-code baseline: `a21aedd7eb42f0e5f3d19238a4106909448136a2`  
Latest validated CI/data head: `de49624a97567237ba789a3d39dc2f2eab543aca` (54 tests passed; historical-data validation passed on 5,311 rows; conservative market-timing backtest is pending in run [43666544162](https://github.com/Baltas80/Kini-/actions/runs/43666544162)). The previous fully validated model-metric baseline remains `a21aedd7eb42f0e5f3d19238a4106909448136a2` until the new full backtest is accepted.

## Executive status

- **P0 backtesting:** validated. Dixon-Coles, ML, the market-assisted ensemble, fixed DC/ML-only ensemble and adaptive DC/ML-only ensemble each generated 5,011/5,011 predictions with zero prediction errors.
- **P1 historical ingestion:** validated on 5,311 completed matches, with the integrity profile passing.
- **P2 temporal validation:** same-calendar-day exclusion, date-based refit cadence and strictly pre-match ML feature history are implemented and tested. The market snapshot screen now fails closed for all Friday/Tuesday fixtures because Football-Data's `Time` field has no documented timezone; the same eligibility predicate gates market use in forecasts and comparisons. The full backtest is pending.
- **P6 ticket optimizer:** probability validation, budget constraints, exhaustive small-budget DP comparison, minimum stake and Pleno al 15 aggregation are implemented and CI-tested.
- **Predictive performance:** the last fully validated multi-book pre-closing benchmark remains materially better than every model configuration. The conservative Friday/Tuesday exclusion changes the market-assisted ensemble sample and is awaiting a new full comparison.
- **Ensemble weighting:** fixed and rolling prequential DC/ML-only comparisons are now evaluated. The adaptive variant did not improve Brier or Log Loss over the fixed DC/ML blend and is not selected as the default.
- **Calibration diagnostics:** one-vs-rest reliability, prevalence, mean predicted probability, binary Brier/Log Loss and ECE by 1/X/2 class and football season are implemented on out-of-sample forecasts.
- **Pinnacle data quality:** PSH/PSD/PSA are excluded from market inputs for match dates on/after 2025-07-23, following the provider's stale-feed warning; the full backtest passed with unchanged market coverage.
- **Prequential calibration experiment:** a regularized multinomial vector-bias/shared-scale calibrator is implemented for every model and the market. It is fitted only on prior OOF forecasts, with a 500-row warm-up, 1,500-row rolling window, minimum 20 observations per class and refits every 30 forecast dates. Same-day outcomes are appended only after the entire date has been forecast. Its updated full walk-forward evaluation completed in run [43657960317](https://github.com/Baltas80/Kini-/actions/runs/43657960317): 4,480 post-warm-up forecasts per model and 33 successful refits after the Pinnacle data-quality correction. It remains experimental because results vary by model and season; it is not selected as a production default.
- **Not complete:** exact per-fixture odds-capture timestamps/timezone provenance, canonical team identity, correlation-aware ticket coverage and expected-payout modelling.

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

GitHub Actions run: [43657960317](https://github.com/Baltas80/Kini-/actions/runs/43657960317)  
Code commit evaluated: `a21aedd7eb42f0e5f3d19238a4106909448136a2`

- Generated history: 5,311 completed fixtures.
- Initial training sample: 300 matches.
- Test sample: 5,011 fixtures.
- Test period: 2020-12-11 through 2026-11-09.
- Refit cadence: every 30 forecast dates.
- Prediction errors: 0 for all five model configurations.
- Every model and the market has 5,011 observations on the common sample.
- Workflow acceptance: `BACKTEST_ACCEPTANCE_OK: 5011 fixtures for dc, ml, ensemble, ensemble_dc_ml, ensemble_dc_ml_adaptive`.

| Model | Accuracy | Multiclass Brier | Log Loss | RPS* | ECE** |
|---|---:|---:|---:|---:|---:|
| Dixon-Coles | 0.4817 | 0.6167 | 1.0278 | 0.2082 | 0.0114 |
| ML | 0.4404 | 0.6452 | 1.0709 | 0.2198 | 0.0453 |
| Ensemble (DC/ML/LAE/market) | 0.4825 | 0.6134 | 1.0226 | 0.2069 | 0.0117 |
| Fixed DC/ML-only | 0.4772 | 0.6158 | 1.0264 | 0.2080 | 0.0108 |
| Adaptive DC/ML-only | 0.4777 | 0.6160 | 1.0267 | 0.2080 | 0.0100 |
| multi-book pre-closing | **0.5081** | **0.5980** | **1.0002** | **0.2002** | 0.0257 |

* RPS is secondary because 1/X/2 are nominal outcomes rather than a naturally ordinal scale.  
** ECE is maximum-confidence expected calibration error with 10 equal-width bins; it is not a complete class-wise calibration assessment.


### Class-wise and seasonal calibration diagnostics

Commit `4508e903dbdee409e4f21571377de4626cd4ef92` adds one-vs-rest diagnostics for each 1/X/2 outcome:
- Class prevalence and mean predicted probability.
- Binary Brier score and binary Log Loss.
- Equal-width reliability bins with count, mean forecast probability and observed frequency.
- Class-wise ECE, weighted by bin population.
- Seasonal slices using July-June football seasons.
- Separate seasonal model-versus-market diagnostics on the exact common market-available fixture sample.

These diagnostics consume only walk-forward out-of-sample predictions. All fixtures on a forecast date are evaluated before any of their outcomes enter subsequent history. No calibrator is fitted or applied by this change; the output measures reliability and exposes class/season weaknesses without changing forecasts. A future calibrator must be trained only on earlier out-of-sample predictions and selected by proper scoring rules on a later untouched period.



### Experimento de calibración prequential — implementado

El calibrador aplica:

\`softmax(scale * log(p) + class_bias)\`

Utiliza una escala positiva compartida y tres sesgos por clase cuya suma es cero (dos parámetros libres). Se ajusta mediante máxima verosimilitud regularizada con SciPy L-BFGS-B y contracción hacia la transformación identidad.

Configuración predeterminada del walk-forward:
- Historial OOF previo mínimo: 500 predicciones.
- Ventana móvil de ajuste: 1.500 predicciones.
- Soporte mínimo por clase: 20 resultados de cada signo (1/X/2).
- Reajuste: cada 30 fechas de pronóstico.
- Hasta disponer de un ajuste válido, las probabilidades permanecen sin modificar.
- Cada configuración de modelo y el mercado mantienen su propio historial y calibrador.
- Las métricas originales y calibradas se calculan sobre exactamente los mismos partidos posteriores al calentamiento.
- La comparación adicional modelo/mercado utiliza solo partidos para los que ambos calibradores ya estaban ajustados.

Las pruebas incluyen un conjunto sintético con sesgo conocido y un bloque de test independiente, además de una prueba de regresión que demuestra que los resultados de la fecha actual no entran en el ajuste de esa misma fecha.

El workflow histórico rechaza muestras calibradas vacías, tamaños distintos entre muestras originales y calibradas, calibradores sin ajuste válido o comparaciones comunes con el mercado inexistentes. La aceptación comprueba que el experimento se ejecutó; no exige que mejore las métricas. Solo se promoverá si reduce Brier y Log Loss fuera de muestra sobre la misma muestra temporal. El backtest completo actualizado terminó correctamente en el run [43657960317](https://github.com/Baltas80/Kini-/actions/runs/43657960317); sus métricas y la decisión de no promover el calibrador se documentan más abajo.

### Adaptive DC/ML weighting

The adaptive ensemble selects its Dixon-Coles weight once per forecast date using only earlier out-of-sample predictions:
- Rolling history window: 1,000 prior forecasts.
- Minimum history before adaptation: 300 prior forecasts.
- Candidate grid: 0.00–1.00 in 0.025 increments, plus the fixed prior.
- Objective: mean multiclass log loss plus a quadratic penalty of 0.02 toward the prior DC weight (0.77333).
- Weight updates: 1,021 forecast dates.
- Mean DC weight: 0.82925; median: 0.825; range: 0.725–0.975; final weight: 0.75.
- The complete per-date weight trace is included in the backtest JSON artifact.

The evaluator selects one weight before each calendar date and appends that date's outcomes only after all its fixtures have been forecast. Therefore, no same-day result can affect another fixture's weight.

### Interpretation

- The multi-book pre-closing benchmark outperforms every model configuration on accuracy, Brier and Log Loss.
- The market-assisted ensemble is marginally better than Dixon-Coles on Brier and Log Loss, but not accuracy; this does not establish a meaningful predictive advantage.
- ML remains materially weaker than Dixon-Coles and market.
- The fixed model-only DC/ML blend slightly improves Brier and Log Loss relative to Dixon-Coles but has lower accuracy.
- The adaptive DC/ML blend has slightly higher accuracy than the fixed model-only blend, but worse Brier and Log Loss. Its ECE is lower, but ECE alone is insufficient to claim better calibration. The adaptive method is retained as an experiment, not selected as the production default.
- No result establishes that model probabilities are profitable or that they outperform market prices at an executable betting cutoff.

### Odds provenance clarification — 2026-11-15

The official Football-Data notes define `B365H/D/A` as **pre-closing** Bet365 odds; the closing equivalents are `B365CH/CD/CA` (the additional `C` marks closing). The current parser in `kini_engine/dataio.py::_market_from_row` averages normalized implied probabilities from the pre-closing triples `B365H/D/A`, `WHH/WHD/WHA`, `VCH/VCD/VCA` and `PSH/PSD/PSA` when available. It does not use the corresponding closing columns (`B365CH/CD/CA`, `WHCH/WHCD/WHCA`, `VCCH/VCCD/VCCA`, `PSCH/PSCD/PSCA`). Therefore every result labelled “market” in the current backtests is a **multi-book pre-closing snapshot benchmark**, not a closing-odds benchmark.

Football-Data states that since 2019/20 it publishes two sets: an initial set collected after market opening at scheduled times, and a separate closing set. Its fixtures page specifies that weekend odds are collected on Fridays generally no later than 17:00 British Standard Time, and midweek odds on Tuesdays no later than 13:00 British Standard Time. The historical match CSV does not store a per-fixture capture timestamp. The scheduled policy supports treating these pre-closing bookmaker triples as a pre-match snapshot reference, but does not prove the exact capture time for every fixture, reschedule or operational cutoff, nor guarantee an executable price. Football-Data also warns that its Pinnacle public feed has been systematically stale since 2025-07-23. The parser now excludes PSH/PSD/PSA on and after that date; the current data contains 1,101 post-cutoff fixtures, 385 with a complete Pinnacle triple, while Bet365 odds remain available for all 1,101.

A raw audit of the 5,311-row dataset found 7 Friday fixtures whose `Time` field is earlier than 17:00 and no Tuesday fixtures earlier than 13:00. The timezone of the CSV `Time` field is not specified in the glossary, and the collection time is only an upper bound; these 7 fixtures are therefore **temporally ambiguous**, not proven leakage and not proven safe. The current loader also drops `Time` from `Match.detail`. Next implementation: preserve kickoff time/timezone metadata, add an explicit market-availability flag, and exclude ambiguous rows from strict market-feature comparisons unless capture evidence resolves them.

Sources: [Football-Data odds/data notes](https://football-data.co.uk/data), [column glossary](https://football-data.co.uk/notes.txt), [fixture collection schedule](https://football-data.co.uk/matches.php).

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

Código predictivo validado: `a21aedd7eb42f0e5f3d19238a4106909448136a2`. Último commit de código/tests validado: `491b40aa6a399f7535284c1562d8784606035b6d`; los commits posteriores solo modifican documentación.

- [CI del HEAD validado](https://github.com/Baltas80/Kini-/actions/runs/43658147899): **47 tests superados**, cuatro advertencias deprecatorias de penaltyblog 1.13.1 bajo NumPy 2.5.
- [Validación histórica del HEAD validado](https://github.com/Baltas80/Kini-/actions/runs/43658147908): 5.311 partidos, integrity_passed true, cero duplicados y cobertura de temporada actual.
- [Backtest histórico tras excluir Pinnacle obsoleto](https://github.com/Baltas80/Kini-/actions/runs/43657960317): 5.011 predicciones para cada una de las cinco configuraciones, cero errores, 4.480 comparaciones calibradas/raw por configuración, 33 ajustes por calibrador y PREQUENTIAL_CALIBRATION_OK.

Los tres workflows usan filtros por rutas y concurrencia por rama: CI cubre código, tests, datos, dependencias y cambios de workflows; validación de datos cubre sus entradas reales; el backtest completo solo se ejecuta ante cambios de modelo/datos/dependencias, además de su ejecución manual y semanal. Esto evita repetir validaciones costosas por cambios documentales y cancela ejecuciones duplicadas push/PR.

El constructor de la ingesta consolida el DataFrame normalizado antes de añadir `_ParsedDate` y concatena `League`, `Season` y `SourceURL` como un único bloque de metadatos. CI detectó que el primer intento había comentado accidentalmente la asignación de la fecha parseada; el commit `2963e7d` la restauró. La implementación corregida conserva las 5.311 filas y elimina los avisos de fragmentación de pandas.

## Remaining work — priority order

1. **Calibration correction:** completed. The prequential calibrator is validated but not promoted to the main ensemble because the primary ensemble does not improve both proper scores and seasonal effects are mixed.
2. **Odds provenance:** the benchmark is multi-book pre-closing. Pinnacle is excluded from 2025-07-23 onward; 7 early-Friday fixtures remain temporally ambiguous because the CSV does not state the timezone or exact capture timestamp. Preserve Time, add a market-availability flag, and separately evaluate provider consensus and closing columns without feeding closing prices into an earlier forecast.
3. **Data identity:** audit aliases, renamed clubs and cross-season continuity; profile checks currently normalize text but do not maintain a canonical team-identity registry.
4. **Ticket economics:** test cross-match dependence and realistic system/reduced-bet constraints. Do not claim expected payout or profitability without a defensible payout model and prize-pool data.
5. **Model research:** retain the adaptive DC/ML weighting as an experiment; do not promote it unless a prequential or nested temporal evaluation demonstrates improvement in proper scoring rules.
6. **Ingestion efficiency:** DataFrame consolidation and metadata concatenation are **validated**; latest data validation retains 5,311 rows and the fragmentation warnings are absent.

## Phase 1 acceptance status

1. Same-date fixtures excluded from one another's training history — **validated**.
2. Walk-forward test count and date coverage reported — **validated**.
3. Model/market comparison uses the same 5,011 fixtures — **validated**.
4. Historical input validation rejects malformed dates, duplicate fixtures, incomplete scores and inconsistent labels — **implemented and CI-tested**.
5. Source/cache provenance and current-season coverage — **validated on 5,311 fixtures**.
6. Non-empty Dixon-Coles, ML and ensemble backtests — **validated, 5,011 predictions each**.
7. Optimizer probability validation and small-budget DP exactness — **implemented and CI-tested**.
8. Fixed and adaptive independent model-only ensembles — **implemented and validated on 5,011 walk-forward fixtures**; adaptive weighting did not improve Brier or Log Loss over the fixed blend. Class-wise and seasonal one-vs-rest diagnostics — **implemented and validated on 5,011 OOF fixtures**. Prequential calibrator — **implemented, same-day isolation and full backtest validated; not promoted because the main ensemble does not improve and seasonal effects are mixed**. Timestamped odds and expected-payout model — **pending**.

## Integration status

- PR #5 (resilient ingestion): [open](https://github.com/Baltas80/Kini-/pull/5).
- PR #6 (temporal validation and models): [open, draft](https://github.com/Baltas80/Kini-/pull/6).
- PR #6 branch includes PR #5 as the second parent of the merge commit. For the cleanest eventual integration, merge PR #5 first and then PR #6.
- No PR has been merged.
- `master` remains at `ef331c3a3f50220b5d2b1a71900a2d7003b259c4` and has not been modified.

## Execution checkpoint — 2026-11-15

- Model-code commit: `a21aedd7eb42f0e5f3d19238a4106909448136a2`; latest validated code/test head: `491b40aa6a399f7535284c1562d8784606035b6d`; subsequent documentation-only commits record the results.
- CI: 47 tests passed on the current branch head; four third-party NumPy/penaltyblog deprecation warnings remain.
- Data validation: 5,311 completed fixtures, integrity passed, duplicate checks and current-season coverage passed.
- Full walk-forward backtest: 5,011/5,011 predictions for all five model configurations, zero errors; calibrated/raw comparisons use 4,480 identical post-warm-up fixtures and 33 prior-OOF fits.
- Pinnacle PSH/PSD/PSA is excluded from the market blend for match dates on/after 2025-07-23. The new backtest confirms that the market remains non-empty and all acceptance gates pass.
- The primary ensemble remains uncalibrated; the experiment is retained for model-specific research only.

## Prequential calibration results — run 43657960317

The full workflow completed successfully on 2026-11-15 for model-code HEAD `a21aedd7eb42f0e5f3d19238a4106909448136a2`. It rebuilt the historical source, passed the first-ML diagnostic, produced all five model forecasts and passed both backtest acceptance gates after the Pinnacle cutoff correction.

- Source history: 5,311 completed matches.
- Initial training: 300 matches.
- Walk-forward test: 5,011 matches, 2020-12-11 to 2026-11-09.
- Prediction errors: zero for Dixon-Coles, ML, market-assisted ensemble, fixed DC/ML blend and adaptive DC/ML blend.
- Calibration: 4,480 post-warm-up forecasts per model and for the market; raw and calibrated scores use identical fixtures.
- Calibration refits: 33 per model/market; final fit used 1,500 prior OOF rows and was dated 2026-10-26.
- Same-calendar-day outcome exclusion: true. Workflow markers: `BACKTEST_ACCEPTANCE_OK` and `PREQUENTIAL_CALIBRATION_OK`.

| Model | n | Raw Brier | Calibrated Brier | Δ Brier | Raw Log Loss | Calibrated Log Loss | Δ Log Loss |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dixon-Coles | 4,480 | 0.615105 | 0.614391 | -0.000714 | 1.025271 | 1.023953 | -0.001317 |
| ML | 4,480 | 0.639687 | 0.633407 | -0.006279 | 1.061780 | 1.051484 | -0.010296 |
| Ensemble DC/ML/LAE/market | 4,480 | 0.612291 | 0.612432 | +0.000141 | 1.020870 | 1.021008 | +0.000138 |
| Fixed DC/ML-only | 4,480 | 0.614517 | 0.614567 | +0.000050 | 1.024162 | 1.024174 | +0.000012 |
| Adaptive DC/ML-only | 4,480 | 0.614591 | 0.614550 | -0.000041 | 1.024310 | 1.024157 | -0.000153 |
| multi-book pre-closing | 4,480 | 0.598956 | 0.598057 | -0.000899 | 1.001482 | 0.999976 | -0.001506 |

Negative deltas indicate improvement. The multi-book pre-closing benchmark remains materially better than every calibrated model on both proper scoring rules. On the same 4,480 common fixtures, the calibrated market scores 0.598057 Brier / 0.999976 Log Loss; the best calibrated model configuration is the raw market-assisted ensemble at 0.612432 / 1.021008.

### Promotion decision

**Do not promote the calibrator as the default prediction layer.** The primary market-assisted ensemble becomes slightly worse on both Brier and Log Loss after calibration. The fixed model-only blend also becomes marginally worse. Standalone Dixon-Coles and ML improve overall, but the improvement is not seasonally stable: in 2026/27 (259 forecasts), the classwise-summed multiclass Brier changes from 0.596009 to 0.598636 for DC, from 0.592878 to 0.594152 for the main ensemble, and from 0.595670 to 0.597484 for the fixed DC/ML blend. The market improves from 0.574361 to 0.572479 in that season. The adaptive blend's overall gain is negligible and its 2026/27 Brier also worsens (0.596068 to 0.598392).

The result validates the prequential implementation and the experiment, not a universal calibration benefit. Keep raw probabilities as the production default; retain the calibrator behind the experiment/backtest path until an independent later holdout or nested temporal selection demonstrates a stable gain for a specific model.

## CI efficiency

CI, historical-data validation and historical backtesting now use input-specific path filters and per-branch concurrency. CI runs for code, tests, data, dependencies and workflow changes; data validation runs when its builder, parser, data or dependencies change; the expensive walk-forward backtest runs when model/data/scripts/dependencies change. Documentation-only changes do not launch these jobs, and duplicate push/PR runs are cancelled. Manual dispatch and the weekly backtest schedule remain available.

## Reproducibility and team-label audit — 2026-11-15

### Exact backtest reproducibility

A second full execution, [run 43657293261](https://github.com/Baltas80/Kini-/actions/runs/43657293261), completed successfully on a documentation-only commit before the Pinnacle cutoff correction. It reproduced **exactly** every aggregate metric and calibration summary from run 43652723196, demonstrating deterministic reproducibility for that pre-correction code/data pair. The current authoritative market baseline is run 43657960317; the older reproducibility result is retained as historical evidence, not as the current odds definition.

### Football-Data team labels

A direct audit of the 5,311-row artifact found:
- 7 LaLiga seasons with exactly 20 distinct team labels each.
- 7 Segunda seasons with exactly 22 distinct team labels each.
- 31 distinct LaLiga labels and 44 distinct Segunda labels across the full period.
- No collisions under the same NFKC + whitespace normalization + case-folding used by `_team_key`.
- No obvious alias variants within this Football-Data sample. Reserve teams such as `Sociedad B`, `Celta B` and `Villarreal B` remain distinct labels.

This closes the immediate alias-variant check for the current source sample, but not canonical identity management across external providers or future renamed clubs. A persistent team-ID registry remains pending before adding other data sources.
 
## Pinnacle feed quality correction — run 43657960317

Football-Data's official data page warns that its public Pinnacle odds feed has been systematically out of date since 2025-07-23. The parser now excludes the Pinnacle pre-closing triple from that date onward while retaining it before the cutoff. A regression test checks both 2025-07-22 and 2025-07-23. The source dataset has 1,101 fixtures on/after the cutoff, 385 with a complete Pinnacle triple; Bet365 pre-closing odds are present for all 1,101, so the market sample remains 5,011/5,011.

Impact against the immediately preceding backtest with Pinnacle included:
- Multi-book market: Brier 0.598036 → 0.598040; Log Loss 1.000186 → 1.000165; accuracy 0.508481 → 0.508082.
- Main ensemble: Brier 0.613354 → 0.613356; Log Loss 1.022650 → 1.022649; accuracy unchanged at 0.482538.
- No material predictive improvement is claimed. The exclusion is justified by provider-quality evidence; its measured score impact is negligible.

The market benchmark remains a multi-book average of per-book no-vig probabilities, not Football-Data's AvgH/AvgD/AvgA consensus columns. Comparing that provider consensus separately is still open research.


## Market timestamp conservatism — fail-closed correction (2026-11-15)

The loader preserves Football-Data's raw `Time` value as `Match.detail.kickoff_time` and records its timezone as `unspecified`; it does not interpret the field as UTC, BST or local Spanish time. The official glossary defines `Time` only as the match kickoff time, while the provider states that weekend odds are collected on Fridays and midweek odds on Tuesdays. Because the CSV does not document the kickoff timezone, comparing the raw value directly with a BST collection cutoff would assume a timezone that the source does not provide.

The classifier therefore uses a stricter rule:

- `ambiguous`: every Friday or Tuesday fixture with valid odds and a parseable kickoff time, regardless of the displayed hour, because the snapshot may be collected on the same calendar day and the two clocks cannot be compared safely.
- `schedule_compatible`: fixtures on other weekdays with a parseable kickoff time, where the published collection day precedes the fixture date. This remains a schedule screen, not an exact timestamp guarantee.
- `unknown`: kickoff time/date cannot be parsed.
- `unavailable`: no valid pre-closing market probabilities exist.

A single `Match.has_temporally_eligible_market` predicate now gates market use in the main ensemble, explicit market mode, surprise diagnostics, market baseline and strict benchmark. Raw odds remain attached to the match only so the unfiltered diagnostic can report them; ambiguous odds cannot influence a prediction. CI also rejects non-zero prediction-error counters and checks that all five model configurations and the strict market benchmark use exactly the same eligible fixture sample.

Validation on commit `de49624a97567237ba789a3d39dc2f2eab543aca`: CI **54 passed, 4 dependency deprecation warnings** ([run 43666547677](https://github.com/Baltas80/Kini-/actions/runs/43666547677)); historical data validation **5,311 completed fixtures, integrity_passed=true, zero duplicates** ([run 43666547684](https://github.com/Baltas80/Kini-/actions/runs/43666547684)). The full walk-forward backtest is still running ([run 43666544162](https://github.com/Baltas80/Kini-/actions/runs/43666544162)); its strict market sample and new metrics are intentionally not reported until the workflow completes.

This conservative rule removes the prior assumption that a kickoff time without timezone can be compared directly with the provider's BST cutoff. Exact per-fixture odds-capture timestamps are still unavailable, so the market benchmark remains schedule-screened rather than timestamp-verified.

## Latest strict-market backtest — run 43666544162 (2026-11-15)

The full workflow completed successfully on commit `de49624a97567237ba789a3d39dc2f2eab543aca`. The job log contains all three acceptance markers: `BACKTEST_ACCEPTANCE_OK`, `MARKET_TEMPORAL_ACCEPTANCE_OK` and `PREQUENTIAL_CALIBRATION_OK`. The downloadable artifact is `historical-backtest/backtest-results.json` (SHA-256 `7d0fe5d9baa63d07a4201e87c9fa35c369d58aff57b55d2b4a7eac42c03722ed`).

- Historical dataset: 5,311 completed fixtures; initial training: 300.
- Walk-forward test: 5,011 fixtures, 2020-12-11 through 2026-11-09; refit every 30 forecast dates.
- Dixon-Coles, ML, main ensemble, fixed DC/ML-only blend and adaptive DC/ML-only blend: **5,011/5,011 predictions each; zero prediction errors**.
- Market odds present: 5,011; schedule-eligible: **4,424**; ambiguous/excluded: **587** (all Friday/Tuesday fixtures with odds, because kickoff timezone/capture timestamp is not documented).
- Strict market acceptance: all five model configurations and the market are compared on exactly the same 4,424 fixtures. This is a schedule-screened benchmark, not timestamp-verified or an executable-price benchmark.

### Common 4,424-fixture comparison

| Model | Accuracy | Multiclass Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Dixon-Coles | 0.4806 | 0.6164 | 1.0275 | 0.2080 | 0.0163 |
| ML | 0.4383 | 0.6469 | 1.0733 | 0.2204 | 0.0487 |
| Ensemble DC/ML/LAE/eligible market | 0.4815 | 0.6135 | 1.0229 | 0.2068 | 0.0148 |
| Fixed DC/ML-only | 0.4758 | 0.6160 | 1.0267 | 0.2079 | 0.0127 |
| Adaptive DC/ML-only | 0.4758 | 0.6162 | 1.0270 | 0.2080 | 0.0128 |
| Multi-book pre-closing market | **0.5072** | **0.5975** | **0.9994** | **0.1999** | 0.0242 |

The market wins on accuracy, multiclass Brier, Log Loss and RPS on the identical 4,424-fixture sample. The main ensemble is the best model-only-or-assisted configuration by Brier/Log Loss, but remains materially behind the market. The model-only blends do not improve on Dixon-Coles in this strict sample. Lower ECE for a model is not enough to outweigh worse proper scoring rules.

### Prequential calibration — exact 3,847-fixture model/market intersection

The post-warm-up model/market comparison contains 3,847 identical fixtures. Raw and calibrated forecasts are compared on those same fixtures:

| Configuration | Raw Brier | Calibrated Brier | Raw Log Loss | Calibrated Log Loss |
|---|---:|---:|---:|---:|
| Dixon-Coles | 0.613791 | 0.613232 | 1.023639 | 1.022458 |
| ML | 0.638003 | 0.632559 | 1.059609 | 1.050517 |
| Main ensemble | 0.611197 | 0.611412 | 1.019558 | 1.019795 |
| Fixed DC/ML-only | 0.613386 | 0.613535 | 1.022816 | 1.022945 |
| Adaptive DC/ML-only | 0.613531 | 0.613585 | 1.023040 | 1.022991 |
| Market | 0.597564 | 0.596714 | 0.999533 | 0.998094 |

There are 33 model-calibrator refits (4,480 post-warm-up forecasts per model); the market has 32 refits and its exact common intersection is 3,847 fixtures. Calibration improves standalone DC and ML aggregate scores on this intersection, but worsens the main ensemble and fixed blend. It is therefore **not promoted** as the production default. The market remains better than every model configuration on both proper scoring rules.

### Validation status and decision

- CI: **54 tests passed**, four third-party deprecation warnings — [run 43666547677](https://github.com/Baltas80/Kini-/actions/runs/43666547677).
- Historical data: **5,311 fixtures**, zero duplicates/incomplete scores and `integrity_passed=true` — [run 43666547684](https://github.com/Baltas80/Kini-/actions/runs/43666547684).
- Full walk-forward: [run 43666544162](https://github.com/Baltas80/Kini-/actions/runs/43666544162), all acceptance markers passed.
- Artifact: [historical-backtest](https://github.com/Baltas80/Kini-/actions/runs/43666544162).

**Decision:** keep raw main-ensemble probabilities as the default; do not promote calibration, adaptive DC/ML weighting or a claim of market outperformance. Keep the market benchmark labelled schedule-screened pre-closing. No profitability claim is supported.

### P0/P5 status after run 43666544162

P0 is validated for non-empty, correctly keyed walk-forward forecasts across all five configurations, with zero prediction errors and reproducible machine-readable output. P5 is validated as a fair same-fixture comparison under the conservative schedule screen; it establishes that the current model configurations do not beat the available market benchmark. Exact bookmaker capture timestamps remain unavailable.

### Next priority — P6 ticket validation

The current optimizer maximizes product coverage of selected 1/X/2 marginal masses subject to a maximum column budget, using an exact dynamic programme under an explicit independent-match approximation. Existing tests compare the DP with exhaustive search for a small budget and validate the 14-match/Pleno al 15 split. Remaining work is not to imply correlation-aware or economic optimization without data: obtain historical official Quiniela coupon composition and prize/pool data, then test cross-match dependence and full SELAE system/reduced-bet constraints. Until those inputs exist, the optimizer must remain labelled as independent-match coverage only, not expected payout or profitability.
