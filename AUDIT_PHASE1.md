# Phase 1 audit — data integrity, temporal validation and model comparison

Date: 2026-11-15  
Repository: Baltas80/Kini-  
Working branch: `feat/selae-fixture-reconciliation`  
Base branch: `feat/canonical-team-identity-registry` (PR #9 stacked on PR #8; `master` untouched)  
Backtest code commit evaluated: `a21aedd7eb42f0e5f3d19238a4106909448136a2`  
Latest fully validated model-code baseline: `a21aedd7eb42f0e5f3d19238a4106909448136a2`  
Latest successful historical-data validation: [run 43713637624](https://github.com/Baltas80/Kini-/actions/runs/43713637624)  
Latest Liga F archive import: [run 43713031093](https://github.com/Baltas80/Kini-/actions/runs/43713031093)  
Implementation/test CI: [run 43713913706](https://github.com/Baltas80/Kini-/actions/runs/43713913706) passed; the subsequent audit-only update also passed [run 43714148651](https://github.com/Baltas80/Kini-/actions/runs/43714148651) with 121 tests and four upstream deprecation warnings.

## Executive status

- **P0 backtesting:** validated. Dixon-Coles, ML, the market-assisted ensemble, fixed DC/ML-only ensemble and adaptive DC/ML-only ensemble each generated 5,011/5,011 predictions with zero prediction errors.
- **P1 historical ingestion:** Football-Data validated on 5,311 completed matches. Separately, the official Liga F importer passed live validation on 1,040 fixtures (1,039 played, one postponed), with 1,040 unique IDs and `training_eligibility.eligible=false`; it remains evidence-only.
- **P2 temporal validation:** same-calendar-day exclusion, date-based refit cadence and strictly pre-match ML feature history are implemented and tested. The market snapshot screen fails closed for all Friday/Tuesday fixtures because Football-Data's `Time` field has no documented timezone; the same eligibility predicate gates market use in forecasts and comparisons. The latest full walk-forward rerun passed in [43713524597](https://github.com/Baltas80/Kini-/actions/runs/43713524597); exact odds-capture timestamps remain unavailable.
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

`softmax(scale * log(p) + class_bias)`

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

### P6 optimizer input-contract hardening — 2026-11-15

A final review found that `TicketOptimizer.optimize` used `prediction.get(sign, 0.0)`. This silently accepted an incomplete probability mapping when the remaining two values happened to sum to one, effectively treating an omitted outcome as a proven zero-probability event. The optimizer now rejects any match missing one of the required `1`, `X`, or `2` keys before validating numeric values. A regression test removes the `2` key while leaving the other two probabilities summing to one and verifies that the input is rejected. This is an input-integrity correction only; it does not change the optimization objective or claim correlation-aware coverage. The DP still maximizes independent-match full-ticket coverage under a maximum column budget.

## Latest optimizer hardening validation — 2026-11-15

- Code: `c6d42a004a3f7657e416dc443fb17228f81b11d6` rejects incomplete 1/X/2 mappings instead of silently substituting zero for a missing sign.
- Regression test: `877867655899439e7a296a94633e6b477d944740` removes one sign while the remaining two sum to one and verifies that the optimizer raises `ValueError`.
- Branch head including the code, test and audit updates: `dcca16a7df7c91718ae6811133ff9613be66286e`.
- CI on the updated branch: **55 passed, 4 third-party deprecation warnings** — [run 43671694073](https://github.com/Baltas80/Kini-/actions/runs/43671694073).
- Historical data validation: **5,311 fixtures, `integrity_passed=true`** — [run 43671694061](https://github.com/Baltas80/Kini-/actions/runs/43671694061).
- The full strict-market walk-forward benchmark remains the accepted result from [run 43666544162](https://github.com/Baltas80/Kini-/actions/runs/43666544162). The optimizer input-contract change does not alter model fitting, forecasts, market inputs or ticket coverage calculations.

The optimizer still reports coverage only under its explicit independent-match approximation. Correlation-aware coverage and expected payout remain unvalidated until historical official coupon composition, outcome/pool data and applicable system rules are available.

## Market consensus comparison — AvgH/AvgD/AvgA versus per-book no-vig mean — 2026-11-15

A separate offline benchmark was run against the exact historical CSV artifact from data-validation run [43671694061](https://github.com/Baltas80/Kini-/actions/runs/43671694061). The test window was reconstructed as the 5,011 fixtures after the first 300 training rows (2020-12-11 through 2026-11-09). The same conservative schedule screen was applied: all Friday/Tuesday fixtures were excluded. Both methods were evaluated on the identical **4,424 fixtures**; all had valid odds for both definitions.

Two distinct constructions were compared:

1. **Current market:** calculate no-vig implied probabilities separately for each available pre-closing bookmaker triple (Bet365, William Hill, Victor Chandler and Pinnacle before 2025-07-23), then average the bookmaker probability vectors. Pinnacle is omitted on/after the documented stale-feed cutoff.
2. **Football-Data AvgH/AvgD/AvgA:** invert the provider's average odds and normalize the three implied probabilities to remove the resulting overround.

| Market construction | n | Accuracy | Multiclass Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|---:|
| Mean of per-book no-vig probabilities (current) | 4,424 | **0.50723** | **0.597504** | **0.999444** | **0.199876** | **0.024213** |
| No-vig normalized AvgH/AvgD/AvgA | 4,424 | 0.50633 | 0.597761 | 0.999913 | 0.200033 | 0.025796 |

The current per-book no-vig mean is marginally better on all five aggregate metrics. The absolute differences are small. A paired cluster bootstrap by calendar date (809 date clusters, 5,000 resamples, fixed seed 20261115) estimated AvgH/AvgD/AvgA minus the current method as:

- Brier difference: **+0.000257**, 95% interval [-0.000042, +0.000556].
- Log Loss difference: **+0.000470**, 95% interval [-0.000022, +0.000967].
- Accuracy difference: **-0.000904**, 95% interval [-0.002713, +0.000892].

All intervals include zero; the available sample does not establish a statistically reliable difference. Seasonal results are mixed, and the 2026/27 slice contains only 234 eligible fixtures. The experiment is raw (uncalibrated) and does not prove either construction is an executable price.

**Decision:** retain the current mean of per-book no-vig probabilities as the production benchmark. Do not replace it with AvgH/AvgD/AvgA, and do not blend the two: the aggregate gain is negligible and unsupported by the paired uncertainty analysis. Keep AvgH/AvgD/AvgA as a documented alternative benchmark for future independent holdout evaluation.

Reproduction input: artifact `kini-historical-data` from run 43671694061 (5,311 rows; source profile `integrity_passed=true`). The script was executed against that artifact with the 300-row initial-training boundary and the same 4,424 schedule-eligible fixtures; the reproduced current-market metrics match the accepted backtest run 43666544162 to floating-point precision.

### Latest regression status for the same branch head

- CI [run 43671814302](https://github.com/Baltas80/Kini-/actions/runs/43671814302): **55 passed**, four warnings (third-party NumPy/penaltyblog deprecation warnings).
- Historical data validation [run 43671814249](https://github.com/Baltas80/Kini-/actions/runs/43671814249): **5,311 fixtures**, `integrity_passed=true`, validation marker `DATA_VALIDATION_OK`.

## P6 direct-system constraints — 2026-11-15

A review of SELAE's official multiple-direct table found that the optimizer previously constrained only the product of selected signs to the caller's budget. It did not enforce the table's authorized maximum number of triples for each number of doubles, nor the 31,104-column maximum (7 doubles + 5 triples). This could allow a caller-supplied high budget to generate a combination not authorized by the direct-method table.

Implemented on the audit branch:
- Reworked the exact DP state to track `(double_count, triple_count)`.
- Enforced the Anexo I maximum triples-by-doubles table and 31,104 maximum.
- Enforced the official two-column minimum even if a caller attempts to configure a lower minimum.
- Exposed explicit double/triple counts, system method and maximum authorized columns in the result.
- Retained the independent-match coverage objective; no correlation or prize-pool assumptions were added.
- The current `KiniEngine.quiniela` chooses one Pleno al 15 category pair, so its multiplier remains 1. Multiple Pleno al 15 categories are not supported.

Regression tests cover the maximum authorized 7-double/5-triple combination, rejection above the direct-system maximum, rejection of a one-column minimum, and the existing exhaustive small-budget comparison.

Official source: SELAE, *Normas de la Quiniela y Elige 8* (October 2019), Anexo I, pp. 40–42, and final clause stating validity for subsequent seasons until replaced: https://www.selae.es/f/loterias/documentos/normativa/Normativa%20de%20los%20juegos/Normas_de_la_Quiniela_y_Elige8_Octubre_2019.pdf. Current SELAE normative-games index: https://www.selae.es/es/web-corporativa/normativa/normativa-de-los-juegos/normativa-de-los-juegos-web-corporativa.


## SELAE official coupon and prize data availability — 2026-11-15

A source investigation confirmed that SELAE publishes official date-specific result pages for current-season draws with the exact 14 coupon fixtures, home/away teams, full-time scores and 1/X/2 signs, plus the Pleno al 15 fixture and score. The official *escrutinios* pages also expose category winners and unit prizes. Verified examples:

- [18 October 2026](https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/la-quiniela-premios-y-ganadores-del-18-de-octubre-de-2026): 14 fixtures, including four women's fixtures, Pleno al 15 and six prize categories.
- [1 November 2026](https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/la-quiniela-premios-y-ganadores-del-01-de-noviembre-de-2026): 14 fixtures, scores/signs, Pleno al 15, winners and unit prizes.
- [4 November 2026](https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/la-quiniela-premios-y-ganadores-del-04-de-noviembre-de-2026): 14 European men's fixtures, showing that coupon composition is not limited to LaLiga/Segunda.
- [8 November 2026](https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/la-quiniela-premios-y-ganadores-del-08-de-noviembre-de-2026): 10 men's fixtures and four Liga F fixtures, with Pleno al 15 and prize distribution.

SELAE's [official result detail page](https://www.loteriasyapuestas.es/es/resultados?drawId=1116207004) also exposes, for the 8 November 2026 result page, bets received, advertised jackpot, total collection and total prizes. SELAE's [official press-release PDF for 8 November 2026](https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/NOTA_DE_PRENSA_LA_QUINIELA_08_11_26.pdf) independently confirms the collection and category results. The official [historical results search](https://www.loteriasyapuestas.es/es/resultados/quiniela) exposes date-range controls, but its results are loaded dynamically; the underlying request/response contract and reliable historical pagination have not yet been established. Directly guessing older date-slugged escrutinio URLs did not resolve reliably. The evidence therefore confirms current-season pages and official historical press-release PDFs, not a complete machine-retrievable historical coupon archive. No automated historical ingestion is claimed at this stage.

### Scope consequence

The validated Football-Data dataset contains LaLiga and Segunda only. It is suitable for those men's domestic-league model benchmarks, but it is **not a complete historical representation of actual Quiniela coupons**. The verified 2026/27 coupons include Liga F, European competitions and cup fixtures. A model trained only on LaLiga/Segunda cannot be described as fully covering those coupons; unseen-team fallback forecasts must be surfaced as low-information estimates, not treated as equivalent to trained-team forecasts.

Next P6/P1 work:
1. Establish a stable SELAE historical-results retrieval contract (date-range search or documented result endpoint), preserving source URL, retrieval timestamp, draw/jornada identifier and raw response hash.
2. Implement an importer with schema validation for 14 fixtures, Pleno al 15, results, prize tiers, collection and total prizes; reject incomplete or inconsistent draws.
3. Build an explicit competition/team identity registry and connect the coupon fixtures to competition-specific historical training data.
4. Only then evaluate actual-coupon coverage and payout distributions. Prize tiers, winners and unit prizes alone are insufficient to reconstruct expected payout without the applicable pool allocation, jackpot carry-over, ticket counts and system rules.

### Full-coupon coverage reporting

`TicketOptimizer.joint_coverage` remains the independent-match probability that at least one direct-system column covers all 14 1/X/2 outcomes. `KiniEngine.quiniela` now additionally reports `estimated_full_coupon_coverage_independent`, multiplying the 14-match coverage by the probability of the selected Pleno al 15 category. The output explicitly records `independent_all_14_matches_and_pleno15`; it is an approximation, not a correlation-aware estimate or an expected-payout metric.

The change is metadata/reporting only: it does not modify any model probability, optimizer selection, budget or historical benchmark.


## Latest coverage-reporting validation — 2026-11-15

The public `KiniEngine.quiniela` result now includes `estimated_full_coupon_coverage_independent`: the 14-match direct-system coverage estimate multiplied by the probability of the selected Pleno al 15 category. It also emits the explicit assumption identifier `independent_all_14_matches_and_pleno15`. The existing `ticket.joint_coverage` remains unchanged and continues to describe the 14-match system only. This output is not correlation-aware and does not estimate prize payout or profitability.

- Implementation: [`01fe0cf`](https://github.com/Baltas80/Kini-/commit/01fe0cfdb932edd9b24b45e0d6eed5e88f68910d).
- Regression test: [`83bc72f`](https://github.com/Baltas80/Kini-/commit/83bc72f6b3488bc558dc09d88c091b5026f0c8e9).
- Documentation/source audit: [`0703b3c`](https://github.com/Baltas80/Kini-/commit/0703b3c7e4ea25ad26cedd4eae4ea2a702c63b47).
- CI on code commit `0703b3c` (subsequent commits are documentation-only): **58 passed, 4 third-party warnings** ([run 43675732172](https://github.com/Baltas80/Kini-/actions/runs/43675732172)).
- Historical-data validation on code commit `0703b3c` passed: **5,311 completed fixtures, zero duplicates, `integrity_passed=true`** ([run 43675732192](https://github.com/Baltas80/Kini-/actions/runs/43675732192)).
- The accepted predictive benchmark remains [run 43666544162](https://github.com/Baltas80/Kini-/actions/runs/43666544162). This change only adds a clearly labelled derived coverage field; it does not change model probabilities, the 14-match DP objective or benchmark forecasts.

PR #5 remains open and is still the prerequisite for integrating PR #6. PR #6 remains draft. No PR has been merged and `master` remains untouched.


## Canonical team identity registry — 2026-11-15

A strict provider-scoped identity registry has been added on branch `feat/canonical-team-identity-registry`.

- Registry: `kini_engine/data/team_identity_registry.json`.
- Source artifact: historical-data-validation run [43672336819](https://github.com/Baltas80/Kini-/actions/runs/43672336819); artifact SHA-256 `c194edf11b0733a203a9559e20e8a2b7e43a8d35a4108eacd2c4da6dae49174d`.
- Consolidated CSV SHA-256: `a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab`.
- Coverage in the source artifact: 5,311 fixtures, 56 exact Football-Data team labels and 10,622 home/away references across SP1/SP2 and seven season codes.
- Stable internal IDs are generated from the source labels. Each alias is scoped to Football-Data and the exact observed competition/season pairs.
- Matching uses Unicode NFKC, case folding and whitespace collapse only. Accents and punctuation are preserved. No fuzzy match or cross-provider inference is permitted.
- SELAE aliases are deliberately not seeded. The importer’s (M)/(F) category markers do not by themselves identify a competition or a verified canonical club identity.
- The registry is not wired into model features or training joins; it is an isolated identity layer.

The validator `python -m scripts.validate_team_identity_registry --csv data/historical_spain.csv` resolved **10,622/10,622** team references to 56 unique IDs, with zero unresolved and zero ambiguous references on the exact historical artifact. The PR workflow [historical-data-validation run 43685131603](https://github.com/Baltas80/Kini-/actions/runs/43685131603) completed successfully; its uploaded artifact report independently confirms the same counts.

Deterministic tests: **12 passed** locally. The full repository CI [run 43685131555](https://github.com/Baltas80/Kini-/actions/runs/43685131555) also completed successfully. The historical-data-validation workflow now runs the registry validator against freshly built data and uploads its report. The expensive historical-backtest path filter has been narrowed to forecast/data inputs so identity-only changes do not trigger a full model backtest.

Open limitation at that point in the audit: the Football-Data registry covered only SP1/SP2 labels. This was later superseded by the separate fail-closed SELAE and Liga F evidence layers documented below. Cup and European fixtures remain outside the validated scope. No model probabilities or backtest metrics were changed by the original identity-layer work.


## SELAE fixture reconciliation layer — 2026-11-15

A separate, fail-closed reconciliation layer has been implemented on branch `feat/selae-fixture-reconciliation`, stacked on the canonical identity registry branch and proposed as [PR #9](https://github.com/Baltas80/Kini-/pull/9).

- `kini_engine/fixture_reconciliation.py` validates imported SELAE JSONL records (schema v1/v2), official SELAE provenance, all 14 positions, played score/sign consistency and the public-draw non-played contract.
- `data/selae_fixture_crosswalk.json` now contains ten evidence-backed mappings for coupon positions 1–10: Málaga–Racing de Santander, Osasuna–Athletic Club, Valencia–Real Madrid, Elche–Betis, Real Sociedad–Rayo Vallecano, Celta–Levante, Villarreal–Getafe, Cádiz–R. Oviedo, Girona–Almería and Sporting–R. Valladolid. The kickoff times are supported by official club schedule pages; Football-Data competition/season/date/team labels and full-time scores were checked against the historical CSV artifact.
- Historical CSV artifact: workflow run [43698382204](https://github.com/Baltas80/Kini-/actions/runs/43698382204), SHA-256 `a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab`. The ten crosswalk rows were matched 10/10 to unique SP1/2627 or SP2/2627 rows with identical full-time scores.
- Each crosswalk entry carries the exact SELAE display labels, Football-Data labels, competition, season, gender, independently sourced timezone-aware kickoff, exact Football-Data calendar date, stable official schedule-page URL, schedule source, HTTPS evidence and UTC verification timestamp.
- The reconciler now loads the generated `data/historical_spain.csv` and requires an exact competition/season/date/home/away row. It rejects absent or duplicate rows and any full-time score discrepancy. The Football-Data `Time` field is retained for provenance but is not treated as an authoritative timezone-aware kickoff.
- Both Football-Data identities are resolved through the canonical registry with exact provider, competition, season and gender scope. Unknown, ambiguous, mismatched, out-of-scope and duplicate records are rejected or reported unresolved.
- For the full 8 November 2026 coupon, 13 fixtures were played and one was resolved by public draw. Ten men's fixtures map to exact Football-Data rows. The three women's fixtures are independently verified through the separate Liga F evidence layer and 16-team current-season registry, but are not mapped into Football-Data and remain training-ineligible pending historical identity continuity and pre-kickoff feature validation. The public-draw fixture is excluded from football labels.
- Reconciled goals and 1/X/2 remain targets only; the tool does not add them to model training. Candidate-label export is refused unless every played fixture in the supplied coupon sample is reconciled and there are no unused crosswalk entries.
- CI runs Ruff on the new implementation and the full pytest suite. Identity-only reconciliation files are excluded from the expensive model backtest and historical-data rebuild path filters.

The first CI attempts exposed test-fixture construction mistakes and Ruff import-order issues; those were corrected. Latest PR CI [43699765076](https://github.com/Baltas80/Kini-/actions/runs/43699765076) passed on code head `7c5ef9555b5acbcf7e5daf106be0a3ec71d83a57`: Ruff reported all checks passed and pytest reported 90 passed, 4 upstream NumPy/penaltyblog deprecation warnings, in 2.16 seconds. The subsequent `666fa56b9027ce212209fb82872e9ee63df695c5` commit updates the audit record only; no code or test files changed after validation.

The incidental model backtest triggered before the workflow path exclusions were committed completed successfully in [run 43698454758](https://github.com/Baltas80/Kini-/actions/runs/43698454758). It used no changed model code or model inputs; it does not constitute a new model-performance result.

PR #9 is a draft targeting PR #8's identity branch. PR #7's SELAE importer remains a separate draft dependency and is not copied into this branch. The next data task is to extract official team-profile IDs from archived match-detail pages for 2022/23–2025/26, compare them with the current-season profile crosswalk, and document season-scoped continuity/renames without fuzzy inference. Then audit the availability time of every proposed pre-match feature. No full-coupon training-label export or model training join has been enabled; no PR has been merged and `master` remains untouched.


## Liga F official fixture evidence — 2026-11-15

A source-specific evidence layer has been added for the three played women's fixtures in the 8 November 2026 Quiniela coupon. This does **not** extend the Football-Data training dataset or alter forecasts.

- Separate registry: `kini_engine/data/ligaf_team_identity_registry.json`; 16 current-season internal IDs, with exact Liga F aliases for all 16 and independently verified SELAE aliases for the six teams appearing in coupon positions 11–13. All are scoped to gender `women`, competition `LIGA_F` and season `2026-27`.
- Evidence manifest: `data/ligaf_fixture_evidence.json`.
- Validator: `kini_engine/ligaf_evidence.py`.
- Regression suite: `tests/test_ligaf_evidence.py`.
- Position 11: Athletic Club–Real Madrid CF, 2026-11-07 16:00 +01:00, 1-1, Liga F match ID `202723868`.
- Position 12: Logroño United–Sevilla FC, 2026-11-08 12:00 +01:00, 2-2, match ID `202723864`.
- Position 13: SD Eibar–Real Sociedad, 2026-11-07 17:00 +01:00, 1-2, match ID `202723866`.
- All three match pages and all six team profile URLs are on the official `ligaf.es` domain. The validator checks source host, unique match IDs, unique coupon positions, timezone-aware kickoffs, UTC evidence timestamps, score/sign consistency, and both Liga F and SELAE aliases against the separate registry.
- The loader hard-codes the safe downstream contract: every returned record has `training_label_eligible=false` until a validated multi-season Liga F historical dataset and temporal training boundary exist.
- The Football-Data crosswalk remains ten men's fixtures. No Liga F record is silently inserted into `historical_spain.csv`; the public-draw Tenerife–Alavés fixture remains excluded.

Official match pages:
- https://ligaf.es/partido/athletic-club-femenino/real-madrid-cf-femenino/202723868/detalle
- https://ligaf.es/partido/logrono/sevilla-fc-femenino/202723864/detalle
- https://ligaf.es/partido/eibar-femenino/real-sociedad-futbol-femenino/202723866/detalle

Validation: CI run [43701107837](https://github.com/Baltas80/Kini-/actions/runs/43701107837) passed on the completed implementation. Ruff checks passed; the two new Liga F Python files passed `ruff format --check`; pytest reported 101 passed and 4 upstream NumPy/penaltyblog deprecation warnings. The historical-data rebuild and full model backtest were excluded because these files are evidence-only and do not change the Football-Data dataset or model inputs. No model code, training data or forecast probabilities were changed.


## Next source discovery — Liga F historical archive (2026-11-15)

The official Liga F site exposes season/round result pages using the route pattern `/resultados/primera_division_femenina/{round}/{season_end_year}`. I verified official pages for:
- 2022/23: `/1/2023` (round 1 page; results dated 1–3 November 2022).
- 2023/24: `/1/2024` (round 1 page; results dated 3–5 October 2023).
- 2024/25: `/1/2025` (round 1 page; results dated 6–8 September 2024).
- 2025/26: `/1/2026` and `/30/2026` (round 30 page contains all eight final-round results dated 31 May 2026).
- 2026/27: `/10/2027` (current-season round 10; includes the three match pages recorded above).

These pages expose match-result links; the match-detail pages expose stable Liga F match IDs and kickoff details. This initial discovery was superseded by the multi-season importer and successful live validation documented below ([run 43713031093](https://github.com/Baltas80/Kini-/actions/runs/43713031093)). The remaining implementation unit is to extract official team-profile IDs from historical match-detail pages, compare IDs across seasons and record verified continuity/renames. Promotion/relegation and club identity changes must remain season-scoped; current display-name similarity is not sufficient evidence.

Example official archive URLs:
- https://ligaf.es/resultados/primera_division_femenina/1/2023
- https://ligaf.es/resultados/primera_division_femenina/1/2024
- https://ligaf.es/resultados/primera_division_femenina/1/2025
- https://ligaf.es/resultados/primera_division_femenina/1/2026
- https://ligaf.es/resultados/primera_division_femenina/30/2026
- https://ligaf.es/resultados/primera_division_femenina/10/2027


## Liga F historical ingestion — implementation added (2026-11-15)

### Source inspection

Inspected official Liga F round archives for:
- 2022/23: matchday 30, season-end year 2023.
- 2023/24: matchday 30, season-end year 2024.
- 2024/25: matchday 30, season-end year 2025.
- 2025/26: matchday 30, season-end year 2026.
- 2026/27: matchday 10, season-end year 2027.

The pages expose eight match links per round. The current-season round 10 includes seven final results and a postponed fixture. The source detail pages expose match IDs, team names, matchday, date/time, status and score.

A critical historical metadata defect was identified: a match page for Real Sociedad–Real Madrid dated 19 May 2023 carries a title suffix “Liga F 2027”. The title year is therefore not authoritative. The importer takes the season-end year from the official archive URL, uses the detail-page day/month/time, and cross-checks the resulting date against the explicit date headings in the requested archive round.

### Implementation

- Added `kini_engine/ligaf_history.py` and `scripts/import_ligaf_history.py`.
- Added deterministic parser, cache, source-integrity, postponed-match, date cross-check, duplicate and season-structure tests in `tests/test_ligaf_history.py`.
- Added a content-addressed HTML cache with SHA-256 metadata, bounded HTTP retries, stale-cache fallback, atomic writes and offline mode.
- Added strict eight-fixture-per-round checks, unique match IDs, exact official source URLs and result/score consistency.
- Completed seasons must contain 240 played fixtures, 16 teams, 30 appearances per team and 15 home/15 away fixtures per team.
- Current-season data is capped at matchday 10 by default; the limit is configurable.
- All records remain `training_label_eligible=false`; no model, Football-Data CSV, forecast or backtest input is changed.
- Added a manual `ligaf-history-validation` GitHub Actions workflow and expanded CI lint/test coverage.
- Added generated-data/cache exclusions so Liga F evidence does not trigger the men's Football-Data rebuild.

### State

Implementation: **committed to `feat/selae-fixture-reconciliation`**. The corrected live bulk import passed in [run 43713031093](https://github.com/Baltas80/Kini-/actions/runs/43713031093): 1,040 records, 1,039 played, one postponed, 1,040 unique IDs and integrity passed. The profile exposes 16 exact team labels for each season range; all rows remain training-ineligible. The current implementation/test baseline passed CI in [43713913706](https://github.com/Baltas80/Kini-/actions/runs/43713913706), and the final audit-only head passed in [43714302978](https://github.com/Baltas80/Kini-/actions/runs/43714302978): Ruff, formatting and 121 tests passed, with four upstream deprecation warnings.


## Full historical model benchmark — 2026-11-15

### Execution evidence

- GitHub Actions workflow: historical-backtest.
- Run: https://github.com/Baltas80/Kini-/actions/runs/43703634264
- Model-code revision tested: 2e1a92fde1b88c8480c22b953cb98de387329787.
- Current branch head at this audit: 61a65296dac7a75d4764328afc0fbd32f7319489.
- A GitHub compare confirms the nine commits after the backtest changed only Liga F evidence/import code and workflow path filters; no model implementation or model input files changed.
- Evaluation sample: 5,011 test matches; initial training history: 300; evaluation period: 2020-12-11 through 2026-11-09.
- Dixon–Coles, ML, baseline ensemble, DC+ML ensemble and adaptive DC+ML ensemble each produced 5,011 forecasts. Recorded prediction errors: zero for every model.
- The non-empty model-backtest, schedule-screened market-sample and prequential-calibration acceptance steps all passed.

### Comparable model/market sample

All figures below are on the same 4,424 fixtures with a schedule-compatible market snapshot. Brier and log loss are lower-is-better; accuracy is higher-is-better.

| Candidate | n | Accuracy | Multiclass Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|---:|
| Dixon–Coles | 4,424 | 0.4806 | 0.616357 | 1.027499 | 0.207959 | 0.016274 |
| ML | 4,424 | 0.4383 | 0.646939 | 1.073301 | 0.220439 | 0.048717 |
| Ensemble | 4,424 | 0.4815 | 0.613467 | 1.022929 | 0.206801 | 0.014836 |
| DC + ML | 4,424 | 0.4758 | 0.615989 | 1.026748 | 0.207909 | 0.012726 |
| Adaptive DC + ML | 4,424 | 0.4758 | 0.616176 | 1.027032 | 0.207962 | 0.012805 |
| Market snapshot | 4,424 | 0.5072 | 0.597504 | 0.999444 | 0.199876 | 0.024213 |

The market snapshot beats every model on accuracy, Brier, log loss and RPS. The baseline ensemble is marginally better than Dixon–Coles on Brier/log loss, but the gain is small and does not close the market gap. ML is materially worse than Dixon–Coles and the baseline ensemble on all the principal predictive/probabilistic metrics. It remains experimental and is not promoted as a production candidate on this evidence.

### Prequential calibration

Calibration was trained only on prior walk-forward out-of-sample forecasts; same-calendar-day outcomes were excluded. Configuration: minimum history 500, rolling window 1,500, refit every 30 dates, minimum class count 20, regularization 0.05. The last recorded fit used 1,500 prior forecasts on 2026-10-26.

The calibrated model/market comparison uses a common sample of 3,847 fixtures:

| Candidate | Accuracy | Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Dixon–Coles calibrated | 0.4890 | 0.613232 | 1.022458 | 0.207641 | 0.013549 |
| ML calibrated | 0.4585 | 0.632559 | 1.050517 | 0.216454 | 0.010368 |
| Ensemble calibrated | 0.4884 | 0.611412 | 1.019795 | 0.206972 | 0.012501 |
| DC + ML calibrated | 0.4858 | 0.613535 | 1.022945 | 0.207924 | 0.007171 |
| Adaptive DC + ML calibrated | 0.4843 | 0.613585 | 1.022991 | 0.207908 | 0.008570 |
| Market calibrated | 0.5082 | 0.596714 | 0.998094 | 0.200481 | 0.011690 |

Calibration improves some individual model metrics and ECE, but does not reverse the ranking. Market remains materially better on accuracy, Brier, log loss and RPS.

### Market-data limitation

The market audit found 5,011 fixtures with odds, of which 4,424 passed the current schedule-compatibility screen and 587 were marked ambiguous and excluded. The current screen is **not** proof of exact odds availability before each forecast: the source does not provide per-fixture capture timestamps, and Friday/Tuesday fixtures are excluded because the kickoff timezone is unspecified. Market results are therefore a strong reference benchmark, not yet a fully proven point-in-time market baseline.

### Decision and next action

- P0 empty-prediction failure: **validated absent in this run** for all five model candidates (n=5,011, zero recorded prediction errors).
- Model/market comparison: **validated on comparable schedule-screened samples**; no model beats the market.
- ML: **retain as experimental only** until a feature/ablation study demonstrates incremental value.
- Ensemble: retain only as a candidate; its small improvement over Dixon–Coles does not justify a production selection yet.
- Do not claim profitability or leak-free historical performance from this run alone.
- Next priority: audit the market odds source and exact point-in-time availability, record the historical dataset hash/manifest with each backtest artifact, and evaluate any market/model blend strictly walk-forward on a common sample.

## Liga F bulk-ingestion evidence and workflow correction — 2026-11-15

### First complete live import

The live importer step completed successfully in GitHub Actions runs [43703811822](https://github.com/Baltas80/Kini-/actions/runs/43703811822) and [43703836669](https://github.com/Baltas80/Kini-/actions/runs/43703836669). The jobs failed only in the subsequent workflow assertion, not in the downloader, parser or integrity validator.

The uploaded artifact from run 43703811822 (artifact ID 14158173866) contains:
- `data/ligaf_history.jsonl`: 1,040 records; SHA-256 `3348a13b55bcbb37f2f825873a95b98ea5ce3fd151298c7df91d05ad8d9c46f7`.
- `data/ligaf_history.profile.json`: `integrity_passed=true`, 1,040 unique match IDs, no stale-cache sources, and `training_eligibility.eligible=false`.

An independent local read of the downloaded artifact confirmed:
- 2022/23, 2023/24, 2024/25 and 2025/26: 240 played fixtures each, 16 teams, 30 appearances per team, 15 home and 15 away matches per team.
- 2026/27 rounds 1–10: 80 scheduled fixtures, 79 played and one postponed; 16 distinct teams.
- 1,040 rows and 1,040 unique match IDs; all rows explicitly remain excluded from training.

The sole non-final record is Costa Adeje Tenerife–Deportivo Alavés (Liga F match ID 202723865), matchday 10, scheduled for 8 November 2026 at 13:00 CET. Its status is `postponed`; goals and 1/X/2 result are null. It is not a football result and must not become a training label.

### Root cause of the failed workflow conclusion

Both live runs reached `LIGA_F_HISTORY_OK: scheduled=1040 played=1039 non-final=1`. The next shell assertion interpolated `${{ inputs.max_current_matchday }}` directly. On a push event, the `inputs` context is empty, producing `int("")` and exit code 1. This was a workflow-input default bug; it did not indicate incomplete source coverage or invalid imported records.

### Correction committed

- Commit `b2a81222c04d1de5ee434d8b5ef5903d364a42e4`: move the input defaults into job-level environment variables and use the same value for the importer and profile assertion.
- Commit `1b05b3136a27f400ae35e95b2d5164b481f32263`: include workflow-file changes in the live-validation push trigger.
- The assertion now verifies the requested current matchday count, eight fixtures per round, full round coverage, 16 teams in each completed season and unique IDs.
- Cache keys use `github.head_ref || github.ref_name` so PR and branch runs can share the same branch cache.
- The uploaded artifact now contains only the JSONL and integrity profile; the large HTML cache is handled by `actions/cache` rather than duplicated in every artifact.

The corrected live workflow [run 43707943077](https://github.com/Baltas80/Kini-/actions/runs/43707943077) completed successfully. Its final assertion passed and artifact `ligaf-history` (ID `14160241926`, 90,854 bytes) was uploaded with ZIP SHA-256 `176604cfbef7d815561504bb5150d3b5c6fe792bbe8b3df549fc661d59133217`. The final profile reports 1,040 scheduled fixtures, 1,039 played, one postponed, 1,040 unique match IDs, no stale-cache sources and `integrity_passed=true`; the four completed seasons each contain 240/240 played fixtures and the current-season range contains 80 fixtures (79 played, one postponed). CI for PR head `0d8fcd1529fb563bb9bd2d6e0a5b2d3d9e5a4c4e` also passed in [run 43708166008](https://github.com/Baltas80/Kini-/actions/runs/43708166008): Ruff, formatting and 118 pytest tests. The earlier independently downloaded JSONL from run 43703811822 had SHA-256 `3348a13b55bcbb37f2f825873a95b98ea5ce3fd151298c7df91d05ad8d9c46f7`; do not confuse that file hash with the new ZIP artifact digest.

### Season-scoped team-name inventory — 2026-11-15

The validated Liga F profile now exposes the exact observed team names separately for each season. Commit `1a45b825ba2fec351024e6d64c36b7eda84c8f94` adds the inventory to each season profile: observed display strings, scheduled and played appearances, home/away played counts, and first/last played kickoff in UTC. Grouping uses only the existing case-fold/whitespace normalization; accents and punctuation remain significant, so this report does not infer renamed-club aliases or canonical IDs.

Regression tests in `dac9edee68edfda3f88af807fd05eb81bdac6c4d` assert 16 team profiles and 30/15/15 appearance counts for a complete season, and explicitly keep `Málaga` distinct from `Malaga`. The regenerated live import [43713031093](https://github.com/Baltas80/Kini-/actions/runs/43713031093) passed; its artifact profile reports 16 exact team labels in each of the five season ranges. The current-season inventory is `Athletic Club`, `Atlético de Madrid`, `Costa Adeje Tenerife`, `Deportivo Abanca`, `Deportivo Alavés`, `FC Badalona Women`, `FC Barcelona`, `Granada CF`, `Logroño United`, `Madrid CFF`, `RCD Espanyol`, `Real Madrid CF`, `Real Sociedad`, `SD Eibar`, `Sevilla FC`, and `VCF Femenino`. Consecutive-season set differences are recorded as entrants/exits only; they are not treated as proof of club renaming or continuity.

The current-season identity registry was expanded to 16 official Liga F labels in commit `431a12df8a38d86a8f372eeeeb7f870a7808a4ff`; six retain the verified SELAE aliases. `data/ligaf_team_profile_crosswalk.json` (commit `201bbfcbee843fa294d15dbed70cf35cf476a676`) records 16 official team profile IDs/URLs and one official match-detail evidence URL per team. Tests in `5fb7ad5b425b7c27c9f90086a0ba94b6b3f8c059` validate exact registry resolution, unique provider IDs and official source URLs. CI found one formatting-only failure in the long assertion; it was corrected in `8217f8166c02aa310e0758f611078db66f4fcc88`. Historical-data validation [43713637624](https://github.com/Baltas80/Kini-/actions/runs/43713637624) passed after the crosswalk was added. The implementation/test head passed in [43713913706](https://github.com/Baltas80/Kini-/actions/runs/43713913706); audit-only follow-ups passed [43714148651](https://github.com/Baltas80/Kini-/actions/runs/43714148651) and [43714302978](https://github.com/Baltas80/Kini-/actions/runs/43714302978). All completed Ruff, formatting and pytest successfully (121 tests, four upstream deprecation warnings).

**Training boundary unchanged:** this history is a validated evidence dataset candidate, not an approved model dataset. Team identity history and pre-kickoff feature availability still require separate validation. No Liga F rows are connected to Football-Data, Dixon–Coles, ML, ensemble or forecast inputs.


## Walk-forward reproducibility rerun — 2026-11-15

GitHub Actions [run 43713524597](https://github.com/Baltas80/Kini-/actions/runs/43713524597) completed successfully on commit `201bbfcbee843fa294d15dbed70cf35cf476a676`. It ran the full historical comparison after a metadata-only Liga F profile-crosswalk addition; no predictive model code changed. The run still provides a useful fresh regression baseline:

- Initial training sample: 300.
- Test predictions: 5,011 per each of Dixon–Coles, ML and all three ensemble candidates; zero prediction errors.
- Test period: 2020-12-11 through 2026-11-09.
- Common model/market sample: 4,424; 587 fixtures excluded by the schedule screen because the Football-Data kickoff-time timezone/capture instant is unknown.

| Candidate | Accuracy | Brier | Log Loss | N on common sample |
|---|---:|---:|---:|---:|
| Dixon–Coles | 0.4806 | 0.61636 | 1.02750 | 4,424 |
| ML | 0.4383 | 0.64694 | 1.07330 | 4,424 |
| Market pre-closing | **0.5072** | **0.59750** | **0.99944** | 4,424 |
| Market-assisted ensemble | 0.4815 | 0.61347 | 1.02293 | 4,424 |
| Fixed DC/ML | 0.4758 | 0.61599 | 1.02675 | 4,424 |
| Adaptive DC/ML | 0.4758 | 0.61618 | 1.02703 | 4,424 |

The market remains better on all three reported metrics on the identical 4,424-match sample. The 5,011 all-model forecast count is not the comparison sample: the 587 temporally ambiguous market fixtures are retained for model-only evaluation but excluded from model/market comparison. The benchmark remains a schedule-screened **pre-closing** reference, not timestamp-proven executable closing odds.

Prequential calibration completed on 4,480 post-warm-up forecasts per model with same-calendar-day outcomes excluded. It improved raw Brier/Log Loss for Dixon–Coles (0.61510/1.02527 to 0.61439/1.02395) and ML (0.63969/1.06178 to 0.63341/1.05148), but slightly worsened the market-assisted ensemble (0.61250/1.02118 to 0.61264/1.02132). The calibrated ensemble still trails the market on the common benchmark; no model/calibrator is promoted on this evidence.

Artifact: [historical-backtest, run 43713524597](https://github.com/Baltas80/Kini-/actions/runs/43713524597), ZIP SHA-256 `247ace2a9c5d5984ff418ae0f15dd79596fbc11809390ff7d9fe0e4cfc6a83b4`. The run was triggered unnecessarily by the new Liga F profile-crosswalk JSON matching a broad `data/**` workflow filter. The backtest and historical-data workflows now explicitly exclude `data/ligaf_team_profile_crosswalk.json` in both relevant event filters, preventing future full football backtests/data rebuilds for this metadata-only file.

## Historical Liga F team-profile identity evidence — 2026-11-15

### Season-scoped profile extraction

Commit `cc40622f5ab1f1dcaeeb498084f719308c729908` adds a separate evidence collector:
- `kini_engine/ligaf_team_profiles.py`
- `scripts/build_ligaf_team_profiles.py`
- `tests/test_ligaf_team_profiles.py`

For each completed season 2022/23–2025/26, the collector reads the eight official match-detail links from matchday 30, extracts each team's provider profile ID from the exact home/away team-name anchor, then requests the season-specific profile route using that ID and slug. A profile page is accepted only if its heading and season standings are present. No fuzzy matching or canonical team ID is assigned.

The latest live validation [run 43716218767](https://github.com/Baltas80/Kini-/actions/runs/43716218767) passed on 2026-11-15. Artifact `ligaf-history` (ID `14161934608`, 102,264 bytes) has ZIP SHA-256 `4275010c8f448f917e4ba7c8a3dc9cafdcbadcb88b9208c159cea788b49bb2ab`.

| Season | Teams | Unique provider IDs | Profile pages verified | Exact display-name matches | Manual review |
|---|---:|---:|---:|---:|---:|
| 2022/23 | 16 | 16 | 16 | 16 | 0 |
| 2023/24 | 16 | 16 | 16 | 16 | 0 |
| 2024/25 | 16 | 16 | 16 | 16 | 0 |
| 2025/26 | 16 | 16 | 16 | 16 | 0 |
| **Total team-season observations** | **64** | **64** | **64** | **64** | **0** |

Across the four seasons, the audit found 21 distinct observed display names and 21 distinct provider profile IDs:
- No display name was assigned multiple provider IDs across the observed seasons.
- No provider profile ID was associated with multiple display names.
- Repeated provider IDs retained the same observed display name.
- `canonical_identity_assignments=0`; repeated source IDs remain evidence only and are not promoted to internal canonical identities.

The artifact also contains the Liga F fixture history: 1,040 scheduled fixtures, 1,039 played, one postponed, 1,040 unique match IDs, `integrity_passed=true`, no stale-cache sources and `training_eligibility.eligible=false`. The postponed Costa Adeje Tenerife–Deportivo Alavés fixture remains without goals or a result.

### Backtest regression triggered by the broad engine path

The profile collector initially matched the broad `kini_engine/**` path filter in `historical-backtest`. The resulting full walk-forward run [43715470120](https://github.com/Baltas80/Kini-/actions/runs/43715470120) completed successfully:
- 5,011 predictions for each of Dixon–Coles, ML and all three ensemble candidates.
- Zero recorded prediction errors for every model.
- Initial training sample 300; test period 2020-12-11 to 2026-11-09.
- Common schedule-screened market sample: 4,424 fixtures; 587 odds rows excluded as temporally ambiguous.

| Candidate | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|
| Dixon–Coles | 0.4806 | 0.616357 | 1.027499 |
| ML | 0.4383 | 0.646939 | 1.073301 |
| Baseline ensemble | 0.4815 | 0.613467 | 1.022929 |
| Market | **0.5072** | **0.597504** | **0.999444** |

The market remains better on the identical 4,424-match sample. The ensemble's small improvement over Dixon–Coles does not close the gap; ML remains experimental. Prequential calibration used 3,847 common market fixtures with same-calendar-day outcomes excluded and did not change the ranking. Exact per-fixture odds capture timestamps remain unavailable, so this is not proof of executable closing odds or profitability.

Commit `02b761fc80c81591cfe1cea7381ee5476bda8f90` excludes `kini_engine/ligaf_team_profiles.py` from the expensive model-backtest trigger. Future changes to this metadata/evidence collector will run CI and Liga F validation without automatically rerunning the men's model benchmark.

### Next priority

The historical provider-profile extraction is implemented and live-validated. The next unresolved acceptance item is a point-in-time audit of every candidate Liga F feature: source publication time, observation time, transformation window, and whether the value existed before the fixture's kickoff. Historical team labels and results remain excluded from model training until that audit and the separate canonical identity review are complete.

### Exact comparison with the current-season registry

A separate exact-label comparison between the 2025/26 historical profile evidence and the current 2026/27 profile crosswalk found 14 shared team labels and 14 identical provider profile IDs, with zero ID mismatches. Relative to 2025/26, the current season contains Deportivo Alavés and VCF Femenino where Alhama CF ElPozo and Levante UD were present previously. The Alavés provider ID is independently observed in 2022/23; the VCF Femenino ID is observed in 2022/23–2024/25. These are season-membership differences, not evidence of a new club identity or an alias; no canonical identity is inferred.

The first lint/format attempts exposed import-order, set-comprehension and formatting issues, followed by an incomplete unit-test fixture for the stronger evidence contract. These were corrected in commits `dc189590199bd911850c0e5b18e46d3231452511` and `5d575ded59ca15aeb214224ecd523e4d8a314ad5`. Final PR CI [run 43716295453](https://github.com/Baltas80/Kini-/actions/runs/43716295453) passed on head `5d575ded59ca15aeb214224ecd523e4d8a314ad5`: Ruff checks passed, five files were already formatted, 132 tests passed, and four upstream NumPy/penaltyblog deprecation warnings remained. The latest live source/profile validation is run 43716218767 above; the subsequent 5d575 test-only commit did not alter the importer or profile collector.

## Point-in-time audit of ML features — 2026-11-15

### Implemented feature contract

A code review of `FeatureModel._features` found that the original 15-column matrix included three standings-position fields read from arbitrary `Match.detail` values. The Football-Data loader did not populate those fields, so they were constant zero in the validated historical benchmark. Other callers could nevertheless inject standings without any publication-time provenance. The fields have therefore been removed rather than treated as valid pre-match inputs.

The model now uses exactly 12 numeric features:

1. Home-team points per match, goals for per match and goals against per match over its last eight completed matches.
2. Away-team equivalents over its last eight completed matches.
3. Home-team points/goals for/goals against over its last eight completed home fixtures.
4. Away-team points/goals for/goals against over its last eight completed away fixtures.

The feature builder now independently filters history to completed matches whose source calendar date is strictly earlier than the forecast fixture, then sorts those observations chronologically before taking the last eight. This protects both training-row construction and inference from accidentally supplied same-day or future matches; it no longer relies solely on the caller to pass a clean history list. Unverified standings and other arbitrary detail fields are not read.

Implementation commit: [`401de5d`](https://github.com/Baltas80/Kini-/commit/401de5d8b6a49cf6a5906326c8b4f576fc80b852). Regression commit: [`506deec`](https://github.com/Baltas80/Kini-/commit/506deec73cf5d8f2622451d3c3f2c48d8943dcfe).

### Regression coverage

- The fake-estimator tests now assert the 12-feature training and 12-feature inference matrix shapes.
- A new test supplies same-day and future results with extreme scores, plus unverified standings positions, and asserts that the resulting feature vector is identical to the clean prior-history vector.
- The existing training-row test continues to assert that same-calendar-day outcomes are excluded.

CI and the full historical walk-forward benchmark are triggered by the model/test changes. Do not reuse the earlier 15-feature ML metrics as validation of this revised feature contract; publish updated metrics only after the new workflow completes.

### Remaining temporal limitations

This is a defensive code-level feature audit, not proof of every upstream observation's publication timestamp. Football-Data provides match dates and results but not a per-result publication timestamp. The strict prior-calendar-day rule excludes same-day results, but the benchmark still assumes a completed prior-date result was available before the next calendar date. This assumption should remain explicit.

The historical benchmark's `KiniEngine(enable_ml=True)` path does not enable `context_adjust`; no H2H adjustment is applied in that benchmark. Football-Data rows loaded by `dataio.py` do not carry LAE probabilities, so LAE is absent from this historical comparison. The market component remains gated by the schedule-compatibility screen, not an exact odds-capture timestamp. These external-source limitations remain open and must not be represented as fully point-in-time verified.


## ML feature hardening — first CI result and lint coverage — 2026-11-15

The first CI run after the 12-feature change completed successfully: [run 43717813345](https://github.com/Baltas80/Kini-/actions/runs/43717813345), Ruff's existing scoped checks passed and pytest reported **133 passed, 4 upstream NumPy/penaltyblog deprecation warnings**. This includes the new same-day/future-history regression test.

The workflow previously linted fixture-reconciliation and Liga F files but did not run Ruff against the predictive core. Commit [fc9bf71](https://github.com/Baltas80/Kini-/commit/fc9bf714538352108c79d4150cf99110770a8816) expands the lint step to include `kini_engine/core.py` and `tests/test_core.py`. Its CI run is pending; any Ruff findings must be corrected before treating the code-quality check as complete.

The model-code push matches the `historical-backtest` path filter. The PR-scoped workflow lookup does not expose the push-triggered backtest run, so no new ML metrics are claimed yet. The last accepted 15-feature metrics remain historical only; the 12-feature revision still requires a fresh full walk-forward result with non-empty model samples and zero prediction errors.


## Predictive-core Ruff findings and correction — 2026-11-15

Expanding CI lint coverage to `kini_engine/core.py` and `tests/test_core.py` exposed 13 existing Ruff findings that the previous CI scope had not checked. They were not test failures in the new feature change; the lint step stopped before pytest.

Corrections:
- Removed unused imports and moved `Iterable` to `collections.abc`.
- Removed unnecessary quoted return annotations under postponed annotation evaluation.
- Narrowed the optional XGBoost fallback from a blanket `Exception` catch to import/library-loading errors (`ImportError`, `OSError`), so estimator/configuration failures are no longer silently hidden by the fallback.
- Marked the SELAE class-level limits table as `ClassVar`.
- Changed invalid input-type failures in the ticket optimizer to `TypeError`; retained `ValueError` for invalid values and probability distributions.
- Removed a redundant `list()` around `sorted()`.
- Added regression assertions for boolean budgets, boolean probabilities and non-mapping per-match input.

Implementation: [`9abee23`](https://github.com/Baltas80/Kini-/commit/9abee231ad87c86bb646a51ae0ebfb1e3721f45a). Tests: [`10d1fe5`](https://github.com/Baltas80/Kini-/commit/10d1fe5ecaa85c6f8a9d24503f882f3c54a5b5a5).

The failed expanded-lint run was [43717966679](https://github.com/Baltas80/Kini-/actions/runs/43717966679). The corrected code and tests trigger a fresh CI run and another full historical benchmark because `core.py` changed. Validation remains pending until those runs finish.


## Historical backtest pull-request validation — 2026-11-15

The historical benchmark workflow was previously push/schedule/manual only. Its push-triggered result is not exposed by the connector's PR-only workflow lookup, which prevented reliable inspection of the exact benchmark generated for a PR head. Commit [08a24ae](https://github.com/Baltas80/Kini-/commit/08a24ae0c80b5cd6184b63df7e29027ae30b9894) adds a `pull_request` trigger with the same model/data path filters and evidence-only exclusions as the push trigger. The existing branch concurrency key keeps push/PR duplicates from running simultaneously.

This makes the required non-empty forecast, zero-error, strict market-sample and prequential-calibration acceptance steps observable against the proposed PR head. The new PR-triggered run is pending; do not claim updated benchmark metrics until it completes and its artifact is inspected.

## Point-in-time context hardening and ML feature-build optimization — 2026-11-15

### Implemented

- Commit `8c0540110c9e9fd552a212a74c4a0a9633136589` centralizes the strict prior-date, completed-result filter in `_prior_completed_matches`.
- `context_adjust` now computes recent form and H2H exclusively from completed matches on calendar dates strictly before the fixture. The previous implementation trusted the supplied history list and could incorporate same-day/future results if a caller passed an unrestricted history.
- `surprise_signal` now uses the same point-in-time filter for its recent-form explanation. It cannot use future results to add or remove a contextual reason.
- `FeatureModel._training_rows` now builds the 12-feature training matrix in one chronological pass, grouped by source calendar date. All fixtures on a date are featurized before any result from that date is appended. Per-team overall/home/away histories retain only the latest eight completed matches. This replaces repeated per-row full-history filtering and feature scans.
- The inference/reference `_features` path and the incremental training builder share `_team_form_features`, keeping the feature definition consistent.
- Commit `af9ac241ed60a12b30dd1ae797b865a83101a724` adds regressions for context/surprise invariance under same-day/future contamination, equivalence of the incremental training matrix to the reference builder under shuffled input, and same-day training-row exclusion.

### Validation status

- CI run [43718207962](https://github.com/Baltas80/Kini-/actions/runs/43718207962) failed at Ruff `I001` only: one surplus blank line after imports in `kini_engine/core.py`. The exact formatting issue was corrected in `8c05401`; no tests ran in the failed CI job.
- The earlier full backtest [43718207967](https://github.com/Baltas80/Kini-/actions/runs/43718207967) was cancelled by the subsequent branch update before the historical comparison and acceptance steps completed. It provides no new metrics.
- Fresh PR CI [43723373814](https://github.com/Baltas80/Kini-/actions/runs/43723373814) was queued/pending at the time of this record. This audit update itself may supersede that documentation-triggered run; the latest CI run on the branch must be used for acceptance.
- Fresh historical backtest [43723373822](https://github.com/Baltas80/Kini-/actions/runs/43723373822) passed history construction and the first-ML diagnostic, then entered the historical comparison. Non-empty forecast, market-sample and prequential-calibration acceptance steps had not yet completed. No new metrics are published.
- The new 12-feature model remains unvalidated until the current full backtest and its uploaded JSON artifact complete successfully.

### Remaining temporal limitations and next action

The strict calendar-day cutoff is conservative, not proof of exact result publication time. Football-Data does not provide per-result publication timestamps. Market odds remain schedule-screened rather than per-fixture capture-timestamp verified. External LAE inputs still lack an explicit point-in-time eligibility contract and must not be treated as historically validated.

Next action: collect the latest CI result, then complete the full walk-forward run and inspect its artifact for all five non-empty model configurations, identical market comparison samples, calibration samples and metrics. After that, harden external LAE eligibility and continue the remaining feature-provenance audit.

## Backtest workflow efficiency correction — 2026-11-15

### Root cause

The expensive workflow's `pull_request.paths` filter was evaluated against the PR's changed-file set, not just the latest commit. Because the PR already contained a predictive-core change, later documentation-only commits still triggered a complete walk-forward backtest. With `cancel-in-progress: true`, those redundant runs could cancel a useful model evaluation before its acceptance steps completed.

Observed consequences:
- Backtest [43718207967](https://github.com/Baltas80/Kini-/actions/runs/43718207967) was cancelled after the next code update.
- Backtest [43723373822](https://github.com/Baltas80/Kini-/actions/runs/43723373822) was cancelled after a documentation update.
- Audit-only commit `346757424e14b7742f0b8fffa68d249296deb63b` nevertheless triggered [43723680047](https://github.com/Baltas80/Kini-/actions/runs/43723680047), confirming that the old PR path filter did not isolate the latest commit.

### Implemented correction

Workflow commits `a45f0606ae7562114907eed9d64e1357e30e5580`, `01e0406518e471e2d8c57823fa1f14235d55f88e`, `6c32944bfe7d51ded8c251d4d0c46732592df703` and `3cceba8e025bc32bb52c549563d934e560c781da` update `.github/workflows/historical-backtest.yml`:

- Feature-branch validation is driven by PR open/reopen/synchronize events; push-triggered full backtests are restricted to `master`.
- A lightweight `changes` job compares the PR head with the latest successful historical-backtest head SHA for that branch. On the first run, it compares the full PR diff with the base.
- Only model/data/dependency paths start the expensive backtest. Audit, tests, workflow and evidence-only changes are excluded.
- The workflow has `actions: read` and `contents: read` permissions for the run lookup and commit comparison.
- `cancel-in-progress: false` lets an already-running walk-forward evaluation finish; the latest pending PR update is then filtered against the completed run.

This avoids the previous failure mode where a documentation commit cancelled a long model comparison. The filter is fail-safe: if the Actions API lookup or ancestry comparison is unavailable, it falls back to the full PR diff rather than silently skipping a required model run.

### Validation status

- The current full backtest [43723680047](https://github.com/Baltas80/Kini-/actions/runs/43723680047) is still executing `Run historical comparison`; history build and first-ML diagnostic passed. It has not yet reached the non-empty forecast, market-sample or calibration acceptance steps.
- CI [43724037642](https://github.com/Baltas80/Kini-/actions/runs/43724037642) is installing development dependencies; lint and pytest are pending.
- The workflow-filter validation run [43724037682](https://github.com/Baltas80/Kini-/actions/runs/43724037682) is pending behind the active backtest. It should execute the lightweight change detector and skip the expensive job for the workflow-only commit.
- No new predictive metrics are claimed. The 12-feature ML candidate and the context hardening remain pending full validation.

Next action: complete CI and the active walk-forward run, verify that all five model candidates produce non-empty predictions with zero errors, inspect the uploaded JSON artifact, and confirm the workflow-only pending run skips the expensive job.

## Latest 12-feature walk-forward validation — 2026-11-15

This section supersedes the earlier pending-validation notes above. The exact PR head `af65a05d088ed9d3dfd3ae9c742ccd9fae2897ef` completed both CI and the full historical benchmark.

### CI

- [PR CI run 43724099444](https://github.com/Baltas80/Kini-/actions/runs/43724099444): Ruff lint passed, formatting check passed, **135 tests passed**.
- Four upstream NumPy 2.5 / penaltyblog deprecation warnings remain; they are not test failures.
- The PR-triggered workflow change detector and full benchmark [run 43724099417](https://github.com/Baltas80/Kini-/actions/runs/43724099417) both completed successfully.

### ML first-forecast diagnostic

- Source history: 5,311 matches.
- Initial training rows: 300.
- Feature matrix: **300 × 12**, all finite.
- First forecast: Valladolid–Osasuna, 2020-12-11.
- First-forecast probabilities: `[0.4246723417, 0.3873721121, 0.1879555462]`; sum = 1.0, all finite and non-negative.
- `ML_DIAGNOSTIC_OK`.

### Full walk-forward result

- Run: [43724099417](https://github.com/Baltas80/Kini-/actions/runs/43724099417).
- Evaluated PR head: `af65a05d088ed9d3dfd3ae9c742ccd9fae2897ef`.
- Source dataset: 5,311 completed fixtures.
- Initial train: 300; test: 5,011 fixtures.
- Test period: 2020-12-11 through 2026-11-09.
- All five configurations generated **5,011/5,011 forecasts**, with zero recorded prediction errors.
- Artifact: `historical-backtest`, ID `14165829900`, 169,354 bytes; GitHub artifact digest `sha256:6971b7a5e9e650e125a5e8d5bb457f0347c382b9198cf20675906dad665f300e`.

| Candidate | Accuracy | Multiclass Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Dixon–Coles | 0.4817 | 0.616668 | 1.027806 | 0.208245 | 0.011423 |
| ML (12 features) | 0.4414 | 0.645534 | 1.071417 | 0.219951 | 0.044087 |
| Market-assisted ensemble | 0.4793 | 0.613630 | 1.023028 | 0.207026 | 0.012840 |
| Fixed DC/ML-only | 0.4758 | 0.615866 | 1.026405 | 0.208008 | 0.009508 |
| Adaptive DC/ML-only | 0.4772 | 0.616077 | 1.026712 | 0.208079 | 0.008118 |
| Schedule-screened market | **0.5072** | **0.597504** | **0.999444** | **0.199876** | 0.024213 |

The raw full-sample model metrics above use 5,011 forecasts; the market uses its 4,424 eligible observations and must not be compared to those full-sample model metrics as if they were paired. The exact common-sample comparison below is the fair model-versus-market comparison.

### Identical market sample

The temporal audit found 5,011 rows with odds, 4,424 schedule-compatible rows and 587 ambiguous rows excluded. All five models and the market were scored on the exact same 4,424 fixtures:

| Candidate | Accuracy | Multiclass Brier | Log Loss |
|---|---:|---:|---:|
| Dixon–Coles | 0.4806 | 0.616357 | 1.027499 |
| ML (12 features) | 0.4378 | 0.647471 | 1.074246 |
| Market-assisted ensemble | 0.4781 | 0.613563 | 1.023018 |
| Fixed DC/ML-only | 0.4740 | 0.616095 | 1.026842 |
| Adaptive DC/ML-only | 0.4749 | 0.616305 | 1.027133 |
| Market | **0.5072** | **0.597504** | **0.999444** |

The market is better on all three reported metrics. The market-assisted ensemble improves slightly over Dixon–Coles on Brier and Log Loss, but remains materially behind the market. ML remains weaker and is not promoted. No ensemble is selected as a market-beating default.

### Prequential calibration

The calibration workflow passed with same-calendar-day outcomes excluded. The regularized multinomial vector-bias/shared-scale calibrator was fitted only on prior walk-forward OOF forecasts, with a 500-row warm-up, 1,500-row rolling window, minimum 20 observations per class and refits every 30 forecast dates.

- Raw/calibrated post-warm-up sample: 4,480 forecasts per model.
- Common model/market calibrated sample: 3,847 fixtures.
- Last calibrator fit: 2026-10-26, using 1,500 prior forecasts.
- On the 3,847 common fixtures, calibrated market: accuracy 0.5082, Brier 0.596714, Log Loss 0.998094.
- Best calibrated model by Brier/Log Loss on that same sample was the market-assisted ensemble: Brier 0.611522, Log Loss 1.019966; it still underperformed the calibrated market. Calibration did not reverse model selection.

The calibration experiment is validated as an evaluation pipeline, not as evidence that calibration makes the model competitive with the market. It remains an experiment.

### Updated acceptance state

- **P0 backtest non-empty predictions:** validated on this PR head; all five configurations returned 5,011 forecasts and zero prediction errors.
- **12-feature ML inference and probability contract:** validated by first-forecast diagnostic and full walk-forward.
- **CI:** validated on this PR head, 135 tests passing.
- **P2 leakage controls:** code-level protections for prior-date results, context/H2H and ML feature history are implemented and tested. Exact publication timestamps for historical results remain unavailable, so this is not a complete source-level point-in-time proof.
- **Market timing:** still schedule-screened, not exact per-fixture capture-time verified; 587 ambiguous rows are excluded.
- **P6 optimizer:** existing basic budget/probability/Pleno tests remain in place; correlation-aware ticket coverage, current SELAE rule verification and defensible expected-payout modelling remain open.

Next priority: audit every external forecast input for an explicit availability timestamp/eligibility contract (especially LAE), then finish canonical team identity and correlation-aware ticket optimization. Do not promote ML or an ensemble based on this benchmark.

## LAE point-in-time eligibility gate — 2026-11-15

A code review found that the live prediction path accepted any non-empty `Match.lae` mapping in the default ensemble, the explicit `lae` mode and the surprise-reference diagnostic. Unlike the market path, LAE had no temporal eligibility contract; a stale or post-kickoff value could therefore influence a forecast.

The prediction core now fails closed. LAE can influence the ensemble, direct LAE mode or surprise diagnostic only when all of the following are present and valid:

- A non-empty `lae_source` identifying the provider/feed.
- `lae_captured_at` as an ISO-8601 timestamp with an explicit UTC offset.
- `kickoff_at` as an ISO-8601 timestamp with an explicit UTC offset.
- The capture instant is strictly earlier than the kickoff instant after UTC normalization.
- All three 1/X/2 values exist, are finite, lie in [0, 1], and sum to one within 1e-6.

Date-only values, naive timestamps, missing provenance, equal/post-kickoff captures and malformed probability vectors are ineligible. Unverified LAE values remain on the Match object for diagnostics but do not affect predictions. The direct `lae` mode raises a clear error instead of silently accepting an unverified input.

Regression tests cover the fail-closed default, a valid cross-offset timestamp, missing source, naive timestamps, equal/late capture, invalid probability sums and rejection by direct LAE mode.

Implementation is intentionally an input contract, not a new historical LAE data claim. The Football-Data historical loader currently supplies no LAE observations, so the 2020–2026 walk-forward benchmark is unchanged by this gate. No LAE feed is considered eligible until its caller supplies the required source and capture/kickoff timestamps.

### LAE gate lint correction — 2026-11-15

The first CI attempt on the new LAE gate stopped at Ruff before pytest. It identified two Python 3.11+ modernization rules: `datetime.fromisoformat` already accepts the UTC `Z` suffix, and the timezone constant should use `datetime.UTC`. Both were corrected without changing the eligibility contract. The initial lint failure is [run 43728615705](https://github.com/Baltas80/Kini-/actions/runs/43728615705); the corrected head is queued for fresh CI and walk-forward validation.

## LAE gate validation — corrected head — 2026-11-15

- Corrected implementation commit: `081178e1d441ed70052e356f5a873f5ea4429322` (Python 3.11+ `datetime.fromisoformat`/`UTC` APIs; no change to the fail-closed eligibility semantics).
- PR CI [run 43728777907](https://github.com/Baltas80/Kini-/actions/runs/43728777907) passed: Ruff reported **All checks passed** and pytest reported **143 passed, 4 upstream deprecation warnings**.
- The first attempt [43728615705](https://github.com/Baltas80/Kini-/actions/runs/43728615705) stopped at Ruff before tests; its two findings were corrected in `081178e`.
- The full walk-forward on the LAE-gate implementation commit `313496c` is still running as [43728615644](https://github.com/Baltas80/Kini-/actions/runs/43728615644). The corrected parser commit changes only equivalent ISO-8601 UTC parsing syntax; historical Football-Data rows contain no LAE inputs, so this gate does not alter the historical benchmark path. A final current-head backtest is queued as [43728777983](https://github.com/Baltas80/Kini-/actions/runs/43728777983).

No LAE provider is currently marked eligible by the historical loader. Live callers must supply the source identifier and timezone-aware capture/kickoff timestamps required by the new contract.

## Source-eligibility hardening and final walk-forward — 2026-11-15

Implementation commit [606ba1e4d86db8838e1297a805b269f95c5a1353](https://github.com/Baltas80/Kini-/commit/606ba1e4d86db8838e1297a805b269f95c5a1353) closes a second point-in-time bypass in the public `surprise_signal()` diagnostic. The engine's normal forecast path already screened source values, but direct callers could previously pass arbitrary LAE/market dictionaries without tying them to the current fixture's provenance. The helper now treats legacy LAE/market arguments only as source-selection flags and reads the authoritative vectors from the current `Match` after its eligibility checks.

- Added a shared strict 1/X/2 validator: all three keys required, finite values in [0, 1], booleans rejected, and sum within 1e-6 of one. Invalid inputs are rejected rather than silently normalized.
- Market eligibility now requires both the explicit schedule-compatibility flags and a valid probability vector.
- LAE eligibility reuses the same probability validator after source, timezone-aware capture/kickoff and strict pre-kickoff checks.
- Surprise diagnostics no longer trust caller-supplied external vectors as data; verified Match-attached values are authoritative.
- Four regression tests cover unverified external vectors, verified Match data overriding external values, invalid market vectors and market provenance requirements.

### Validation on commit 606ba1e

- PR CI [run 43734040241](https://github.com/Baltas80/Kini-/actions/runs/43734040241) completed successfully: Ruff **All checks passed**, formatting passed, **147 tests passed**, with four upstream NumPy 2.5 / penaltyblog deprecation warnings.
- Historical walk-forward [run 43734040294](https://github.com/Baltas80/Kini-/actions/runs/43734040294) completed successfully. History construction, first-ML forecast diagnostic, historical comparison, non-empty prediction acceptance, market-sample acceptance, prequential-calibration acceptance and artifact upload all passed.
- Test period: 2020-12-11 through 2026-11-09; initial training sample: 300; generated history: 5,311 completed fixtures; five model configurations each produced **5,011/5,011 forecasts** with **zero prediction errors**.
- Artifact: [historical-backtest, ID 14169644093](https://github.com/Baltas80/Kini-/actions/runs/43734040294/artifacts/14169644093), 169,317 bytes; ZIP SHA-256 `9dfb3c07e6b42e205c0422dfecff10c79ab6801c48cba1a5828b3f415a29689f`.

### Current-head metrics

Full model samples contain 5,011 forecasts each. The schedule-screened market sample contains 4,424 fixtures; the 587 ambiguous rows are excluded. Full-sample model metrics are descriptive only and must not be compared to the smaller market sample as if paired.

| Candidate | n | Accuracy | Multiclass Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|---:|
| Dixon–Coles | 5,011 | 0.4817 | 0.616668 | 1.027806 | 0.208245 | 0.011423 |
| ML (12 features) | 5,011 | 0.4414 | 0.645534 | 1.071417 | 0.219951 | 0.044087 |
| Market-assisted ensemble | 5,011 | 0.4793 | 0.613630 | 1.023028 | 0.207026 | 0.012840 |
| Fixed DC/ML-only | 5,011 | 0.4758 | 0.615866 | 1.026405 | 0.208008 | 0.009508 |
| Adaptive DC/ML-only | 5,011 | 0.4772 | 0.616077 | 1.026712 | 0.208079 | 0.008118 |
| Schedule-screened market | 4,424 | 0.5072 | 0.597504 | 0.999444 | 0.199876 | 0.024213 |

The exact paired comparison uses the same **4,424 fixtures** for every model and the market:

| Candidate | Accuracy | Multiclass Brier | Log Loss |
|---|---:|---:|---:|
| Dixon–Coles | 0.4806 | 0.616357 | 1.027499 |
| ML (12 features) | 0.4378 | 0.647471 | 1.074246 |
| Market-assisted ensemble | 0.4781 | 0.613563 | 1.023018 |
| Fixed DC/ML-only | 0.4740 | 0.616095 | 1.026842 |
| Adaptive DC/ML-only | 0.4749 | 0.616305 | 1.027133 |
| Market | **0.5072** | **0.597504** | **0.999444** |

The market remains better than every candidate on accuracy, Brier and Log Loss. The market-assisted ensemble is the strongest model candidate by Brier/Log Loss but does not close the market gap. ML remains materially weaker. No candidate is promoted as a market-beating production model.

### Prequential calibration on the current head

The regularized multinomial vector-bias/shared-scale calibrator used only prior walk-forward out-of-sample forecasts, excluded same-calendar-day outcomes, used a 500-forecast warm-up, 1,500-row rolling window, minimum 20 observations per class and refit every 30 forecast dates.

- Each model: 4,480 post-warm-up raw/calibrated forecasts.
- Exact common calibrated model/market sample: 3,847 fixtures.
- Last calibrator fit: 2026-10-26 using 1,500 prior forecasts.
- Calibrated market on the common sample: accuracy 0.5082, Brier 0.596714, Log Loss 0.998094.
- Best calibrated model on that same sample: market-assisted ensemble, accuracy 0.4866, Brier 0.611522, Log Loss 1.019966.

Calibration improves the market's Brier/Log Loss slightly on this sample and reduces its ECE, but the calibrated ensemble remains materially worse. Calibration is validated as a prequential evaluation pipeline, not as evidence of model-market parity or betting profitability.

### Acceptance and remaining limitations

- **P0 non-empty backtests:** validated on the current code head; all five configurations generated 5,011 forecasts with zero errors.
- **Source eligibility:** the direct surprise-diagnostic bypass is closed and regression-tested.
- **CI:** 147 tests pass on the current code head.
- **Historical market comparison:** paired on 4,424 schedule-compatible fixtures. The 587 Friday/Tuesday rows remain ambiguous because exact kickoff timezone and per-fixture odds capture timestamps are unavailable; the market remains a schedule-screened pre-closing snapshot benchmark, not verified closing/executable odds.
- **Historical feature availability:** strict prior-date filtering is implemented, but exact publication timestamps for historical results are not available; source-level point-in-time proof remains incomplete.
- **Live LAE adapter:** `KinielaGPTSource.probabilities()` still discards capture-time metadata and `detect_surprises()` does not yet attach a verified timezone-aware kickoff. The fail-closed core therefore intentionally ignores those adapter-supplied LAE values. Do not fabricate timestamps to re-enable them.
- **P6:** optimizer still needs correlation-aware coverage validation, complete rule/price refresh for actual submission, and defensible expected-payout modelling.

Next priority: repair the live LAE adapter contract by preserving a provider capture timestamp and obtaining an exact timezone-aware kickoff from the fixture source; then continue canonical team identity and correlation-aware ticket-optimization acceptance. Do not promote ML or an ensemble on these results. No merge or changes to `master`.

## Live LAE adapter provenance — 2026-11-15

The live KinielaGPT adapter was hardened in commits [b61d147](https://github.com/Baltas80/Kini-/commit/b61d14795ac32f075cffde976b20ac544ef5d13f) and [1c7e8b8](https://github.com/Baltas80/Kini-/commit/1c7e8b84ba250bb1efd47c6d09eabc56d66fe422), with formatting and optional-dependency cleanup in subsequent commits through `60bf55b`.

- Each XML endpoint is fetched independently through a response-snapshot helper. The adapter records a timezone-aware UTC timestamp immediately after the complete HTTP response has been received.
- The LAE endpoint (`porcentajes_lae.asp`) and public Quinielista percentages endpoint (`porcentajes.asp`) are now retained as separate normalized 1/X/2 vectors, with separate source identifiers and client-receipt timestamps.
- The legacy top-level 1/X/2 output remains available as an equal-weight mean of the valid, individually normalized source vectors, preserving the existing consumer contract while making its composition explicit.
- Invalid or empty source vectors are not repaired into apparently valid probabilities and are excluded from the blend.
- MCP `detect_surprises()` now passes the actual LAE vector and its provenance metadata to `Match`; it no longer labels the legacy blended vector as LAE.

**Timestamp limitation:** these timestamps prove when this client received the response, not when the provider first published or last refreshed the underlying percentages. The adapter still does not provide a verified, timezone-aware per-match kickoff timestamp. Consequently the core's LAE gate remains fail-closed and the MCP surprise tool does not yet use LAE to alter predictions. No timestamp or kickoff has been inferred or fabricated. Re-enabling the feature requires an exact kickoff value from the fixture/details source and an explicit mapping to the same match ID.

### Validation and workflow scope

- CI [run 43740812199](https://github.com/Baltas80/Kini-/actions/runs/43740812199) passed on the current adapter head: Ruff passed, formatting passed, **149 tests passed**, with four upstream NumPy 2.5 / penaltyblog deprecation warnings.
- Two source-adapter regression tests cover separate feed vectors, the equal-weight compatibility blend, UTC response-receipt timestamps and exclusion of an invalid all-zero source vector.
- Ruff and formatting coverage now includes `kini_engine/sources.py`, `kini_engine/mcp_server.py` and `tests/test_sources.py`.
- The historical backtest workflow now excludes source/MCP adapter-only changes from the expensive model benchmark. The walk-forward CLI imports `backtest` and `dataio`, not these live adapters; CI still validates the adapters. No model or historical feature code changed in this unit, so the previously completed 5,011-forecast benchmark remains the applicable model result. The current PR-triggered scope-check run is [43740812220](https://github.com/Baltas80/Kini-/actions/runs/43740812220); its final skip/success state is to be recorded once the job is created.
- The current production limitation remains: LAE-based surprise detection is not active until a verified kickoff timestamp is available. The fail-closed behavior is intentional.

Next priority: inspect the live `detallePartido` response schema through a controlled, non-mutating source diagnostic; map its exact match identifier and timezone-aware kickoff field only if the provider supplies them. If it supplies only local date/time without timezone semantics, keep LAE ineligible until that contract is verified.


## Historical backtest after live-adapter changes — 2026-11-15

The PR-triggered historical workflow [run 43740951689](https://github.com/Baltas80/Kini-/actions/runs/43740951689) completed successfully on branch head `1085401288f479f764a182d86a357dfe67c2ebc2`. This run did execute the full comparison; it was not merely a path-filter skip.

- Generated history: 5,311 completed fixtures.
- Test period: 2020-12-11 through 2026-11-09.
- Initial training sample: 300.
- All five model configurations generated 5,011/5,011 forecasts with zero recorded prediction errors.
- Schedule-screened market sample: 4,424; 587 ambiguous odds rows excluded.
- Artifact: [historical-backtest, ID 14173302990](https://github.com/Baltas80/Kini-/actions/runs/43740951689/artifacts/14173302990), 169,354 bytes; ZIP SHA-256 `c2d52c6fa9403fe9b48b8b4dc3ef2a770e770b12550507a186274679d53cdff1`.

Paired model/market metrics on the same 4,424 fixtures:

| Candidate | Accuracy | Multiclass Brier | Log Loss |
|---|---:|---:|---:|
| Dixon–Coles | 0.4806 | 0.616357 | 1.027499 |
| ML (12 features) | 0.4378 | 0.647471 | 1.074246 |
| Market-assisted ensemble | 0.4781 | 0.613563 | 1.023018 |
| Fixed DC/ML-only | 0.4740 | 0.616095 | 1.026842 |
| Adaptive DC/ML-only | 0.4749 | 0.616305 | 1.027133 |
| Market | **0.5072** | **0.597504** | **0.999444** |

Prequential calibration retained 3,847 common post-warm-up fixtures. On that same sample, the calibrated market scored Brier 0.596714 / Log Loss 0.998094; the best calibrated model candidate (market-assisted ensemble) scored 0.611522 / 1.019966. Calibration did not close the gap. No model is promoted.

The successful run confirms that the live-adapter-only changes did not break the historical model pipeline. It does not validate the provider's live details schema or make LAE eligible for production predictions.

## Controlled live details-schema diagnostic — implementation

The adapter now exposes `details_payload()`, which returns the provider JSON object unchanged together with the local UTC response-receipt timestamp. The compatibility `details()` method now fails explicitly if `detallePartidos` is missing, is not an array, or contains non-object records; it no longer silently converts an unexpected response shape into an empty list.

A read-only GitHub Actions diagnostic has been added. It fetches the current jornada and its details, then stores only bounded schema evidence: root keys, record keys, candidate match/date/time fields, scalar samples and whether an ISO datetime explicitly carries a timezone. It does not upload the raw provider response and performs no write operation.

- Unit tests cover payload preservation, receipt timestamp, request parameters, strict response shape and timezone-aware versus local date/time detection.
- CI lint and formatting explicitly include the diagnostic script and tests.
- Dedicated workflow: `.github/workflows/kinielagpt-live-details-diagnostic.yml`.
- Live workflow result and artifact: pending this commit's PR-triggered execution.

Production LAE eligibility remains fail-closed. A timezone-aware kickoff is not inferred from a local date/time string; a field must be tied to the same provider match ID before it can be passed into `Match`.


### First live details-schema observation — run 43745525438

The read-only diagnostic [run 43745525438](https://github.com/Baltas80/Kini-/actions/runs/43745525438) succeeded for current jornada 22, temporada 2027. Artifact [kinielagpt-details-diagnostic, ID 14174630685](https://github.com/Baltas80/Kini-/actions/runs/43745525438/artifacts/14174630685), 1,839 bytes, SHA-256 `c849d144df20e93cf22149c4ec668bf1ca843ede65bf2e17fb5c8a191e037d37`.

- The provider returned a JSON object with 15 `detallePartidos` records.
- Root fields include `jornada`, `temporada`, `caducidad`, `juego`, `clasificaciones`, `detallePartidos` and `detallePlenoQuince`.
- Each inspected detail record exposes `idEquipoLocal`, `idEquipoVisitante`, team names, `dia`, `hora`, `orden` and `idCompeticion`.
- No `idPartido` or timezone-aware kickoff field appeared in the sampled detail records. The observed `hora` value is a local clock string (for example `20:45`), not an offset-aware timestamp.
- The first five records include international team fixtures; their team provider IDs are available, but the separate percentage XML uses a match number and display names. A join must be explicitly verified rather than assuming that `orden` and XML `num` are interchangeable.

This is sufficient to keep the LAE gate disabled: the response does not currently prove an exact, timezone-aware kickoff. The diagnostic has been extended to expose the actual `dia`, `orden`, jornada/season and cache-expiry samples so the date semantics and any safe match-number crosswalk can be checked. No timezone will be inferred from the Spanish-language site or from the local clock string.


### Live details field semantics — run 43745730824

The second read-only diagnostic [run 43745730824](https://github.com/Baltas80/Kini-/actions/runs/43745730824) completed successfully for jornada 22 / temporada 2027. Artifact [kinielagpt-details-diagnostic, ID 14174126247](https://github.com/Baltas80/Kini-/actions/runs/43745730824/artifacts/14174126247), 2,558 bytes; SHA-256 `56801dde0d3d52486f36923ecb872270cbd79273bea2828d29b30dc6525ec2dd`.

Observed field semantics:

- `dia` is a weekday abbreviation (`MAR`), not a calendar date.
- `hora` is a local clock string (`20:45` in the sampled records); it carries no timezone offset.
- `orden` is a sequence from 1 onward; the provider detail records do not expose a fixture-level `idPartido`.
- `idEquipoLocal` and `idEquipoVisitante` are present, but the percentage XML exposes team display names and its own `num`; no provider fixture ID is shared in the inspected payload.
- Root `caducidad=1794783600` converts to 2026-11-15 23:00 UTC. It is a cache-expiry-like field, not a kickoff field, and is not used for eligibility.
- The detail payload contains 15 records, but no calendar date or timezone-aware kickoff in the sampled records.

The evidence rules out deriving kickoff from `dia` + `hora` or treating `caducidad` as match time. LAE therefore remains ineligible for live surprise detection. The diagnostic now explicitly flags `dia` as a date/time candidate and verifies that weekday-only and local-clock strings are not timezone-aware ISO timestamps.

The next safe investigation is a strict crosswalk check between `orden` and the percentage XML's `num`, using exact normalized home/away names as an independent guard. Even a successful crosswalk will not solve the missing calendar date/timezone; a separate source with a documented, timezone-aware kickoff is still required.


### Final validation for the live details diagnostic — 2026-11-15

Validated on commit `afde6775d3cc1243da6016e2797b4216d84df331`:

- CI [run 43745904226](https://github.com/Baltas80/Kini-/actions/runs/43745904226) completed successfully: Ruff passed, formatting passed, **156 tests passed**, four upstream deprecation warnings.
- Live schema diagnostic [run 43745904213](https://github.com/Baltas80/Kini-/actions/runs/43745904213) completed successfully. Artifact [ID 14174441120](https://github.com/Baltas80/Kini-/actions/runs/43745904213/artifacts/14174441120), 2,569 bytes; SHA-256 `c77d022e2f465f80b30c6523fd838615ef344f2d610cb9810532dc1323dfbee1`.
- The repeated live response again returned 15 detail records for jornada 22 / temporada 2027. The first five sampled records consistently reported `dia=MAR`, `hora=20:45`, and `orden=1..5`; both `dia` and `hora` are explicitly classified as not timezone-aware ISO values.
- The historical workflow [run 43745904189](https://github.com/Baltas80/Kini-/actions/runs/43745904189) completed successfully with the expensive backtest job skipped by its change-scope gate. No model or historical data code changed in this diagnostic unit.

The live LAE source is therefore not eligible for pre-kickoff surprise detection using this endpoint alone. The implementation is fail-closed; the absence of a calendar date and timezone is a provider-data limitation, not a parsing failure.


### Diagnostic workflow efficiency and final CI — 2026-11-15

The live details workflow now checks the files changed in the latest PR commit before making external GET requests. PR open/reopen events and commits that change the adapter, diagnostic script, related tests or workflow run the diagnostic; documentation-only follow-up commits skip it. This avoids re-fetching the provider schema merely because the audit log was updated.

- Code validation on `afde677`: [CI run 43745904226](https://github.com/Baltas80/Kini-/actions/runs/43745904226) passed Ruff, formatting and 156 tests.
- Documentation-head validation on `848e78f`: [CI run 43746039985](https://github.com/Baltas80/Kini-/actions/runs/43746039985) also passed Ruff, formatting and 156 tests.
- The repeated live schema check [run 43746039912](https://github.com/Baltas80/Kini-/actions/runs/43746039912) succeeded and produced the same 15-record, weekday-plus-local-time schema. Its artifact is retained for seven days.
- The expensive historical backtest [run 43746039920](https://github.com/Baltas80/Kini-/actions/runs/43746039920) was skipped by the scope gate because the commit only changed documentation.

No changes were made to model code or historical features in this unit. The last full walk-forward metrics remain those recorded above. The PR remains open as a draft and `master` is unchanged.


### Final workflow-filter validation — 2026-11-15

The live diagnostic workflow's latest-commit filter was repaired after two workflow-only attempts exposed a malformed shell regex/duplicated YAML tail. The final workflow file was replaced as a complete block in commit `0bf4f7a`; the filter now uses a bounded latest-commit diff and a literal-dot regex. This prevents audit-only commits from repeating the external provider GET.

Validation on `0bf4f7a7c17b5f78550cc3be1564f7fa498081f9`:

- CI [run 43746288126](https://github.com/Baltas80/Kini-/actions/runs/43746288126): Ruff passed, formatting passed, **156 tests passed**, four upstream deprecation warnings.
- Live diagnostic [run 43746288146](https://github.com/Baltas80/Kini-/actions/runs/43746288146): both `changes` and `inspect` jobs passed; provider GET and artifact upload succeeded. Artifact [ID 14173922579](https://github.com/Baltas80/Kini-/actions/runs/43746288146/artifacts/14173922579), 2,569 bytes; SHA-256 `12bec2b30f1a32bffb6565b9261921ee7daff45b2a0c3b0ea6801d6b479dfd9d`.
- Historical workflow [run 43746288169](https://github.com/Baltas80/Kini-/actions/runs/43746288169): change-scope gate succeeded and skipped the expensive walk-forward because only diagnostic/workflow code changed.

The current endpoint still returns `dia=MAR` and `hora=20:45`, with no calendar date or timezone. LAE remains fail-closed. The last full historical model comparison remains run 43740951689 as documented above.

This verification was completed on documentation-only commit `6041fd8`: live workflow run [43746425602](https://github.com/Baltas80/Kini-/actions/runs/43746425602) passed `changes` and skipped `inspect`; historical run [43746425599](https://github.com/Baltas80/Kini-/actions/runs/43746425599) skipped the backtest. The latest-commit filter therefore avoids a redundant provider GET on audit-only updates.

## Fixture-order crosswalk and workflow baseline corrections — 2026-11-15

### KinielaGPT order-to-percentage crosswalk

The read-only diagnostic now compares `detallePartidos[].orden` against the `num`/ID and home/away names returned by the current percentage XML endpoint.

The check is deliberately conservative:

- Normalize Unicode accents, case and punctuation only.
- Require an exact normalized home/away pair in the same orientation.
- Require exactly one percentage row for each pair.
- Require `orden == num` for every fixture.
- Require unique detail orders and percentage IDs, equal record counts, one-to-one coverage and no invalid records.
- Do not use aliases, fuzzy matching, reversed home/away pairs or positional fallback.

Three regression tests cover a valid accent/case-normalized bijection, a reversed fixture whose names point to a different number, and an ambiguous duplicate name pair.

Live validation on the current jornada:

- Diagnostic run [43751980923](https://github.com/Baltas80/Kini-/actions/runs/43751980923) succeeded on the updated branch.
- Jornada 22, temporada 2027.
- 15 detail records and 15 percentage records.
- **15/15 exact name-pair matches; all 15 `orden` values equal their percentage `num`.**
- Zero duplicate orders, duplicate percentage IDs, invalid records or unmatched percentage IDs.
- Artifact [kinielagpt-details-diagnostic, ID 14176397533](https://github.com/Baltas80/Kini-/actions/runs/43751980923/artifacts/14176397533), 3,144 bytes.

This verifies the crosswalk for this live jornada snapshot only. It does not establish that the provider's numbering contract is invariant across all seasons or competitions.

### Kickoff-time limitation remains open

The crosswalk does not provide a calendar date or timezone-aware kickoff. In the first five sampled detail records, `dia` was `MAR` and `hora` was `20:45`; both were classified as non-timezone-aware values. The sampled schema still has no timezone-aware ISO kickoff field.

Do not combine weekday plus local clock into a guessed date, and do not treat the root `caducidad` value as kickoff. LAE remains fail-closed and cannot influence the live ensemble or surprise score until an independent fixture source supplies an exact timezone-aware kickoff for the same verified fixture.

### Workflow reliability and efficiency corrections

Two CI scope filters had edge cases that could cause unnecessary work or hide a cancelled validation:

- The historical workflow queried the Actions API with `status=success`, but `status` is a lifecycle filter, not a conclusion. It now queries completed runs and selects the newest run whose actual `backtest` job concluded successfully. A skipped backtest is not accepted as a validation baseline.
- The live diagnostic filter previously compared only the latest commit. A later documentation/workflow commit could therefore skip a diagnostic whose earlier run had been cancelled. It now compares against the newest completed run whose `inspect` job actually succeeded.
- Both changes jobs now fetch full history before checking whether the last successful validation commit is an ancestor, avoiding false fallback to a full PR diff caused by shallow history.

Validation:
- CI [run 43751980894](https://github.com/Baltas80/Kini-/actions/runs/43751980894): Ruff and formatting passed; **159 tests passed**, with four upstream NumPy 2.5 / penaltyblog deprecation warnings.
- Live diagnostic [run 43751980923](https://github.com/Baltas80/Kini-/actions/runs/43751980923): change filter and live inspection both passed; bounded artifact uploaded.
- An earlier full historical backtest [run 43751566316](https://github.com/Baltas80/Kini-/actions/runs/43751566316) was started because the old historical baseline query returned no successful SHA. It is still running at this audit update. No predictive model or historical feature code changed in this unit; the last completed benchmark remains run 43740951689 until a new full run completes.

### Next actions

1. Confirm the corrected historical scope filter finds the last successful backtest job and skips the queued workflow-only/diagnostic-only update after run 43751566316 completes.
2. Continue sourcing exact timezone-aware kickoff timestamps and verify each timestamp against the same crosswalked home/away fixture. Keep LAE disabled until this is demonstrated.
3. Resume the candidate-feature point-in-time audit and correlation-aware Quiniela ticket-coverage acceptance work.

No direct changes to `master`; PR #9 remains open and unmerged.


## LAE XML activation diagnosis and freshness gate — 2026-11-15

### Live endpoint diagnosis

The bounded live diagnostic now inspects the actual LAE percentage XML schema rather than inferring a parser failure from an empty vector.

Evidence from live jornada 22 / temporada 2027:

- Detail records: 15.
- Percentage records: 15.
- Exact normalized home/away crosswalk: **15/15**.
- \`orden == num\` for all 15 fixtures.
- Official kickoff mapping: **15/15**.
- Schedule evidence fresh at the probability capture: **15/15**.
- LAE source rows: 15.
- Valid LAE probability vectors: **0/15**.
- Temporally eligible LAE rows: **0/15**.

The LAE XML schema contains the parser's expected fields: \`num\`, \`local\`, \`visitante\`, \`porc_1\`, \`porc_X\`, \`porc_2\`. The three percentage fields are zero in the sampled records. \`_probability_map\` correctly rejects an all-zero vector because it has no probability mass. This is **not a field-name/parser mismatch**; the provider has not supplied usable LAE percentages for this jornada snapshot.

Diagnostic run [43755104246](https://github.com/Baltas80/Kini-/actions/runs/43755104246) succeeded. Bounded artifact [14177602838](https://github.com/Baltas80/Kini-/actions/runs/43755104246/artifacts/14177602838), 3,760 bytes, SHA-256 \`91e204e173282b2e36e01f796fdabedd0f1a797044c0df6999920f38bf9a5a83\`.

The fixture schedule is independently grounded in the official UEFA pages:

- [2026 UEFA Nations League fixtures](https://www.uefa.com/uefanationsleague/news/02a2-1fea18abbcbc-456e846509e7-1000--2026-uefa-nations-league-all-the-league-phase-fixtures-a/): Tuesday 17 November, all times CET, 20:45 unless stated.
- [2026/27 Women's Champions League fixtures](https://www.uefa.com/womenschampionsleague/news/02a9-21848dfb62c3-1313bc23426c-1000--202627-womens-champions-league-all-the-league-phase-fixtures/): 18–19 November, all times CET, 21:00 unless stated, with the listed 18:45 exceptions.

### LAE eligibility hardening

A stale official schedule can become unsafe if a fixture's kickoff is amended after the schedule was checked. The previous gate only required that the schedule check preceded the LAE capture; it did not bound the age of that evidence.

The shared contract now defines \`LAE_KICKOFF_EVIDENCE_MAX_AGE = timedelta(hours=24)\` and applies it in three layers:

1. \`KinielaGPTSource.probabilities()\` attaches kickoff metadata to an LAE row only when the exact fixture identity is verified and the schedule evidence is between zero and 24 hours old at capture. Older evidence is labelled \`schedule_evidence_stale\`; evidence checked after capture remains \`schedule_evidence_after_lae_capture\`.
2. \`Match.has_temporally_eligible_lae\` independently requires the exact LAE source ID, verified fixture identity, an HTTPS evidence URL, timezone-aware evidence/capture/kickoff timestamps, evidence age in \`[0, 24h]\`, capture strictly before kickoff, and a valid normalized 1/X/2 vector.
3. The live diagnostic summary applies the same freshness rule and reports \`evidence_fresh_at_capture\`.

The 24-hour threshold is a conservative project safety policy, not a provider guarantee. It means the schedule evidence must be refreshed before a later LAE capture can be accepted. LAE remains excluded until the provider supplies non-zero, valid vectors.

Regression coverage now includes missing or wrong source identity, unverified fixture identity, non-HTTPS evidence, missing/naive timestamps, evidence after capture, evidence older than 24 hours, capture at/after kickoff, invalid probability vectors, and the source adapter's stale-evidence rejection.

### Validation of this unit

On final code commit \`86b88213734ec2d84204965e0add064086f7cbb2\`:

- CI [run 43755104132](https://github.com/Baltas80/Kini-/actions/runs/43755104132): Ruff passed, formatting passed, **173 tests passed**, four upstream deprecation warnings.
- Live diagnostic [run 43755104246](https://github.com/Baltas80/Kini-/actions/runs/43755104246): change filter and read-only inspection passed; all 15 fixture mappings and freshness checks passed; no usable LAE vectors were returned.
- Historical data validation [run 43755104115](https://github.com/Baltas80/Kini-/actions/runs/43755104115): dataset build, canonical team identity validation and quality-profile checks passed.

### Latest full probabilistic benchmark

The previously pending full walk-forward run [43751566316](https://github.com/Baltas80/Kini-/actions/runs/43751566316) completed successfully. Artifact [14176219177](https://github.com/Baltas80/Kini-/actions/runs/43751566316/artifacts/14176219177). Test period: 2020-12-11 through 2026-11-09; 5,011 model predictions. The market had 4,424 schedule-eligible matches; all primary comparisons below use that same 4,424-match common sample.

| Candidate | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|
| Dixon-Coles | 48.06% | 0.616357 | 1.027499 |
| ML | 43.78% | 0.647471 | 1.074246 |
| Ensemble | 47.81% | 0.613563 | 1.023018 |
| Ensemble DC+ML | 47.40% | 0.616095 | 1.026842 |
| Adaptive ensemble | 47.49% | 0.616305 | 1.027133 |
| Market | **50.72%** | **0.597504** | **0.999444** |

The market remains better on the matched sample. The prequential calibration uses prior walk-forward out-of-sample forecasts and excludes same-calendar-day outcomes. On its 3,847-match common market sample, calibration reduced the ensemble's ECE (0.01710 to 0.00972) but slightly worsened its Brier (0.611315 to 0.611522) and Log Loss (1.019753 to 1.019966). The calibrated market remained better (Brier 0.596714; Log Loss 0.998094). Do not promote the calibrated ensemble on ECE alone.

The market temporal audit still excludes 587 of 5,011 odds-bearing fixtures because kickoff schedule/timezone evidence is ambiguous. No historical model or feature code changed in the LAE freshness unit, so this benchmark remains the latest valid predictive baseline; no redundant walk-forward was launched.

### Next actions

1. Re-check the official UEFA fixture pages and refresh the crosswalk evidence timestamp before its 24-hour freshness window expires. Do not extend the timestamp without a fresh source check.
2. Re-query the LAE endpoint as the jornada approaches. Keep LAE disabled while all percentages are zero; when non-zero values appear, require valid vectors and retain the same fixture/time gates.
3. Continue the point-in-time feature audit.
4. Continue correlation-aware ticket-coverage work. The current ticket coverage objective still uses an independence approximation; do not describe it as a joint-probability optimizer until a validated joint scenario source is available.

PR #9 remains open as a draft against \`feat/canonical-team-identity-registry\`. No changes were made to \`master\`, and no PR was merged.

## Correlation-aware ticket coverage evaluator — 2026-11-15

### Implemented

- Added `TicketOptimizer.evaluate_joint_scenario_coverage(columns, scenarios, weights=None)`.
- It evaluates complete 14-outcome scenarios against exact 14-sign ticket columns. A scenario counts as covered only if the full ordered outcome vector matches one submitted column; marginal per-match sign unions are not mistaken for a winning column.
- Optional non-negative scenario weights are supported. The result reports weighted empirical coverage, scenario/column counts, duplicate columns, covered weight and effective sample size.
- Inputs fail closed on malformed columns/scenarios, invalid 1/X/2 labels, mismatched weight lengths, booleans, negative/non-finite weights and zero total weight.
- The method explicitly excludes Pleno al 15 and makes no independence assumption.

### Independence boundary retained

The existing optimizer still chooses doubles/triples using the product of selected marginal sign masses. Its legacy `joint_coverage` response field is retained for compatibility, but the response now also exposes `independent_coverage_estimate` and `coverage_method=product_of_marginal_selected_sign_masses`. This is not empirical joint coverage and is not expected payout.

### Data limitation

The repository currently contains `data/matches.csv` with one fixture per row and columns `Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR`; it does not contain a draw identifier or a complete, ordered 14-match Quiniela coupon outcome per round. The current SELAE fixture crosswalk is not a historical joint-outcome dataset. Therefore no historical joint-coverage score or correlation-aware optimization result is claimed. Constructing scenarios by independently sampling the existing fixture rows would destroy the cross-match dependence this evaluator is intended to measure.

### Next acceptance step

Acquire official historical Quiniela draw results with stable draw IDs and all 14 main-match outcomes, reconcile each coupon slot to a dated fixture without fuzzy identity inference, and then compare the existing independence estimate with this exact scenario evaluator on a held-out set of complete draws. Only after that evidence exists should the optimizer objective be changed.

Implementation and regression tests are committed separately from the model benchmark. No model probabilities or historical benchmark metrics were changed by this unit.

### Numerical edge-case hardening

The weighted evaluator now scales weights before the sum-of-squares calculation, avoiding underflow/overflow for very small or large finite weights. It rejects a non-finite aggregate weight total and rejects non-string sign labels explicitly. Regression tests cover weights of 1e-300 and 1e200, aggregate overflow, and non-string outcomes.

The overflow regression initially emitted a NumPy runtime warning while correctly rejecting the aggregate. The implementation now scales first and checks the finite-total bound before multiplying, so invalid extreme weights are rejected without emitting a numerical warning.

## Latest execution — joint-scenario coverage and source discovery (2026-11-15)

### Implementation

- Commit [870138c](https://github.com/Baltas80/Kini-/commit/870138c5967b32d6d47be3ba98ba9273f0ada4c1) adds `TicketOptimizer.evaluate_joint_scenario_coverage(columns, scenarios, weights=None)`.
- The evaluator checks exact ordered 14-sign columns against complete 14-outcome scenarios. It supports explicit non-negative weights and reports weighted coverage, counts, duplicate columns and effective sample size.
- It fails closed on malformed columns/scenarios, invalid sign labels, weight-length mismatches, booleans, negative/non-finite weights and zero total weight.
- Commit [17f845e](https://github.com/Baltas80/Kini-/commit/17f845ec7134103c954ad278eff162f0d6112838) added six regression tests and made the existing independence estimate explicit in the optimizer response while retaining the legacy `joint_coverage` field for compatibility.
- Commit [f19ea6e](https://github.com/Baltas80/Kini-/commit/f19ea6e3714537c317edce4a3c47d565a0afbe8d) hardened weight scaling. The implementation now scales before summing/squaring and rejects an overflowing aggregate before multiplication, without emitting a NumPy runtime warning. It also rejects non-string outcome labels.

The existing optimizer still selects doubles/triples by the product of marginal selected-sign masses. The new evaluator measures a supplied joint scenario set; it does not yet optimize selections against that set. No correlation-aware optimizer or historical joint-coverage result is claimed.

### Validation on final code head

- PR CI [43757548790](https://github.com/Baltas80/Kini-/actions/runs/43757548790): Ruff passed; **181 tests passed, 4 upstream warnings**.
- Historical-data validation [43757548930](https://github.com/Baltas80/Kini-/actions/runs/43757548930): passed, including dataset construction and canonical identity validation.
- Live KinielaGPT diagnostic [43757548696](https://github.com/Baltas80/Kini-/actions/runs/43757548696): passed its change filter and skipped the external inspection because the provider adapter did not change.
- No historical model backtest was rerun because this unit changed only ticket-coverage evaluation and its tests, not predictive models, features or training data.

The push-triggered historical-backtest run [43757543794](https://github.com/Baltas80/Kini-/actions/runs/43757543794) failed before job creation (zero jobs returned by the Actions jobs endpoint). The PR CI and historical-data validation runs above completed successfully. This remains a workflow-level trigger/startup issue; it is not reported as a model or pytest failure. No change to `master` was made to investigate it.

### Official historical Quiniela source discovery

- SELAE's official results search page is [Resultados de La Quiniela](https://www.loteriasyapuestas.es/es/resultados/la-quiniela). It exposes a date-range search and a historical-results link to [HistoricoQuiniela.xls](https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Calendarios/HistoricoQuiniela.xls).
- A date-specific official result page, for example [23 November 2025](https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-23-de-noviembre-de-2025), exposes the ordered 14 fixtures, their scores and 1/X/2 signs, plus Pleno al 15.
- The XLS binary could not be downloaded or inspected in this execution environment. Its schema and whether it contains only dates or additional draw metadata remain unverified. The date-specific pages do not visibly expose a separate stable draw ID; a date/URL key must be checked for uniqueness before it is adopted.
- A third-party API advertises historical results since 2004 but requires an API key; it was not used as a source of truth.

### Next action

Retrieve the official SELAE historical calendar XLS through a binary-capable runner, inspect its schema, and use its draw dates to fetch and hash the corresponding official date-specific result pages. Build a dataset of complete, ordered 14-match scenarios with stable source IDs and explicit exclusions for incomplete/void fixtures. Only then compare the independence estimate with held-out joint-scenario coverage and consider a scenario-aware optimization objective.

No predictive benchmark metrics changed in this execution. PR #9 remains a draft and unmerged; `master` remains untouched.

## Historical-backtest workflow repair — 2026-11-15

### Root cause

The branch's .github/workflows/historical-backtest.yml contained two identical backtest job keys. Between them was a stray tab-prefixed fragment from an earlier changes-job shell script. The file had 500 lines, and GitHub rejected it before job creation; affected push runs returned zero jobs. This was a workflow-definition failure, not a test, model or data failure.

### Repair

Commit [942320e](https://github.com/Baltas80/Kini-/commit/942320ef07309bb1e2f13d41c2cf7e03250215ca):

- Removes the malformed trailing fragment and duplicate backtest job; the workflow is now 287 lines with exactly one changes job and one backtest job.
- Adds a job-level condition to skip push events on non-master branches, while preserving PR, manual and scheduled execution.
- The repaired workflow is now parsed by GitHub and creates both changes/backtest jobs.

### Validation

- PR CI [43757784608](https://github.com/Baltas80/Kini-/actions/runs/43757784608): Ruff passed; **181 tests passed, four upstream warnings**.
- Historical-data validation [43757784623](https://github.com/Baltas80/Kini-/actions/runs/43757784623): passed.
- Live diagnostic filter [43757784610](https://github.com/Baltas80/Kini-/actions/runs/43757784610): passed and skipped the external request.
- Repaired historical walk-forward [43757784652](https://github.com/Baltas80/Kini-/actions/runs/43757784652): workflow parsed successfully; the changes job passed and the backtest job has reached the historical comparison step. Metrics and acceptance status remain pending until that job completes.

The prior zero-job failure [43757667066](https://github.com/Baltas80/Kini-/actions/runs/43757667066) is now explained by the malformed workflow file. No changes to master and no PR merge.

## CI workflow lint guard — 2026-11-15

Commit [24500cc](https://github.com/Baltas80/Kini-/commit/24500cc251f3c2faae2bfeab9c4a18679a018e25) adds raven-actions/actionlint@v2 to the main CI job. This validates all GitHub Actions workflow definitions on relevant PRs, addressing the gap that allowed the duplicated historical-backtest job and malformed trailing fragment to reach GitHub.

Validation on this commit:
- Actionlint workflow validation: passed.
- PR CI [43758043087](https://github.com/Baltas80/Kini-/actions/runs/43758043087): Ruff passed; **181 tests passed, four upstream warnings**.
- Historical-data validation [43758043114](https://github.com/Baltas80/Kini-/actions/runs/43758043114): in progress at the time of this record.
- Full historical walk-forward [43757784652](https://github.com/Baltas80/Kini-/actions/runs/43757784652): still in the historical comparison step; no refreshed metrics are claimed.
- The workflow repair has been validated structurally: the repaired PR run creates a changes job and a backtest job instead of failing before job creation.

Next action is to capture the completed walk-forward artifact and acceptance checks. The subsequent scheduled execution should continue from the latest successful backtest head rather than repeat this audit.
## SELAE historical workbook access diagnostics — 2026-11-15

### Reproducible inspection tooling

- Added scripts/inspect_selae_historical_calendar.py to download the official HistoricoQuiniela.xls, verify the OLE/BIFF signature and size bounds, compute SHA-256, inspect every worksheet, and export every non-empty raw row with its original cell type to JSONL.
- The report records retrieval time, HTTP metadata, workbook sheet dimensions, date-cell counts, first/last row samples, and the source-file hash. It explicitly does not infer draw IDs or row semantics before the workbook schema has been reviewed.
- Added xlrd>=2.0.1 to development dependencies only, plus regression tests for text, numeric zero, Excel dates, booleans, errors, blank cells, empty-row detection, and HTML/truncated-file rejection.
- Added a manual workflow_dispatch workflow, .github/workflows/selae-historical-calendar-inspection.yml. It is manual-only after the access test below so future code changes do not repeatedly hit a known provider block.
- The main CI now runs Ruff lint and formatting checks on the inspector and its tests. Documentation-only changes no longer trigger the main CI workflow.

### Official-source access result

The inspection workflow [43763253282](https://github.com/Baltas80/Kini-/actions/runs/43763253282) attempted the official results index, a date-specific official result page, and the official XLS from a GitHub-hosted runner. All three requests returned HTTP 403 with an Akamai edgesuite.net Access Denied response. The diagnostic artifact [14181346104](https://github.com/Baltas80/Kini-/actions/runs/43763253282/artifacts/14181346104) contains the three response samples and structured status metadata.

This is a source-network/WAF restriction on the hosted runner, not an XLS parsing failure: no workbook bytes were delivered, so the XLS schema remains unverified. The inspection workflow is now manual-only; repeated automatic retries would not add evidence. Do not substitute third-party result sites or datasets as the source of truth. Bulk scenario construction remains blocked until the official workbook or equivalent official export can be retrieved through a browser-capable session or supplied as a file.

### Completed walk-forward baseline

The repaired historical walk-forward [43757784652](https://github.com/Baltas80/Kini-/actions/runs/43757784652) completed successfully, including all workflow acceptance checks. Its artifact reports 5,011 test fixtures from 2020-12-11 through 2026-11-09. All five required model streams produced exactly 5,011 predictions with zero recorded prediction errors; the workflow explicitly rejects empty or partial model samples.

On the 4,424 fixtures shared with the schedule-screened market sample:

| Model | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|
| Dixon-Coles | 48.06% | 0.616357 | 1.027499 |
| ML | 43.78% | 0.647471 | 1.074246 |
| Ensemble | 47.81% | 0.613563 | 1.023018 |
| DC/ML fixed ensemble | 47.40% | 0.616095 | 1.026842 |
| DC/ML adaptive ensemble | 47.49% | 0.616305 | 1.027133 |
| Market | 50.72% | 0.597504 | 0.999444 |

The market remains better on the identical 4,424-match sample. The market audit contains 5,011 odds-bearing fixtures, 4,424 schedule-compatible fixtures, and 587 excluded as ambiguous (Friday/Tuesday collection-day cases). This is a conservative schedule screen, not proof of exact per-fixture odds capture timestamps.

Prequential calibration used only prior out-of-sample forecasts and excluded same-calendar-day outcomes. On its 3,847-match common market sample, the ensemble's Brier changed from 0.611315 to 0.611522 and Log Loss from 1.019753 to 1.019966 after calibration; ECE improved, but the proper scoring rules worsened slightly. The calibrated market remained better (Brier 0.596714; Log Loss 0.998094). Do not promote the calibrated ensemble on ECE alone.

### Current validation and continuity

- Historical-data validation [43763639957](https://github.com/Baltas80/Kini-/actions/runs/43763639957) passed, and the latest validation on documentation head `db10e32` [43764336134](https://github.com/Baltas80/Kini-/actions/runs/43764336134) also passed dataset construction, canonical team identity checks, and generated-profile validation.
- The CI run for the current head is still in progress; earlier attempts exposed only Ruff formatting issues in the new inspector, which have been corrected in commit e3b1a50. Do not mark CI green until the current run completes.
- A separate full walk-forward [43763046836](https://github.com/Baltas80/Kini-/actions/runs/43763046836), triggered by the development-only xlrd dependency change, is still in the historical-comparison step. It is not a new result until its model acceptance steps pass.
- PR #9 remains open as a draft against feat/canonical-team-identity-registry. No PR was merged and master was not modified.

### Next actions

1. Confirm the current CI run and its 186-test suite.
2. Capture and validate the result of the in-progress walk-forward only if it completes; do not launch another full run while it remains active.
3. Continue the point-in-time audit. In particular, review all public baseline helpers for the same strict source-eligibility gates already used by the live prediction path.
4. Resume joint-scenario dataset construction only after official SELAE calendar/results bytes are available. Until then, the optimizer must continue to label its current product-of-marginals estimate as an independence approximation.
## SELAE inspector validation correction — 2026-11-15

The first CI run that reached the new date-cell test exposed an API namespace mistake: xlrd's date conversion functions are provided by the xlrd.xldate module, not as top-level xlrd attributes. The parser and test now import that module explicitly in commit f171b54. This was a test/API integration failure, not a failure of the historical workbook parser against source data; the official workbook remains inaccessible from the hosted runner as documented above.

- CI [43763909260](https://github.com/Baltas80/Kini-/actions/runs/43763909260): Ruff and formatting passed; 185 tests passed and one date-serialization test failed on the incorrect xlrd attribute.
- CI [43764064931](https://github.com/Baltas80/Kini-/actions/runs/43764064931): exposed an import-order issue after the xlrd namespace correction.
- The import order was corrected in `823a0cb`; latest PR CI [43764223973](https://github.com/Baltas80/Kini-/actions/runs/43764223973) is green: actionlint passed on six workflows, Ruff lint/format passed, and **186 tests passed with four upstream warnings**.
- Historical-data validation [43764064913](https://github.com/Baltas80/Kini-/actions/runs/43764064913): pending.
- The older full walk-forward [43763046836](https://github.com/Baltas80/Kini-/actions/runs/43763046836) remains in its historical-comparison step. No new model metrics are claimed from it.

The latest code commit is `823a0cb`; this audit entry records its completed CI result. PR #9 remains open as a draft. No merge or master change.


## LAE baseline temporal-eligibility correction — 2026-11-15

A point-in-time review of the public `baseline_probabilities(source="lae")` helper found that it read `Match.lae` whenever the raw field was non-empty. Unlike the live `KiniEngine` path and the market baseline, this helper did not require verified fixture identity, source provenance, fresh timezone-aware kickoff evidence, a strictly pre-kickoff capture, or a valid normalized 1/X/2 vector. Unverified LAE data could therefore enter a diagnostic baseline even though it was excluded from live forecasts.

The helper now requires `Match.has_temporally_eligible_lae` before using LAE. Ineligible or malformed source rows fall back to the uniform baseline; the gate does not repair or normalize untrusted LAE values. A regression test covers an unverified high-confidence vector, a valid timezone-verified pre-kickoff vector, and an invalid probability sum.

The latest pre-fix head `11ff4867562c852a4052cf73c8b36d3a35c81b8a` had green CI [43764494736](https://github.com/Baltas80/Kini-/actions/runs/43764494736): Ruff/actionlint passed and 186 tests passed (four upstream penaltyblog/NumPy warnings). Historical-data validation [43764494726](https://github.com/Baltas80/Kini-/actions/runs/43764494726) passed on 5,311 completed fixtures with zero duplicates, conflicts, invalid result labels or score/result mismatches. The historical-backtest workflow [43764494708](https://github.com/Baltas80/Kini-/actions/runs/43764494708) completed successfully but correctly skipped its expensive model job because this preceding commit changed only documentation/evidence paths; no new predictive metrics are claimed from that run.

This correction affects the public diagnostic baseline helper, not the walk-forward model path or its previously accepted metrics. CI is required for the new regression test; the full historical model benchmark is not required unless predictive model/data inputs change.

### Next action

Continue the point-in-time audit across any remaining public source-derived baseline or diagnostic helpers. Keep official historical Quiniela scenario acquisition blocked and explicit until the official SELAE workbook/result bytes can be retrieved through a non-geoblocked source session; do not fabricate draw IDs or derive joint scenarios from independent fixture rows.


## Public forecast training-window guard — 2026-11-16

A second point-in-time boundary is now enforced at the public model boundary, not only by the walk-forward caller:

- `KiniEngine` rejects a dated forecast if its fitted Dixon–Coles history contains any completed result on the same calendar day or later than the forecast date.
- `FeatureModel.fit_predict_proba()` applies the same check to its explicit training snapshot. Direct use of the ML model can no longer train on labels from the target day or a future day and then forecast backwards.
- The check considers only completed matches because incomplete scheduled fixtures are not used by either model's fitting path. A same-day unplayed fixture remains valid in the training snapshot.
- Undated live-analysis calls (`Match("")`) remain supported for compatibility. They cannot be certified as historical point-in-time forecasts; historical evaluations must provide a forecast date.
- Regression tests cover same-day and future Dixon–Coles contamination, direct ML training contamination, and safe same-day unplayed fixtures.

Validation for this commit is pending. The existing walk-forward path already fits each forecast date from prior-date history, so this is a fail-closed guard for external/public callers rather than a change to the established training split. No changes to `master` and no PR merge.

## Dixon-Coles fit-state hardening — 2026-11-16

### Root cause correction

The earlier suspicion that penaltyblog silently marks an unsuccessful optimizer fit as fitted was not accurate. The upstream BaseGoalsModel._fit implementation raises ValueError when scipy.optimize.minimize(...).success is false, and sets model.fitted = True only after that check. Source: https://github.com/martineastwood/penaltyblog/blob/master/penaltyblog/models/base_model.py

The actual silent-readiness gap was in the Kini adapter:

1. DixonColes.fit() returned normally when fewer than 12 completed matches were available, leaving the wrapped model unfitted.
2. KiniEngine.fit() nevertheless set self.fitted = True.
3. DixonColes.predict() silently returned the fixed 1.35/1.05-goal Poisson fallback when the model was unfitted.
4. _predict_one() called Dixon-Coles even for ML-only, market-only and LAE-only modes, so a failed optional estimator could block independent sources.

### Implemented correction

- DixonColes now exposes fit_status, fit_error, completed training-match/team counts, log-likelihood and AIC.
- A fit is accepted only if penaltyblog.model.fitted is true, likelihood/AIC are finite, and a probe forecast returns valid normalized score-grid and 1/X/2 probabilities.
- Insufficient history remains an explicit insufficient_history state; it is never reported as a fitted model.
- Optimizer/import/validation failures are wrapped as DixonColesFitError. KiniEngine.fit() records the failure and keeps independent ML, market and LAE modes available.
- DC, ensemble and DC/ML ensemble modes fail closed if Dixon-Coles is not fitted. They cannot silently score an untrained fallback as a Dixon-Coles prediction.
- Untrained fallback is available only through an explicit allow_untrained_fallback=True argument. The engine never enables it.
- A fitted model may use the existing cold-start fallback for an unseen team only through an explicit engine argument; this is labelled in Prediction.reasons. Pleno al 15 output now includes pleno_al_15_model_source.
- KiniEngine.model_diagnostics() exposes the model-specific fit state.

### Regression coverage

Six new tests cover insufficient history, explicit fallback, engine readiness, cold-start labelling, independent market/ML operation after DC failure, and a library fit that returns without setting its fitted flag. Existing DC-dependent unit tests now fit a real estimator before substituting a controlled prediction stub; the standalone Pleno aggregation test opts into fallback explicitly.

### Validation

- CI [43779317411](https://github.com/Baltas80/Kini-/actions/runs/43779317411) initially exposed eight old tests that depended on the implicit untrained fallback. Those tests were updated to reflect the fail-closed contract.
- Latest CI [43779494093](https://github.com/Baltas80/Kini-/actions/runs/43779494093) is green: actionlint, Ruff and formatting passed; **197 tests passed**.
- The 20 test warnings all originate from upstream penaltyblog/models/dixon_coles.py:257, where the package assigns a NumPy array shape in a way deprecated by NumPy 2.5. They are non-failing and are not suppressed in Kini.
- Historical-data validation [43779494168](https://github.com/Baltas80/Kini-/actions/runs/43779494168) passed.
- The full walk-forward for the fit-state change is still running in [43779275691](https://github.com/Baltas80/Kini-/actions/runs/43779275691); a latest-head run [43779494166](https://github.com/Baltas80/Kini-/actions/runs/43779494166) is pending. No new predictive metrics are claimed until a completed artifact passes all acceptance checks.
- Live-details inspection was correctly skipped because the relevant source adapter did not change.

### Remaining work

1. Capture the full walk-forward artifact and confirm every required model has the complete sample with zero prediction errors.
2. Add explicit per-model counts for unseen-team cold-start fallbacks to the backtest report. Those forecasts are now labelled in prediction reasons, but the aggregate benchmark does not yet expose their count.
3. Continue official SELAE calendar acquisition. The historical workbook remains unavailable from the hosted runner; no joint Quiniela scenarios may be fabricated or inferred from independent fixtures.

PR #9 remains open and in draft. No PR was merged and master was not modified.


## Unseen-team cold-start reporting — 2026-11-16

The walk-forward comparison now exposes a structured per-model cold-start diagnostic. Each of the five forecast streams records its successful prediction count, unseen-team fallback count, fallback rate and up to 20 dated fixture examples. Counts are sourced from the Dixon-Coles model's explicit prediction-source state rather than inferred by parsing display strings. ML-only forecasts are not counted as DC-dependent; the adaptive DC/ML stream is counted only when both component forecasts succeed.

A regression test covers one unseen-team fixture and one known-team fixture, checks the count and rate for every DC-dependent stream, and verifies that the independent ML stream remains at zero. Existing test doubles without the optional prediction-source diagnostic remain compatible.

### Latest accepted fit-state backtest before cold-start reporting

- Walk-forward [run 43779494166](https://github.com/Baltas80/Kini-/actions/runs/43779494166), code head b5b3b5a8b9fab0605905faa2f891da33dd7e6ae7: **5,011/5,011 predictions** for all five model streams, zero prediction errors; initial training sample 300; test period 2020-12-11 to 2026-11-09.
- The strict market sample contains 4,424/5,011 fixtures; 587 Friday/Tuesday rows are excluded as temporally ambiguous. This remains a schedule screen, not exact per-fixture capture-time verification.
- On the identical 4,424-fixture market intersection:

| Model | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|
| Dixon-Coles | 48.06% | 0.616357 | 1.027499 |
| ML | 43.78% | 0.647471 | 1.074246 |
| Main ensemble | 47.81% | 0.613563 | 1.023018 |
| Fixed DC/ML | 47.40% | 0.616095 | 1.026842 |
| Adaptive DC/ML | 47.49% | 0.616305 | 1.027133 |
| Market | **50.72%** | **0.597504** | **0.999444** |

- Prequential calibration used 3,847 common model/market fixtures. For the main ensemble, Brier worsened from 0.611315 to 0.611522 and Log Loss from 1.019753 to 1.019966; it is not promoted. The market remains better.
- CI [run 43779494093](https://github.com/Baltas80/Kini-/actions/runs/43779494093) passed actionlint, Ruff, formatting and **197 tests**. The 20 test warnings originate in penaltyblog's NumPy 2.5 shape-assignment deprecation.
- Historical-data validation [run 43779494168](https://github.com/Baltas80/Kini-/actions/runs/43779494168) passed. The cold-start reporting code and regression test in the next commit require fresh CI and walk-forward acceptance.

No PR was merged and master was not modified.


## Validation follow-up — 2026-11-16

- Cold-start accounting implementation commit: `70aa42ea8069aa2cfe7bee03ff212177e9692800`.
- CI [run 43785829956](https://github.com/Baltas80/Kini-/actions/runs/43785829956) passed on that code head: actionlint, Ruff/format checks already configured at the time, and **198 tests passed**. The new cold-start regression test is included in that total.
- Historical-data validation [run 43786009207](https://github.com/Baltas80/Kini-/actions/runs/43786009207) passed: 5,311 completed fixtures, seven seasons across two leagues, zero duplicate/conflicting fixtures, zero missing team names or scores, and 56 canonical team identities resolving 10,622 team references.
- Expanding Ruff coverage to the backtesting module exposed five existing style findings (import ordering, redundant integer cast, adjacent-pair iteration and test import style). They were corrected in `26bddef05ffd26155615f83e61871c59612768bf`; the change does not alter model calculations.
- CI for the expanded Ruff scope is running on the latest head. The latest full walk-forward is also pending behind the already-running comparison; the updated workflow will reject missing/inconsistent cold-start counts, rates or examples and will require DC-dependent streams to agree.
- Do not mark cold-start reporting fully validated until the latest-head CI and the walk-forward with the new acceptance step both pass.

Next action: complete latest-head CI and walk-forward validation; then add a season-level cold-start breakdown before deciding whether the fallback policy needs adjustment.

## Cold-start measurement and formatting validation follow-up — 2026-11-16

### Accepted walk-forward evidence

- Historical backtest [run 43786233563](https://github.com/Baltas80/Kini-/actions/runs/43786233563), code head `4644136d3a1cbc0e4877f416ad0313a015b5a036`: **5,011/5,011 predictions** in each of the five model streams, zero prediction errors; initial training sample 300; test period 2020-12-11 to 2026-11-09.
- Cold-start fallbacks: Dixon-Coles **73/5,011 (1.4568%)**; main ensemble, fixed DC/ML and adaptive DC/ML each **73/5,011**; ML-only **0/5,011**. The first 20 retained examples run from 2021-08-13 through 2021-09-18. Because the report intentionally caps examples at 20, this does not prove all 73 are confined to that early-season window. Do not change the fallback policy from this aggregate alone.
- Strict market intersection: 4,424 fixtures; 587 of 5,011 excluded as schedule-ambiguous. On the identical 4,424-fixture sample, the market scores 50.72% accuracy, Brier 0.597504 and Log Loss 0.999444. Dixon-Coles: 48.06%, 0.616357, 1.027499; ML: 43.78%, 0.647471, 1.074246; main ensemble: 47.81%, 0.613563, 1.023018; fixed DC/ML: 47.40%, 0.616095, 1.026842; adaptive DC/ML: 47.49%, 0.616305, 1.027133.
- Interpretation: non-empty model backtests and fallback accounting are now demonstrated on this accepted run, but the market remains superior on the comparable sample. This is not evidence of profitability. Market eligibility is still a schedule screen; exact per-fixture odds capture timestamps remain unavailable.

### CI correction

- Expanded Ruff lint first exposed an extra blank line after the import block in `kini_engine/backtest.py`; corrected in `334529e597ce86c4ab27716c4f98f040259e6ae7`.
- The subsequent formatting check identified pre-existing Ruff formatting drift in `kini_engine/backtest.py` and `tests/test_backtest.py`. Both files were formatted to the exact Ruff diff in commits `057eba07ef2a40f5c3b6db4d0b5b060125d30aed` and `04d6bb31f4a28535e65a48ff85c3c3ceef46ceb6`. These are formatting-only changes; no model calculation was intentionally changed.
- Latest-head CI [run 43791310107](https://github.com/Baltas80/Kini-/actions/runs/43791310107) is running. Latest-head historical backtest [run 43791310144](https://github.com/Baltas80/Kini-/actions/runs/43791310144) is pending behind an earlier comparison [run 43790746411](https://github.com/Baltas80/Kini-/actions/runs/43790746411), which is still running. Historical-data validation [run 43791310181](https://github.com/Baltas80/Kini-/actions/runs/43791310181) is running. Do not mark this follow-up validated until the latest-head CI and backtest complete successfully.

PR #9 remains open and in draft. No PR was merged and `master` was not modified.
## Accepted current-head walk-forward — 2026-11-16

The latest complete walk-forward on the current PR code is [run 43791408878](https://github.com/Baltas80/Kini-/actions/runs/43791408878), head f18f8e8cdb03a880345be0a5cad53d8a3c148a72. It completed all acceptance steps and uploaded artifact [14193691727](https://github.com/Baltas80/Kini-/actions/runs/43791408878/artifacts/14193691727), 170,041 bytes, ZIP SHA-256 3dabf167d550246861a8da44e2754ed208735cdce5374d9b193ec1c19469989b.

- Test period: 2020-12-11–2026-11-09; initial training sample: 300; total out-of-sample fixtures: 5,011.
- Dixon–Coles, ML, main ensemble, fixed DC/ML and adaptive DC/ML each produced 5,011/5,011 forecasts with zero prediction errors.
- The schedule-screened market contains 4,424/5,011 fixtures; 587 Friday/Tuesday odds rows remain excluded as ambiguous. All comparisons below use the same 4,424 fixtures.

| Candidate | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|
| Dixon–Coles | 48.06% | 0.616357 | 1.027499 |
| ML | 43.78% | 0.647471 | 1.074246 |
| Main ensemble | 47.81% | 0.613563 | 1.023018 |
| Fixed DC/ML | 47.40% | 0.616095 | 1.026842 |
| Adaptive DC/ML | 47.49% | 0.616305 | 1.027133 |
| Market | **50.72%** | **0.597504** | **0.999444** |

The market remains superior on accuracy and both proper scoring rules. No model or ensemble is promoted as market-beating. The market is still schedule-screened rather than verified with per-fixture odds-capture timestamps.

Prequential calibration used 3,847 common post-warm-up model/market fixtures, prior out-of-sample forecasts only, a 500-row minimum history, 1,500-row rolling window and refit every 30 dates. For the main ensemble, Brier/Log Loss moved from 0.611315 / 1.019753 raw to 0.611522 / 1.019966 calibrated; calibration is not promoted. The calibrated market scored 0.596714 / 0.998094 on that same sample.

Cold-start diagnostics report 73/5,011 unseen-team fallbacks (1.4568%) for Dixon–Coles and every DC-dependent ensemble; ML-only reports 0/5,011. The report currently retains only the first 20 dated examples, so the aggregate alone is insufficient to change the fallback policy. Commit 6ebd3ad adds a source-backed league/season breakdown and CI acceptance checks that reconcile seasonal denominators and fallback totals to the aggregate counts; final validation is pending.

Historical-data validation [run 43791408933](https://github.com/Baltas80/Kini-/actions/runs/43791408933) succeeded. CI [run 43791408930](https://github.com/Baltas80/Kini-/actions/runs/43791408930) was cancelled before lint or pytest ran; its retry was requested. This cancellation is not counted as a test failure or a passing CI result.

No PR was merged and master was not modified.


### Season-level cold-start diagnostics — implementation and data validation

Commit 6ebd3ad adds per-model by_season output to the walk-forward report. Buckets use the source League/Div and Season fields; no season is inferred from fixture dates. Football-Data four-digit season codes are preserved alongside a readable label. The CI acceptance step checks each bucket's identity, uniqueness, denominator, count and rate, reconciles seasonal totals to aggregate totals, and requires every DC-dependent stream to match Dixon–Coles season by season.

The latest historical-data validation [run 43797467165](https://github.com/Baltas80/Kini-/actions/runs/43797467165) succeeded. Artifact [14194529537](https://github.com/Baltas80/Kini-/actions/runs/43797467165/artifacts/14194529537) contains 5,311 completed fixtures across 14 league/season groups, 2020-09-12–2026-11-09. The generated profile reports zero missing team names, missing final scores, incomplete scores, duplicate fixtures, conflicting duplicates, invalid result labels, score/result mismatches or invalid dates with teams. The source cache age was approximately 17.6 hours at profile generation. Sparse bookmaker columns remain a data-availability limitation, not a fixture-integrity failure.

CI [run 43797153246](https://github.com/Baltas80/Kini-/actions/runs/43797153246) passed actionlint and Ruff lint, then failed only the Ruff formatting check on the new league-label assignment in kini_engine/backtest.py; pytest was not reached. This was a formatting defect, not a test or model failure. Commit 7b00db2 corrected it. Latest-head CI [run 43797467163](https://github.com/Baltas80/Kini-/actions/runs/43797467163) passed actionlint, Ruff lint, formatting and 199 tests; 20 upstream NumPy/penaltyblog deprecation warnings remain.

The current-head walk-forward [run 43797153254](https://github.com/Baltas80/Kini-/actions/runs/43797153254) has completed history construction and the first-ML diagnostic and is running the full comparison. Its seasonal fallback output is not yet available, so the 73/5,011 aggregate must not be used to change fallback policy.

No merge or direct master modification.


### Market-book composition audit — 2026-11-16

An independent calculation from the validated historical-data artifact [14194529537](https://github.com/Baltas80/Kini-/actions/runs/43797467165/artifacts/14194529537) reproduced the 300-match complete-date warm-up and the 5,011-match out-of-sample period (first test date 2020-12-11). On the 4,424 schedule-compatible market fixtures, the current consensus market has this bookmaker-count distribution: 979 fixtures with one book, 354 with two, 1,010 with three and 2,081 with four.

The composition changes sharply over time: every schedule-eligible fixture in 2025/26 and 2026/27 has only Bet365 odds after the Pinnacle stale-feed cutoff and the disappearance of the other feeds. Bet365 is available on 4,417/4,424 schedule-compatible test fixtures; seven consensus-market fixtures lack a complete Bet365 triplet.

On that 4,417-fixture intersection, the equal-weight bookmaker consensus scores accuracy 50.74%, Brier 0.597332 and Log Loss 0.999185; Bet365-only scores 50.80%, 0.597352 and 0.999324. The overall difference is small, but the source composition is not stationary across seasons. This is an offline data audit, not a replacement for the walk-forward artifact. Next P5 action: add a fixed-book Bet365 benchmark to the backtest report and compare models on that exact common sample, while retaining the current consensus benchmark. Do not promote or discard either market reference before the paired result is available.

---
## 2026-11-16 — P5: benchmark fijo Bet365

**Estado:** implementado y validado estadísticamente; corrección de formato de CI en curso.

### Implementación

- dataio.py conserva por partido las probabilidades 1/X/2 sin margen de cada casa disponible, además del consenso de mercado existente.
- Se mantiene el consenso actual: media equiponderada de las probabilidades sin margen de las casas válidas.
- El backtest añade un benchmark Bet365 fijo a partir de B365H/B365D/B365A, invirtiendo las cuotas decimales y normalizando el vector para retirar el overround.
- Se publica una comparación pareada en la que Dixon-Coles, ML, ensemble, ensemble DC/ML, ensemble adaptativo, consenso y Bet365 utilizan exactamente los mismos encuentros.
- La aceptación del workflow comprueba que los recuentos de odds, exclusiones temporales y muestras comunes son coherentes para los cinco flujos de modelo.
- Se documenta que Football-Data no proporciona la hora exacta de captura de cada cuota. El filtro de calendario no demuestra por sí solo que la cuota estuviera disponible y fuera ejecutable antes del inicio.

### Evidencia de datos

Workflow historical-data-validation #43803266946: **success**.

- 5.311 partidos completos, desde 2020-09-12 hasta 2026-11-09.
- 0 equipos faltantes, 0 resultados incompletos, 0 duplicados y 0 discrepancias entre marcador y signo.
- 10.622 referencias de equipos resueltas contra 56 identidades canónicas; 0 referencias ambiguas o sin resolver.
- 5.297 partidos con triplete Bet365 válido en el histórico completo.

### Backtest walk-forward

Workflow historical-backtest #43803266920: **success**. Commit evaluado: 86ab11d.

- Test: 5.011 partidos para cada uno de los cinco flujos de modelo; 0 errores de predicción.
- Consenso de mercado: 4.424 encuentros con calendario compatible; 587 excluidos por ambigüedad de horario.
- Bet365: 5.004 tripletes válidos en el test; 4.417 elegibles tras aplicar el mismo filtro de calendario; 587 excluidos.
- En la muestra común de 4.417 encuentros, cada modelo, el consenso y Bet365 tiene exactamente n=4.417.

| Flujo | Brier | Log Loss |
|---|---:|---:|
| Dixon-Coles | 0.616231 | 1.027290 |
| ML | 0.647375 | 1.074108 |
| Ensemble DC/ML principal | 0.613436 | 1.022809 |
| Ensemble DC/ML fijo | 0.615974 | 1.026639 |
| Ensemble DC/ML adaptativo | 0.616182 | 1.026927 |
| Consenso de mercado | 0.597332 | 0.999185 |
| Bet365 fijo | 0.597352 | 0.999324 |

Métricas Bet365 en su muestra elegible: accuracy 0.508037, Brier 0.597352, Log Loss 0.999324, RPS 0.199785 y ECE 0.023801. Un recálculo independiente desde el CSV histórico reproduce Brier, Log Loss, RPS y ECE con diferencias inferiores a la precisión de redondeo.

### Interpretación

- El consenso y Bet365 superan a los modelos en Brier y Log Loss sobre la misma muestra.
- La diferencia entre consenso y Bet365 es muy pequeña; no se interpreta como una mejora estadísticamente demostrada ni como evidencia de rentabilidad.
- El ensemble principal mejora modestamente a Dixon-Coles, pero no alcanza el benchmark de mercado.
- ML aislado es el peor de los cinco flujos en esta evaluación. No debe recibir más peso por complejidad ni por porcentaje de aciertos.

### CI y seguimiento

- CI #43806744226: success sobre el commit 7b61be5; actionlint, Ruff lint, Ruff format y pytest completados. Resultado: 209 passed, 20 warnings de deprecación procedentes de penaltyblog/NumPy 2.5. Se añadió una prueba que verifica para cada número de dobles que el máximo de triples coincide exactamente con el límite oficial de 31.104 apuestas.
- La validación de datos #43806744234 terminó success: 5.311 fixtures completados, integrity_passed=true y artefacto 14198673097 con CSV, perfil y validación de identidades canónicas.
- El backtest #43805280611 continúa ejecutando la comparación walk-forward; todavía no hay métricas finales nuevas que publicar. La nueva ejecución #43806744219 permanece pendiente de la anterior y no debe duplicar el backtest si el filtro de cambios la clasifica como solo tests/documentación.
- La siguiente prioridad P6 es cerrar el contrato de Pleno al 15 y su multiplicador antes de usar la cobertura como cobertura de boleto completo.


---
## 2026-11-16 — Descubrimiento del archivo oficial paginado de resultados (P6)

La página oficial de resultados de La Quiniela (https://www.loteriasyapuestas.es/es/la-quiniela/resultados) expone paginación histórica. En la inspección web del 16-11-2026 se observaron 80 páginas. La página 2 (page=1 en el componente XHR) devolvió 20 enlaces, desde el resultado del 16-08-2026 hasta el del 22-04-2026. La página 80 (page=79) devolvió dos enlaces antiguos; uno muestra la fecha 15-04-2011, pero su URL conserva marcadores de plantilla (VAL_DIA, VAL_MES, VAL_ANYO) y la ficha no contiene el detalle de los partidos. Esa fecha se considera solo texto de enlace, no fecha de sorteo verificada.

Una ficha oficial de resultados del 16-08-2026 expone por separado los 14 partidos, equipos locales, visitantes, marcadores y signos. En la quinta posición aparece marcador "-" y signo "X"; no se atribuye una causa (aplazamiento, sorteo u otra resolución) sin consultar la evidencia específica de esa jornada. Esto confirma que el importador histórico debe separar siempre el signo del cupón del resultado futbolístico y no convertir un marcador ausente en goles.

La inspección de una ficha del 23-11-2025 confirma el mismo formato de 14 signos y Pleno al 15. No se han descargado ni validado todas las fichas históricas, no se ha inferido ningún ID de sorteo y todavía no existe un conjunto de escenarios históricos aceptado.

### Implementación de descubrimiento

- scripts/discover_selae_result_archive.py enumera las páginas oficiales y extrae únicamente enlaces, fechas explícitas en el slug y fechas visibles solo en el texto del enlace.
- Cada fecha lleva procedencia (slug, label_only o unresolved); las fechas label_only no se presentan como fechas verificadas.
- El informe conserva URL, página, hash SHA-256 de cada respuesta, rango de fechas derivado de slugs y recuentos de enlaces sin fecha.
- El workflow manual selae-result-archive-discovery publica el informe y el JSONL de enlaces.
- Este proceso no descarga las fichas de resultado, no interpreta signos ni premios, no crea IDs y no habilita entrenamiento ni backtesting de boletos.

### Siguiente paso P6

Ejecutar el descubrimiento desde un entorno con acceso a SELAE. Si la descarga es accesible, inspeccionar las fichas de resultado por lotes y definir un esquema versionado que distinga partidos disputados, aplazados y signos determinados por sorteo público. Después, reconciliar cada jornada con sus 14 fixtures y Pleno al 15 antes de calcular cobertura histórica. Si SELAE bloquea el entorno, conservar el error y el diagnóstico; no sustituir la fuente oficial por datos no verificados.


---
## 2026-11-16 — Validación reglamentaria del múltiple directo y Pleno al 15 (P6)

Se contrastó el optimizador con las normas oficiales de SELAE, documento Normas que regulan el juego La Quiniela con Elige8 (octubre de 2019), actualmente enlazado desde la página oficial de normativa.

- La norma 18.2 establece que el Pleno al 15 multiplica las apuestas desarrolladas con los otros 14 partidos según el número de categorías marcadas para cada equipo; el multiplicador puede llegar a 16.
- La norma 21.3 exige tener en cuenta el Pleno al 15 al determinar el máximo de apuestas autorizadas en los métodos múltiples.
- La norma 22 remite al Anexo I para las combinaciones autorizadas del método múltiple directo.
- El apartado D de apuestas que participan fija un mínimo de 2 y un máximo de 31.104 apuestas por boleto, incluido el Pleno al 15.
- La norma 5 fija el precio en 0,75 EUR por apuesta.

El límite de 31.104 y la tabla de dobles/triples implementados en TicketOptimizer son coherentes para un único pronóstico del Pleno (multiplicador 1). El contrato actual declara explícitamente pleno15_multiplier=1 y KiniEngine selecciona una única categoría de Pleno para el cálculo de cobertura independiente. Por tanto, el optimizador no debe presentarse como compatible con boletos que marquen varias categorías del Pleno: en ese caso el multiplicador debe reducir el número de combinaciones de los 14 partidos para que el total siga siendo <= 31.104. La selección múltiple del Pleno queda pendiente de implementación y prueba; no se modifica silenciosamente el presupuesto actual.

Fuente normativa oficial: https://www.loteriasyapuestas.es/f/loterias/documentos/normativa/Normativa%20de%20los%20juegos/Normas_de_la_Quiniela_y_Elige8_Octubre_2019.pdf


---
## 2026-11-16 — Diagnóstico de bloqueo de SELAE y vía local de importación

La ejecución GitHub Actions 43807527115 confirma HTTP 403 desde el runner para los índices español e inglés, el RSS oficial, el endpoint de resultados por fecha, el PDF oficial de prensa y los dos endpoints XHR de paginación. El informe de diagnóstico se conserva en el artefacto 14198398686. No se ha intentado eludir el bloqueo mediante proxies ni se han usado espejos de terceros como fuente de verdad.

Se añade scripts/import_selae_press_release.py como vía reproducible para importar PDFs oficiales descargados localmente. El parser exige fecha explícita en el documento, 14 signos 1/X/2 y las dos categorías del Pleno en 0/1/2/M; registra el SHA-256 del PDF y deja el escenario en estado scenario_imported_unreconciled hasta reconciliarlo. La dependencia pypdf queda en el extra opcional [selae]. Se añaden tests con vectores publicados en notas de prensa oficiales de 08-11-2026, 01-11-2026 y 17-12-2023; estos tests validan el parser, no constituyen por sí mismos un histórico completo.


---
## 2026-11-16 — CI formatting follow-up for SELAE official PDF import

- PR #9 head `3e41da3a5f9cbb563c2f305752b09a1c2260ef91` passed predictive-core/fixture-reconciliation Ruff lint, but CI run [43807949841](https://github.com/Baltas80/Kini-/actions/runs/43807949841) failed at `ruff format --check` before pytest. The four files were `scripts/discover_selae_result_archive.py`, `scripts/import_selae_press_release.py`, `tests/test_selae_press_release.py` and `tests/test_selae_result_archive.py`; the failure was formatting-only.
- Applied the exact Ruff formatting changes without changing parser, discovery or model semantics. Historical-data validation [43807949993](https://github.com/Baltas80/Kini-/actions/runs/43807949993) passed on the pre-fix head. Historical backtest [43807949935](https://github.com/Baltas80/Kini-/actions/runs/43807949935) was pending at the time of this update and must be inspected before accepting current model validation.
- Next: verify CI on the formatting-fix commit, collect the pending walk-forward result if still valid, then continue P6 by reconciling an official local press-release PDF against the exact 14 fixtures and Pleno al 15. SELAE HTTP 403 from GitHub runners remains an explicit source-access limitation; no proxy or third-party mirror is treated as official evidence.

- Formato Ruff corregido en el commit `a43333995498977988c852d2bece4b0718160a46`. Se añadió una prueba adicional para fechas ISO imposibles y rechazo de archivos que no sean PDF antes de la extracción; la validación CI debe ejecutarse sobre el nuevo head, no sobre el commit previo al arreglo.


---
## 2026-11-16 — Vector oficial reciente para el parser SELAE

La nota oficial de prensa del sorteo de 15-11-2026 publica el vector `2 - X - 1 - X - 2 - 1 - 1 - X - 1 - 1 - 1 - 2 - 2 - X - 2M` y confirma la fecha del sorteo. Fuente oficial: https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Notas%20de%20prensa/NOTA_DE_PRENSA_LA_QUINIELA_15_11_26.pdf. Se incorpora como regresión de parsing para el formato compacto de Pleno `2M`. La extracción textual del buscador permite verificar el contenido publicado, pero la descarga binaria del PDF desde el entorno de ejecución falló; por tanto, no se registra SHA-256 ni se afirma que el importador local haya generado un artefacto. El bloqueo HTTP 403 de GitHub Actions sigue abierto.


---
## 2026-11-16 — Validación CI y datos en el head 950fccc

- **CI:** [run 43808967651](https://github.com/Baltas80/Kini-/actions/runs/43808967651) completado con éxito sobre `950fccc834409bde73741121dfb1927d415b28d7`. Actionlint encontró 0 errores en 7 workflows; Ruff lint y format pasaron; pytest: **222 passed** en 2,57 s. Los 20 avisos proceden de `penaltyblog/models/dixon_coles.py:257`, por asignación de `.shape` a un array bajo NumPy 2.5; no son fallos de tests.
- **Datos históricos:** [run 43808967647](https://github.com/Baltas80/Kini-/actions/runs/43808967647) completado con éxito en el mismo head. El rebuild produjo 5.311 partidos completos; 0 nombres ausentes, 0 resultados ausentes/incompletos, 0 duplicados, 0 duplicados conflictivos y 0 discrepancias entre marcador y signo. La validación de identidad resolvió 10.622 referencias en 56 IDs canónicos, con 0 no resueltas y 0 ambiguas. `integrity_passed=true`. ZIP del artefacto: `72510def134287eefbd005c5a3e44eaefc8eabee50685e25d4ced534a9729a56`.
- **Backtest:** [run 43807909291](https://github.com/Baltas80/Kini-/actions/runs/43807909291) sigue ejecutando la comparación histórica sobre el head anterior `5dbc9c95e088b26c06124275d23f0ab51ac325ca`; [run 43808967666](https://github.com/Baltas80/Kini-/actions/runs/43808967666) está pendiente para el head actual. La comparación Git entre ambos heads confirma que los siete commits intermedios solo cambian este registro, scripts SELAE y tests; no cambian `kini_engine/core.py` ni `kini_engine/backtest.py`. No se declara todavía aceptado el backtest ni se publican métricas hasta que termine y pase sus gates.
- **SELAE:** [run 43808823319](https://github.com/Baltas80/Kini-/actions/runs/43808823319) confirma HTTP 403 en los índices oficiales español e inglés desde GitHub Actions. La nota oficial del 15-11-2026 se pudo verificar en la fuente documental y el vector compacto `2M` está cubierto por test; la descarga binaria local falló, por lo que no existe aún PDF importado ni SHA-256 de archivo.
- **Estado de integración:** PR #9 continúa en borrador contra `feat/canonical-team-identity-registry`; no se ha modificado `master` ni se ha fusionado ningún PR.

**Siguiente acción prioritaria:** recoger el resultado de la comparación walk-forward que ya está en curso, comprobar que los cinco modelos obligatorios tienen `n == n_total` y cero errores, y revisar cold-start, mercado con cuotas temporalmente elegibles, benchmark Bet365 y calibración prequential. Después, continuar la cobertura P6 del Pleno múltiple y la reconciliación de nuevos cupones con evidencia independiente.


---
## 2026-11-16 — P6: Pleno al 15 multiplier in direct-multiple optimization

**Implementation status: committed; CI and data-integrity validation passed; current-head walk-forward validation remains in progress.**

- TicketOptimizer.optimize() now accepts explicit home and away Pleno category sets using the official categories 0, 1, 2 and M.
- The Pleno multiplier is the Cartesian product of the selected category counts. The optimizer constrains column_count × pleno15_multiplier to the statutory 31,104 total-bet cap and calculates cost from total payable bets at the configured per-bet price.
- The default KiniEngine.quiniela() behavior remains the most probable single joint Pleno pair. Callers can request multiple categories; the response reports selected combinations, selected Pleno probability mass and the full-coupon independent coverage estimate.
- Regression tests cover the 16-combination Pleno multiplier, the 31,104 total-bet boundary, the two-bet minimum with one 14-match column, invalid/partial category sets and end-to-end coverage/cost accounting.
- The independent-match coverage approximation is unchanged. This work does not add expected-prize modelling, joint dependence across the 14 matches, reduced/conditioned systems or Elige8.
- Validation evidence will be appended only after CI and the current-head historical backtest gates complete.


### Validation evidence — 2026-11-16

- Implementation commit: 468b34417d9cace03675404121ec41cbe9aa1a6a (P6 optimizer and regression contract); previous feature commit: f512f9c4c47203f8b61835ac236a4958476b2dec.
- CI run 43816060895: **success**. Ruff lint passed, formatting check passed, and pytest reported **226 passed** (21 third-party NumPy/penaltyblog deprecation warnings).
- Historical-data validation run 43816060879: **success**. The generated dataset contains 5,311 completed fixtures from 2020-09-12 to 2026-11-09. Team identity registry resolved 10,622/10,622 references to 56 canonical IDs, with 0 unresolved and 0 ambiguous references. Dataset checks reported 0 duplicates removed, 0 missing team names, 0 missing/incomplete final scores and 0 score/result mismatches.
- Previous successful walk-forward artifact 43807909291 (commit 5dbc9c95e088b26c06124275d23f0ab51ac325ca) remains the latest completed predictive benchmark: 5,011 out-of-sample forecasts for each of Dixon-Coles, ML, ensemble, DC+ML ensemble and adaptive ensemble; all five reported zero prediction errors. Test window: 2020-12-11 to 2026-11-09; initial training window: 300 matches.
- On the 4,424-match schedule-screened common market sample, the market achieved Brier 0.59750 and log loss 0.99944. The best model-only result was the ensemble at Brier 0.61356 and log loss 1.02302; the market remained better. ML alone was weakest (Brier 0.64747, log loss 1.07425). Do not select an ensemble on accuracy alone.
- The fixed Bet365 benchmark had 4,417 eligible rows (Brier 0.59735, log loss 0.99932). The market eligibility screen excluded 587 of 5,011 odds rows because kickoff timing was ambiguous. It is only a schedule-compatibility screen: exact per-fixture odds capture timestamps are unavailable, so strict point-in-time availability is not yet proven.
- Current-head historical-backtest run 43815638254 was still running at the time of this update. Its results are not yet counted as passed. The pending run for the documentation/test-only follow-up will be allowed to skip after the f512f9c walk-forward completes successfully.


---
## 2026-11-16 — Validación completa del head c16a917 (P0/P4/P6)

Esta sección sustituye los estados pendientes anteriores del backtest tras la ampliación del optimizador Pleno al 15. El head validado es `c16a9178fbd9a560b50c70f78928de419a56f6a5`; el cambio funcional del optimizador está en `468b34417d9cace03675404121ec41cbe9aa1a6a`, y el commit de este head actualiza el registro de auditoría.

### CI y calidad de datos

- CI [43816268711](https://github.com/Baltas80/Kini-/actions/runs/43816268711): actionlint, 7 workflows sin errores; Ruff lint y format correctos; **226 tests pasados** en 1,87 s. Persisten 21 warnings de deprecación originados en `penaltyblog/models/dixon_coles.py:257` por la asignación de `.shape` a un array con NumPy 2.5; no son fallos del proyecto.
- Validación histórica [43816268627](https://github.com/Baltas80/Kini-/actions/runs/43816268627): **5.311 partidos completados**, cero nombres de equipo ausentes, cero marcadores finales ausentes, cero duplicados eliminados o conflictivos y cero discrepancias marcador/signo. El registro de identidad resolvió **10.622/10.622 referencias**, 56 IDs canónicos, cero no resueltas y cero ambiguas; `integrity_passed=true`.
- Artefacto `kini-historical-data`, ID `14202965335`, 714.131 bytes, SHA-256 `c3ff06eddf03965270fe095b69018ca2adfd12eb2141396561affefece22462e`.

### Backtest walk-forward: P0/P3/P4/P5

Backtest [43816268634](https://github.com/Baltas80/Kini-/actions/runs/43816268634), artefacto `historical-backtest` ID `14204028183`, 178.715 bytes, SHA-256 `ffb2c6c5e5d15ab84a3824757e98efe47a8c6b84b3fb54240868ec2aa56ba194`.

- Histórico total: 5.311; ventana inicial de entrenamiento: 300; test walk-forward: **5.011 partidos**, del 11-12-2020 al 09-11-2026.
- Dixon–Coles, ML, ensemble principal, ensemble DC/ML fijo y adaptativo: **5.011/5.011 predicciones cada uno**, cero errores de predicción. Los gates del workflow para muestras no vacías, cold-start, mercado, Bet365 y calibración prequential terminaron correctamente.
- Métricas sobre los 5.011 partidos de test (el mercado solo existe en la submuestra temporalmente filtrada de 4.424):

| Candidato | n | Accuracy | Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|---:|
| Dixon–Coles | 5.011 | 48,174 % | 0,616668 | 1,027806 | 0,208245 | 0,011423 |
| ML | 5.011 | 44,143 % | 0,645534 | 1,071417 | 0,219951 | 0,044087 |
| Ensemble principal | 5.011 | 47,935 % | 0,613630 | 1,023028 | 0,207026 | 0,012840 |
| DC/ML fijo | 5.011 | 47,575 % | 0,615866 | 1,026405 | 0,208008 | 0,009508 |
| DC/ML adaptativo | 5.011 | 47,715 % | 0,616077 | 1,026712 | 0,208079 | 0,008118 |
| Mercado multi-casa filtrado | 4.424 | **50,723 %** | **0,597504** | **0,999444** | **0,199876** | 0,024213 |

Comparación adicional sobre la muestra idéntica de **4.417** partidos con Bet365 y los cinco streams de modelo:

| Candidato | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|
| Dixon–Coles | 48,056 % | 0,616231 | 1,027290 |
| ML | 43,784 % | 0,647471 | 1,074246 |
| Ensemble principal | 47,807 % | 0,613563 | 1,023018 |
| DC/ML fijo | 47,401 % | 0,616095 | 1,026842 |
| DC/ML adaptativo | 47,491 % | 0,616305 | 1,027133 |
| Consenso multi-casa sin margen | **50,736 %** | **0,597332** | **0,999185** |
| Bet365 sin margen | **50,804 %** | **0,597352** | **0,999324** |

El mercado sigue superando a todos los candidatos en las métricas probabilísticas principales. No se promueve ML ni ningún ensemble como sustituto del mercado. El mercado continúa siendo un benchmark con filtro de calendario, no una cotización cuya captura pre-partido esté demostrada.

### Calibración prequential

La calibración usa exclusivamente predicciones OOF walk-forward anteriores y excluye resultados del mismo día. Configuración: warm-up mínimo 500, ventana 1.500, refit cada 30 fechas, mínimo 20 observaciones por clase y regularización 0,05. Se evaluaron 4.480 predicciones post-warm-up por modelo y una intersección común modelo/mercado de 3.847 partidos.

Brier / Log Loss en esa intersección (raw → calibrado):

| Candidato | Brier raw → calibrado | Log Loss raw → calibrado |
|---|---:|---:|
| Dixon–Coles | 0,613791 → 0,613232 | 1,023639 → 1,022458 |
| ML | 0,638702 → 0,632937 | 1,060984 → 1,051149 |
| Ensemble principal | 0,611315 → 0,611522 | 1,019753 → 1,019966 |
| DC/ML fijo | 0,613518 → 0,613653 | 1,023036 → 1,023129 |
| DC/ML adaptativo | 0,613703 → 0,613727 | 1,023289 → 1,023189 |
| Mercado | 0,597564 → 0,596714 | 0,999533 → 0,998094 |

**Decisión:** no activar calibración como salida predeterminada del ensemble: empeora ligeramente Brier y Log Loss del ensemble principal y el mercado mantiene una ventaja clara. DC y ML mejoran agregadamente, pero no cierran la brecha. La calibración queda como diagnóstico/experimento prequential.

### Cold-start

En los 5.011 partidos, el fallback se activó en 73 predicciones de Dixon–Coles y los ensembles (1,457 %); ML registró cero. Los diagnósticos se conservaron por modelo y temporada. Esto no sustituye una evaluación separada de equipos nuevos fuera de muestra.

### P6 — Pleno al 15 y límite reglamentario

La ampliación del commit `468b344` permite pasar conjuntos explícitos de categorías 0/1/2/M para local y visitante. El multiplicador es el producto cartesiano de ambos conjuntos. El DP limita simultáneamente columnas de 14 partidos y apuestas totales, aplicando el máximo SELAE de **31.104 apuestas incluido el Pleno** y el coste sobre el total pagadero.

- Con las 4 categorías para cada equipo: multiplicador 16, máximo de 1.944 columnas de 14 partidos y 31.104 apuestas totales.
- Coste al precio configurado de 0,75 EUR: 23.328,00 EUR para el máximo reglamentario.
- Se mantienen el mínimo de dos apuestas y la tabla oficial de dobles/triples.
- Las pruebas cubren multiplicador 16, límite exacto, mínimo de dos apuestas con una columna, categorías parciales/duplicadas/ inválidas y el flujo de extremo a extremo de coste y cobertura.
- La cobertura sigue siendo una aproximación de independencia entre los 14 partidos y las categorías seleccionadas del Pleno. No estima premios, correlación real, rentabilidad ni sistemas reducidos/condicionados o Elige8.

### Límites y siguiente trabajo

- 587 registros de cuotas siguen excluidos por ambigüedad temporal (viernes/martes); no existen timestamps de captura por partido. El benchmark Bet365 tiene 4.417/5.004 filas elegibles.
- No se ha completado la auditoría de disponibilidad temporal/publicación de cada feature histórica. El corte por fecha estrictamente anterior es conservador, pero no acredita por sí solo el instante de publicación de cada resultado.
- El workflow de descubrimiento del archivo SELAE [43816268620](https://github.com/Baltas80/Kini-/actions/runs/43816268620) se omitió correctamente porque el código de descubrimiento no cambió. La inspección activa anterior [43808823319](https://github.com/Baltas80/Kini-/actions/runs/43808823319) registró HTTP 403 desde el runner en los endpoints oficiales; no se declara importación histórica completa de cupones.
- Próximas prioridades: (1) auditoría feature-by-feature de observación, publicación, ventana y disponibilidad antes del kickoff; (2) conseguir un flujo reproducible de PDFs oficiales SELAE descargados localmente o acceso oficial estable y reconciliar jornadas completas; (3) ampliar la evaluación del optimizador con escenarios conjuntos y premios históricos cuando existan datos oficiales suficientes.

PR #9 sigue en borrador y basado en `feat/canonical-team-identity-registry`. No se ha modificado `master` ni se ha fusionado ninguna PR.


---
## 2026-11-16 — Auditoría point-in-time de features (P2, revisión estática)

Se revisaron `kini_engine/core.py`, `kini_engine/backtest.py`, `kini_engine/dataio.py` y sus pruebas sobre el head posterior a la validación P6.

| Componente | Variables/inputs observados | Corte temporal aplicado | Estado |
|---|---|---|---|
| ML (12 features) | Puntos, goles a favor y en contra en los últimos 8 partidos: local y visitante en global; local solo como local; visitante solo como visitante | `_prior_completed_matches` exige fecha de origen estrictamente anterior; `_training_rows` calcula las features de toda una fecha antes de añadir resultados de esa fecha | Sin leakage de mismo día/futuro en el código revisado; disponibilidad exacta de publicación histórica no demostrada |
| Contexto de forma | Últimos 5 partidos completados por equipo | Mismo filtro de fecha estrictamente anterior | Conservador por fecha; sin timestamp de publicación |
| H2H | Hasta 10 enfrentamientos previos, mínimo 5 | Se construye desde el histórico ya filtrado | Sin uso de enfrentamientos del mismo día/futuros |
| Dixon–Coles | Marcadores completados, equipos y fechas para fuerzas y decaimiento temporal | Backtest agrupa por día y añade el grupo al entrenamiento solo después de pronosticar todos sus partidos; el motor rechaza resultados de fecha igual o posterior | Sin leakage de calendario en walk-forward; la hora de publicación de resultados no está disponible |
| Ensemble adaptativo/calibrador | Predicciones OOF anteriores y resultados asociados | Pesos/calibradores se fijan antes de la primera predicción del día; resultados se agregan tras completar el grupo diario | Prequential y aislado por día, validado por los gates del backtest |
| Mercado | Cuotas pre-cierre B365/WH/VC/Pinnacle, sin margen por casa | Filtro conservador: viernes/martes excluidos; Pinnacle retirado desde 23-07-2025 por feed obsoleto | Solo compatibilidad de calendario; sin captura individual ni zona horaria acreditadas |
| LAE (porcentajes XML vía Quinielista) | Vector 1/X/2, hora de recepción de la respuesta, identidad de fixture y evidencia de kickoff | Crosswalk por nombre local/visitante + orden; captura posterior a la comprobación de calendario, dentro de 24 h y anterior al kickoff | El adaptador MCP sí transmite los metadatos. El proveedor no ofrece timestamp de publicación/actualización; la hora registrada es recepción del cliente |
| Clasificación, alineaciones, lesiones, clima | No entran en la matriz ML de 12 features | No aplicable | Excluidos por falta de procedencia/publicación point-in-time |

### Corrección de reproducibilidad temporal

La revisión encontró que Dixon–Coles convertía `Match.date` a timestamp y luego a `datetime.fromtimestamp`, lo que puede desplazar una fecha con zona horaria explícita al día anterior según la zona horaria del runner. Se sustituye por medianoche de la fecha de calendario de origen, coherente con el corte diario conservador. La regresión usa una fecha con offset `+02:00` y comprueba que las fechas enviadas a `dixon_coles_weights` son fechas de origen estables y sin zona horaria.

### Límite P2 que permanece abierto

La auditoría estática no puede certificar el instante de publicación de los resultados históricos ni el timestamp de captura de cuotas: Football-Data no los proporciona en el CSV utilizado. Por tanto, el estado correcto es **sin leakage de calendario en la implementación revisada**, no una demostración absoluta de disponibilidad real de cada dato en el instante de predicción. No se incorporan alineaciones, lesiones, clima ni tablas reconstruidas a posteriori.


### Corrección de la auditoría LAE y zonas CET/CEST

La revisión del adaptador confirma que `KinielaGPTSource.probabilities` adjunta `lae_source`, `lae_captured_at`, `kickoff_at`, URL y hora de comprobación de evidencia, y que `mcp_server.py` transmite esos campos a `Match.detail`. La afirmación anterior de que el adaptador MCP no conservaba los metadatos era incorrecta y queda sustituida por la fila de la tabla.

El crosswalk actual `data/kinielagpt_fixture_kickoffs.json` corresponde a la jornada 22/temporada 2027 y declara 15/15 fixtures verificados por pareja exacta normalizada local/visitante y número de orden, sin alias ni fuzzy matching. El diagnóstico [43752475866](https://github.com/Baltas80/Kini-/actions/runs/43752475866) confirmó el esquema de 15 detalles y 15/15 correspondencias. Su artefacto no incluía todavía el resumen de elegibilidad temporal por fixture; por eso no se atribuye un recuento de LAE elegible a esa ejecución.

Se detectó además que el crosswalk solo aceptaba CET (+01:00), rechazando fechas de verano CEST (+02:00). El validador ahora acepta ambos identificadores únicamente cuando el offset ISO coincide exactamente con el declarado. Se añadieron regresiones de aceptación CEST y rechazo de offset inconsistente. El diagnóstico live ampliado expondrá por fixture los timestamps de captura/evidencia/kickoff, antigüedad de la evidencia, minutos hasta kickoff y razones de exclusión.

La elegibilidad continúa siendo fail-closed: fuente, identidad, vector, URL HTTPS, evidencia anterior y fresca (máximo 24 h) y captura anterior al kickoff. La recepción del XML no demuestra cuándo el proveedor publicó o refrescó originalmente el contenido; esa limitación permanece.


### Corrección de la primera regresión CEST

La primera ejecución de CI detectó que la validación del offset ya aceptaba +02:00, pero la validación previa de la fuente seguía exigiendo literalmente `CET` y la salida etiquetaba el fixture siempre como `CET`. Se corrigen ambos puntos: la fuente puede declarar `CET` o `CEST`, el offset debe coincidir y el valor devuelto conserva la zona declarada. La prueba de verano ahora verifica el flujo completo; la prueba negativa mantiene el rechazo de un offset +01:00 declarado como CEST.


## 2026-11-16 — score-ingestion hardening and fresh data validation

The CSV model loader had a validation gap: pandas can infer score columns containing `True`/`False` as boolean, and `float(True)`/ `float(False)` silently converts them to 1/0. `_optional_goal` now rejects Python and NumPy boolean values before numeric conversion. Regression cases cover both home-goal and away-goal columns. The CI lint scope now includes `kini_engine/dataio.py` and `tests/test_dataio.py`.

Validation evidence on the current PR branch:
- CI [run 43833711914](https://github.com/Baltas80/Kini-/actions/runs/43833711914): passed; Ruff passed and pytest reported **231 passed**, with 21 upstream NumPy/penaltyblog deprecation warnings.
- Historical-data validation [run 43833711884](https://github.com/Baltas80/Kini-/actions/runs/43833711884): passed. Its artifact records 5,311 completed fixtures from 14 Football-Data CSV sources, covering 2020-09-12 through 2026-11-09; 0 missing team names, 0 missing/incomplete final scores, 0 duplicate fixtures, 0 invalid result labels and 0 score/result mismatches.
- Canonical identity check in the same artifact: 56 unique team IDs, 10,622/10,622 team references resolved, 0 unresolved and 0 ambiguous.
- The artifact's source cache entries were approximately 23 hours old at retrieval. The observed dataset therefore ends on 2026-11-09; this is the actual source snapshot, not a claim that later fixtures are absent from the provider.

The historical backtest for the boolean-score hardening is queued as [run 43833712029](https://github.com/Baltas80/Kini-/actions/runs/43833712029). It has not yet completed, so no new predictive metrics are claimed for this commit. The last completed full walk-forward remains [run 43825259647](https://github.com/Baltas80/Kini-/actions/runs/43825259647), which accepted 5,011/5,011 predictions for DC, ML and all three ensemble variants with zero prediction errors.

### Remaining P1 ingestion follow-ups

- `scripts/build_history.py::_parse_source_csv` still relies on `pd.to_numeric`, which also accepts boolean values as numeric scores in some pandas dtypes. Apply the same explicit boolean rejection at the source-download/cache boundary and add a regression test.
- `kini_engine.dataio.build_dataset_profile` indexes its parsed-date list with DataFrame index labels rather than row positions. Non-RangeIndex frames can undercount duplicate fixtures; fix the positional association and add a regression test.

Next priority: close these two data-quality defects, then require the resulting historical-data validation and full backtest runs to pass before marking P1 complete.

## 2026-11-16 — P1 ingestion defects fixed and revalidated

Two follow-ups identified in the previous audit entry are now implemented.

- `scripts/build_history.py::_parse_source_csv` rejects Python and NumPy boolean values in `FTHG`/`FTAG` before `pd.to_numeric`. This prevents `True`/`False` from being accepted as 1/0 and prevents invalid source content from replacing the last known-good cache.
- `kini_engine.dataio.build_dataset_profile` now associates parsed dates with DataFrame rows by position, not index label. It also creates a correctly sized missing-date sequence when a frame has no `Date` column. Non-RangeIndex frames no longer undercount duplicate fixtures or index the parsed-date list incorrectly.
- Regression tests cover boolean scores in both home/away columns at the source-download/cache boundary, cache non-replacement, non-RangeIndex duplicate detection and missing-date frames.

### Validation on current PR head

- Implementation commit: [eb72fa6](https://github.com/Baltas80/Kini-/commit/eb72fa61435dc7d19fa0313efa0271d43025d18b).
- Test-fixture correction: [0f17916](https://github.com/Baltas80/Kini-/commit/0f17916dfa0cfa7fc0671f6f41e9f4ac200305a3). The first CI attempt exposed literal backslash-n delimiters in the new CSV fixture; the fixture was corrected and the fresh run below is the accepted result.
- CI [43841173353](https://github.com/Baltas80/Kini-/actions/runs/43841173353): success. Ruff passed, 18 files passed formatting, and **235 tests passed**. The 21 NumPy 2.5 / penaltyblog deprecation warnings remain upstream dependency warnings.
- Historical-data validation [43841173572](https://github.com/Baltas80/Kini-/actions/runs/43841173572): success. **5,311/5,311 completed fixtures**, 0 missing team names, 0 missing/incomplete final scores, 0 duplicates removed, 0 conflicting duplicates and 0 score/result mismatches. Canonical identity validation resolved **10,622/10,622** team references to 56 IDs, with 0 unresolved and 0 ambiguous; `integrity_passed=true`.
- Historical walk-forward [43840991448](https://github.com/Baltas80/Kini-/actions/runs/43840991448), running on implementation commit `eb72fa6`, was still executing its historical comparison at the time of this record. The current-head run [43841173346](https://github.com/Baltas80/Kini-/actions/runs/43841173346) was queued behind it. No new model metrics are claimed until one of those runs completes and its non-empty prediction and market acceptance gates pass.

### P1 status

The two specific ingestion defects above are **implemented and covered by passing tests**. The broader P1 audit is not closed: source publication provenance, exact market-capture timestamps, historical SELAE coupon completeness and any additional provider-specific integrity constraints remain open. The successful dataset profile establishes structural integrity for the observed Football-Data snapshot, not point-in-time publication completeness.

Next action: inspect the walk-forward artifact and acceptance gates, then continue the remaining source-provenance and official coupon ingestion work without changing the model-selection decision (the market remains the strongest benchmark).


## 2026-11-16 — completed walk-forward after P1 ingestion hardening

The historical walk-forward started on the implementation commit `eb72fa61435dc7d19fa0313efa0271d43025d18b` has now completed. Workflow [43840991448](https://github.com/Baltas80/Kini-/actions/runs/43840991448) finished successfully: the history build, first-ML diagnostic, historical comparison, non-empty prediction gate, cold-start diagnostics, schedule-screened market acceptance, fixed-book Bet365 benchmark acceptance, prequential-calibration acceptance and artifact upload all passed.

Artifact:
- `historical-backtest`, ID `14215051364`, 178,715 bytes.
- ZIP SHA-256: `b0a58e1d9ca13885b5689ffb57465653d45c8f2a4403d7d4fc7e23b5d7f143b7`.
- Dataset/test interval: 5,011 walk-forward fixtures, 2020-12-11 through 2026-11-09; initial training sample 300.
- All five configurations (`dc`, `ml`, `ensemble`, `ensemble_dc_ml`, `ensemble_dc_ml_adaptive`) generated 5,011/5,011 predictions. Recorded prediction errors: zero for every configuration.
- Cold-start fallback diagnostics reconcile to all 5,011 successful forecasts: Dixon–Coles and each DC-dependent ensemble used the explicit unseen-team fallback 73 times (1.4568%); ML used it zero times. Per-season diagnostics and examples were present and passed the workflow gate.

### Same-fixture comparison with the schedule-screened market

The model/market comparison uses the identical 4,424 fixtures for which the historical odds passed the conservative schedule screen. Metrics below are multiclass accuracy, Brier score, Log Loss, RPS and ECE respectively.

| Candidate | n | Accuracy | Brier | Log Loss | RPS | ECE |
|---|---:|---:|---:|---:|---:|---:|
| Dixon–Coles | 4,424 | 0.480561 | 0.616357 | 1.027499 | 0.207959 | 0.016274 |
| ML | 4,424 | 0.437839 | 0.647471 | 1.074246 | 0.220661 | 0.048768 |
| Baseline ensemble | 4,424 | 0.478074 | 0.613563 | 1.023018 | 0.206841 | 0.016342 |
| Fixed DC/ML ensemble | 4,424 | 0.474005 | 0.616095 | 1.026842 | 0.207953 | 0.012912 |
| Adaptive DC/ML ensemble | 4,424 | 0.474910 | 0.616305 | 1.027133 | 0.208019 | 0.012296 |
| Schedule-screened market | 4,424 | **0.507233** | **0.597504** | **0.999444** | **0.199876** | 0.024213 |

The market is better on accuracy, Brier, Log Loss and RPS. The baseline ensemble is the strongest of the uncalibrated model candidates by Brier/Log Loss, but remains materially behind the market. ECE alone does not reverse the conclusion.

### Prequential calibration

Calibration was fitted only from prior walk-forward out-of-sample forecasts; same-calendar-day outcomes were excluded. The common calibrated model/market sample contains 3,847 fixtures. On that sample:
- Market: raw Brier/Log Loss 0.597564/0.999533; calibrated 0.596714/0.998094.
- Dixon–Coles: raw 0.613791/1.023639; calibrated 0.613232/1.022458.
- ML: raw 0.638702/1.060984; calibrated 0.632937/1.051149.
- Baseline ensemble: raw 0.611315/1.019753; calibrated 0.611522/1.019966.
- Fixed DC/ML: raw 0.613518/1.023036; calibrated 0.613653/1.023129.
- Adaptive DC/ML: raw 0.613703/1.023289; calibrated 0.613727/1.023189.

Calibration improves some model scores modestly but does not close the market gap; it slightly worsens the baseline ensemble's Brier and Log Loss on this common calibrated sample. No candidate is promoted as market-beating.

### Market-data limitations

There are 5,011 fixtures with odds in the raw snapshot; 4,424 pass the schedule-compatibility screen and 587 remain ambiguous/excluded. Friday/Tuesday fixtures are excluded because the kickoff timezone is unspecified. Exact per-fixture odds-capture timestamps are unavailable. The benchmark therefore establishes a schedule-screened historical comparison, not proof that every quoted price was captured before the relevant kickoff. It does not establish executable profitability.

### Relationship to the current PR head

The walk-forward ran on `eb72fa6`. Comparing that commit with current PR head `05109b3a9c089f5f602c5819a5da95e6a3b4f1f6` shows exactly two later commits and only two changed files: `tests/test_build_history.py` (fixture delimiter correction) and this audit record. No predictive code, features, model configuration or backtest implementation changed after the completed walk-forward. Current-head CI [43841433607](https://github.com/Baltas80/Kini-/actions/runs/43841433607) passed; current-head historical-data validation [43841433631](https://github.com/Baltas80/Kini-/actions/runs/43841433631) passed. Current-head backtest workflow [43841433598](https://github.com/Baltas80/Kini-/actions/runs/43841433598) correctly skipped its expensive job because the two post-backtest commits changed only a test fixture and this document.

P0 is now **validated for the current predictive code**: every required model produced a non-empty, error-free walk-forward sample and the workflow acceptance gates passed. This closes the previous `n=0` blocker. It does not close P1 source provenance or P2 exact publication/capture-time proof. The PR remains a draft and unmerged; no direct change to `master`.


## 2026-11-16 — P1 SELAE provenance and redirect hardening

P0 is closed for the current predictive code as recorded above. The next P1 unit is source provenance for the SELAE coupon/calendar pipeline.

### Implemented, awaiting final CI evidence

**PR #7 — offline coupon importer**
- Branch: \`feat/selae-official-coupon-ingestion\`.
- Current head: \`fb0f01dbd152681a5b79abbd40a18082be0b96d9\`.
- Offline HTML now requires a \`.meta.json\` sidecar with the exact date-specific official HTTPS URL, UTC capture timestamp, raw-byte SHA-256 and encoding.
- Cache reuse now requires a valid sidecar and a SHA-256 match against the cached bytes; tampered/missing cache metadata causes a fresh fetch.
- HTTPS downgrade, non-official hosts, missing/naive/non-UTC timestamps, hash mismatch and invalid encoding fail closed.
- UTF-8 sidecars with or without BOM are supported. The Windows PowerShell example writes UTF-8 without BOM.
- Regression coverage was added for missing sidecars, hash mismatch, HTTP downgrade, tampered cache, non-UTC timestamps and BOM handling.
- The latest branch head has no successful workflow run exposed yet. Earlier CI runs predate this patch; do not mark this unit validated.

**PR #9 — historical calendar and archive URL boundaries**
- Branch: \`feat/selae-fixture-reconciliation\`.
- Current head at this record: \`275b3004a376082150d19725183a3d5a5d5f8eb6\`.
- The official historical XLS downloader rejects final redirects outside HTTPS on an exact SELAE host and standard port.
- Archive index/detail URLs now reject HTTP downgrade, deceptive subdomains, user-info and non-standard ports.
- Regression tests cover off-domain XLS redirects and unsafe archive URL variants.
- CI run [43850954338](https://github.com/Baltas80/Kini-/actions/runs/43850954338) passed workflow validation and Ruff lint, then failed only in Ruff formatting of the newly added calendar tests. The exact formatting corrections are committed at \`81f1b51\` and \`275b3004\`. No successful final-head CI run has been returned yet; this work remains implemented, not validated.

### Source access and remaining evidence

- GitHub-hosted runners previously received HTTP 403 for the SELAE escrutinio page, RSS, static result HTML, results index and official press-release PDF. The importer continues to treat this as a source-access limitation, not as successful validation.
- The official 2026-11-08 escrutinio page is currently retrievable through indexed web content, and its displayed 14 fixtures/signs and prize table are readable. That text view is not the original response bytes and cannot be used to fabricate the importer's raw HTML/SHA-256 provenance artifact.
- The latest archive-discovery run [43851171841](https://github.com/Baltas80/Kini-/actions/runs/43851171841) has not produced a completed discovery artifact. Earlier run [43849772941](https://github.com/Baltas80/Kini-/actions/runs/43849772941) skipped the discovery step because its inputs had not changed. No complete official historical archive inventory is claimed.
- The official historical workbook inspection workflow is manual-dispatch only; no workbook artifact was obtained in this cycle.

### Next action

1. Obtain successful deterministic CI for the final heads of PR #7 and PR #9; distinguish push-triggered runs from pull-request-triggered runs and do not infer success from queued/cancelled jobs.
2. Obtain the original official SELAE HTML/XLS bytes from an allowed environment and preserve exact capture metadata; do not substitute extracted web text.
3. Complete the official draw-date inventory and fixture crosswalk only where competition, canonical teams and actual kickoff are independently evidenced.
4. Keep all coupon targets and prize data out of pre-match features and model training until those joins are unambiguous.


## 2026-11-16 — P1 reconciliation record validation hardening

A further inspection of the public-draw and crosswalk validator found that public-draw evidence timestamps only had to be timezone-aware, not actually UTC. The draw loader also accepted unsafe official URLs with a non-standard port/user-info and accepted numeric floats where integer schema fields were required.

Implemented on PR #9:
- Central strict HTTPS URL validation: HTTPS only, non-empty host, standard port 443/default, no user-info.
- SELAE source and public-draw evidence URLs must use the exact official host.
- Crosswalk evidence URLs must pass the safe HTTPS check.
- \`sign_evidence_checked_at_utc\` must have UTC offset zero.
- \`schema_version\`, \`fixture_count\` and fixture \`position\` must be actual integers, not booleans/floats.
- Regression tests cover HTTP downgrade, port 8443, user-info, non-UTC public-draw timestamps, float positions and float fixture counts.

Commits:
- \`12d7517082d0016d47c9f954d78a19a9c479c8cb\` — implementation.
- \`280e59d674f0a95a2c0447953c1c9e8a2556d14c\` — regression tests.
- \`be9b5d1dea93d84fec73d10cf78d0bbbf23bb150\` — Ruff formatting.

Validation status: **implemented, not validated**. The most recent visible CI attempt remains [43850954338](https://github.com/Baltas80/Kini-/actions/runs/43850954338), which failed only on Ruff formatting in earlier calendar tests; those formatting corrections and this new patch are committed after that run. No final-head CI run or test artifact has been returned. Do not mark this unit tested or validated until a run on the final commit completes.


## 2026-11-16 — final validation checkpoint

### PR #7 importer provenance patch — validated

The final head of \`feat/selae-official-coupon-ingestion\` is \`fb0f01dbd152681a5b79abbd40a18082be0b96d9\`.
- CI [43850584199](https://github.com/Baltas80/Kini-/actions/runs/43850584199): **87 tests passed**, 4 upstream NumPy/penaltyblog deprecation warnings.
- Historical-data validation [43850584212](https://github.com/Baltas80/Kini-/actions/runs/43850584212): succeeded; historical dataset/profile built, validated and uploaded (artifact ID \`14217885532\`, 713,793 bytes).
- This validates the offline sidecar/cache integrity tests and the full existing test suite. It does not prove that GitHub runners can fetch SELAE live pages; that remains a separate 403 source-access limitation.

### PR #9 reconciliation/calendar patch — awaiting final-head CI

The latest implementation commit is \`1a517110c47654f2498fb1b115bc655af8bb6239\`. It includes:
- Strict SELAE source URL validation (HTTPS, exact host, default/443 port, no user-info).
- UTC-only public-draw evidence-check timestamps.
- Strict integer validation for schema version, coupon fixture count and fixture positions.
- Safe HTTPS checks for crosswalk evidence URLs.
- Redirect trust checks for the official historical calendar XLS and archive discovery URLs.

The previous PR #9 CI/data-validation attempt [43852090136](https://github.com/Baltas80/Kini-/actions/runs/43852090136) / [43852090288](https://github.com/Baltas80/Kini-/actions/runs/43852090288) was cancelled by subsequent source-formatting commits before lint/pytest or dataset validation ran. The historical-backtest changes job correctly skipped the model backtest because these changes do not touch predictive code; archive discovery also skipped because its own inputs did not change. Do not count either cancelled job as validation.

A documentation-only commit follows this checkpoint so CI can run against the settled source/test head; no further source changes are planned in this cycle.

### Official coupon evidence cross-check

The current official SELAE result page for 8 November 2026 confirms the 14 coupon positions, scores and signs, including position 14 as displayed score 1–0/sign 1. Official Liga F match-detail pages independently confirm the three played women's fixtures and their kickoffs/results:
- Position 11 Athletic Club–Real Madrid CF, 7 Nov 16:00, 1–1.
- Position 12 Logroño United–Sevilla FC, 8 Nov 12:00, 2–2.
- Position 13 SD Eibar–Real Sociedad, 7 Nov 17:00, 1–2.

SELAE's official postponement PDF states that Tenerife–Alavés was scheduled for 8 Nov 13:00, postponed, and would be decided by public draw from 22:00 if it could not be played within 24 hours. This supports keeping position 14 out of football training labels. The separate Liga F evidence manifest continues to declare \`training_eligibility.eligible=false\` because no validated multi-season Liga F training dataset exists.

These official pages are content-level cross-checks only. Their extracted web text is not the original HTML response and has not been substituted for a raw-byte import or SHA-256 provenance artifact.


## 2026-11-16 — P1 reconciliation CI and data reproducibility passed

Final source/test head before this documentation update: \`abaea2a35d018b4685852d7962abf8699aee6552\`.

- CI [43852804478](https://github.com/Baltas80/Kini-/actions/runs/43852804478): **244 passed**, 21 upstream deprecation warnings. Workflow validation, Ruff lint and Ruff format all passed.
- Historical-data validation [43852804294](https://github.com/Baltas80/Kini-/actions/runs/43852804294): successful build, canonical team identity validation, dataset/profile validation and artifact upload.
- Historical-data artifact ID: \`14219255876\`; ZIP digest: \`sha256:3b3ff9bf56f2816baf7e4078901192ca52a5854176c54f5d3e1a26a4c6664c53\`.
- The generated \`historical_spain.csv\` SHA-256 is \`a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab\`. It is byte-identical to the CSV from PR #7 data-validation artifact \`14217885532\` and the preceding PR #9 validation artifact \`14219400394\`.
- Profile: 5,311/5,311 complete rows, date coverage 2020-09-12 through 2026-11-09, 0 missing team names, 0 missing final scores, 0 incomplete scores, 0 duplicate fixtures, 0 conflicting duplicates, 0 invalid result labels, 0 score/result mismatches; \`integrity_passed=true\`.
- The historical-backtest workflow [43852804242](https://github.com/Baltas80/Kini-/actions/runs/43852804242) correctly skipped the model backtest because this P1 change does not modify predictive code.
- Archive discovery [43852804421](https://github.com/Baltas80/Kini-/actions/runs/43852804421) skipped its discovery step because archive-discovery inputs did not change; no new archive inventory is claimed.

The preceding CI attempt [43852613210](https://github.com/Baltas80/Kini-/actions/runs/43852613210) reached pytest and reported 238 passed / 6 failed. All six failures shared one test-fixture defect: the new JSONL regression tests wrote a literal backslash-n instead of a line-feed, so the loader correctly rejected the malformed JSONL before reaching the intended assertions. The test fixture was corrected in commit \`abaea2a\`; the final CI above confirms the corrected suite passes.

P1 URL/provenance hardening in PR #9 is now **implemented and validated by CI**. Live SELAE source access, complete official archive inventory and original raw HTML/XLS capture remain separate open evidence items.


## 2026-11-16 — Press-release source URL validation hardening

A focused provenance-boundary review found that `scripts/import_selae_press_release.py::validate_official_source_url` accepted official-host URLs using non-standard ports and URLs containing user-info. This was inconsistent with the stricter SELAE URL validators used by archive discovery and fixture reconciliation.

Implemented on PR #9:
- Require HTTPS and an exact SELAE hostname.
- Accept only the default HTTPS port or explicit port 443.
- Reject URL user-info (username/password).
- Convert malformed-port parsing errors into a clear validation error.
- Continue requiring a PDF path.
- Regression cases cover HTTP downgrade, port 8443, username-only and username/password user-info, deceptive subdomains, malformed ports, and the explicit standard port 443.

Commits:
- `5bcb30207864f32640a3d1bf2a298f1150d4aaa7` — strict source URL validation.
- `8e9642267bcf734b72891c558bbc37a82c4603ef` — preserve the established error-message contract.
- `7004aac8372b20087b16147eba2fd1e2c64ec64a` — URL-boundary regression tests.

Validation on final source/test head `7004aac8372b20087b16147eba2fd1e2c64ec64a`:
- PR CI [43855861933](https://github.com/Baltas80/Kini-/actions/runs/43855861933) passed workflow validation, Ruff lint, Ruff formatting and **244 pytest tests**. The 21 warnings are upstream NumPy 2.5 / penaltyblog deprecations.
- Historical-data validation [43855861928](https://github.com/Baltas80/Kini-/actions/runs/43855861928) passed dataset construction, canonical-team validation, profile assertions and artifact upload. Artifact `kini-historical-data`, ID `14221182942`, size 714,126 bytes, digest `sha256:5a38fea0311d282b644b846297455cf04e9f0b649d1fc2b74977a35cefaca86d`.
- Historical-backtest [43855861910](https://github.com/Baltas80/Kini-/actions/runs/43855861910) correctly skipped its model job because the changes are limited to SELAE import validation and tests; no fresh predictive benchmark is claimed.
- Archive discovery [43855862019](https://github.com/Baltas80/Kini-/actions/runs/43855862019) passed its scope check but skipped the network discovery step because neither the discovery script nor its workflow changed. No new archive inventory is claimed.

The change closes this specific unsafe-URL acceptance gap. It does not solve the separate GitHub-runner HTTP 403 issue for some SELAE endpoints and does not create original raw-byte provenance for pages whose original response bytes have not been captured. Extracted search/web text remains content-level corroboration only, not a substitute for source bytes or their SHA-256.


## 2026-11-16 — Official SELAE archive index reconnaissance

A current read-only inspection of the official [SELAE Quiniela results index](https://www.loteriasyapuestas.es/es/la-quiniela/resultados) on 2026-11-16 surfaced pagination links numbered 1–80. The first index page lists 20 result-detail links, from 2026-11-15 back to 2026-08-23. Following the official page-2 component link returned 20 more links, from 2026-08-16 back to 2026-04-22.

This is a useful scope signal for the archive collector: the current index exposes 80 pages, so a two-page CI smoke run is not a complete archive inventory. The web/browser text extraction is content-level corroboration only. It does not expose the original response bytes, response headers or a source-byte SHA-256 and must not be converted into a raw-capture provenance record.

The automated GitHub archive-discovery job remains scoped to code changes and its latest documentation-head run skipped network discovery. The next complete archive attempt should fetch all discovered pages from an allowed network environment, preserve each page's original bytes and metadata, and only then report deduplicated result URLs/date coverage. No historical draw outcomes or raw-byte hashes are inferred from this reconnaissance.


### SELAE archive transport probe — artifact inspection

The earlier archive-discovery failure artifact was downloaded and inspected rather than treated as a generic workflow failure.

- Workflow: [43851162609](https://github.com/Baltas80/Kini-/actions/runs/43851162609), commit `948aa503ca82561640932cd0e7bbe41b825aa975`.
- Artifact: [selae-result-archive-discovery](https://github.com/Baltas80/Kini-/actions/runs/43851162609/artifacts/14218270980), ID `14218270980`, 1,216 bytes.
- ZIP SHA-256 independently recomputed from the downloaded artifact: `e7d9af5b28aeaae9c7e3d7d6638b637c231ca544b67657d6c88fb192f3a90e0d`.
- The report confirms both Spanish and English result-index requests returned HTTP 403. All five transport probes also returned HTTP 403: results RSS (435 bytes), static result HTML (434), 8-Nov press-release PDF (528), Spanish page-2 component (434) and English page-2 component (434). Each response remained on the official host, but `accessible=false`.
- The recorded SHA-256 values are hashes of those short HTTP-403 response bodies, **not** hashes of official result pages, PDFs or RSS data. They must not be reused as draw-source provenance.

This narrows the blocker to the GitHub-runner HTTP client/network path rather than a missing pagination implementation. The current web-index observation demonstrates that an indexed/text-rendered view exists, but it does not expose the original bytes. The local container's direct downloads of the official result page and PDF also failed, so no original source bytes were captured in this execution. Keep the importer fail-closed; do not fabricate raw-source hashes or promote extracted text to a provenance artifact.


## 2026-11-16 — Current execution checkpoint and forecast-ledger implementation

### Validation and P0 reconciliation

- Current PR #9 head before this implementation: `e46ad863a057611e0264427f5703e478559f5755`.
- CI [43900321979](https://github.com/Baltas80/Kini-/actions/runs/43900321979) passed workflow validation, Ruff lint, Ruff formatting and **245 tests**. The 21 warnings remain upstream NumPy 2.5 / penaltyblog deprecations.
- The archive-discovery attempt [43900321930](https://github.com/Baltas80/Kini-/actions/runs/43900321930) reached both official SELAE result-index routes; both returned HTTP 403. Diagnostic artifact ID `14240363732` was uploaded. No official raw page bytes, archive inventory or source-byte hash are claimed.
- A scheduled run on current `master`, [43869289099](https://github.com/Baltas80/Kini-/actions/runs/43869289099), completed with workflow conclusion `success` but is **not a valid model backtest**: `n_total=4752`, market `n=4752`, while Dixon–Coles, ML and ensemble each reported `n=0`. The old workflow on `master` lacks the non-empty-model acceptance gate. This result must not be treated as predictive validation or used for model selection.
- The current PR branch contains the corrected predictive implementation and non-empty acceptance gates. Its latest full model run before this checkpoint was [43840991448](https://github.com/Baltas80/Kini-/actions/runs/43840991448), on `eb72fa61435dc7d19fa0313efa0271d43025d18b`: all five forecast streams generated 5,011/5,011 predictions with zero prediction errors and all model/market/calibration acceptance steps passed. A commit comparison from `eb72fa6` to `e46ad86` found no changes to `core.py`, `backtest.py`, `dataio.py`, `sources.py` or `build_history.py`; the benchmark remains applicable to the predictive code in the current branch.
- Historical-data validation [43858724502](https://github.com/Baltas80/Kini-/actions/runs/43858724502) passed on the preceding source/test head. The subsequent `e46ad86` commit changed only archive-discovery formatting.

### Forecast ledger — implementation in progress

The walk-forward comparator previously retained individual rows internally for metrics but did not expose a durable per-fixture forecast record. The next implementation adds:
- Stable SHA-256 fixture IDs based on source-scoped competition, season, date and team identity.
- Per-fixture OOS probabilities for DC, ML and all ensemble candidates, actual result, forecast-as-of date, model-fit and training cutoffs, training sample sizes and cold-start fallback state.
- Market, Bet365 and LAE vectors only when their existing temporal-eligibility gates pass.
- A run manifest containing code revision, dataset and profile hashes, execution ID, Python version and full model/backtest configuration.
- One JSONL file per run, created exclusively (existing files are never overwritten), with workflow artifact retention extended to 90 days.

Validation of this implementation is pending. The first full walk-forward on the implementation head must pass the existing non-empty model gates and the new ledger integrity gate before the ledger is considered validated. The 90-day Actions artifact is an immutable per-run record, not yet an indefinite archive; long-term retention remains a separate storage decision.

### Next action

Complete CI and the full walk-forward for the forecast-ledger implementation, inspect the artifact and verify fixture uniqueness, probability validity, prior-date cutoffs and manifest hashes. Then begin the comparative error-analysis module using the archived fixture-level rows. No direct changes to `master` and no PR merges.


### Forecast-ledger lint correction

The first CI run for the ledger implementation [43902333075](https://github.com/Baltas80/Kini-/actions/runs/43902333075) reached Ruff and identified three invalid-type checks using `ValueError` plus a redundant UTC suffix replacement. These were corrected to use `TypeError` for wrong input types and Python's native ISO-8601 parser for the timezone-aware timestamp. The full backtest run [43902333077](https://github.com/Baltas80/Kini-/actions/runs/43902333077) is independently exercising the ledger implementation; its final result is still pending.


### Forecast-ledger formatting follow-up

The first corrected CI run [43902672952](https://github.com/Baltas80/Kini-/actions/runs/43902672952) passed Ruff lint but failed the repository's non-mutating Ruff format check on five newly touched files. The formatter's exact layout changes have been applied; pytest had not yet run in that attempt. CI is being rerun on the formatted commit.


## 2026-11-16 — Per-fixture forecast ledger and comparative error diagnostics

### Ledger execution and integrity

- Historical backtest run [43906085406](https://github.com/Baltas80/Kini-/actions/runs/43906085406) completed successfully on code revision `3d401dc6ff83165641e1e53e55bbc47901bdcdd5`. All five model streams generated **5,021/5,021 forecasts** with zero recorded prediction errors; initial training sample 300; forecast period 2020-12-11 through 2026-11-15.
- The workflow passed `BACKTEST_ACCEPTANCE_OK`, `FORECAST_LEDGER_ACCEPTANCE_OK`, `COLD_START_DIAGNOSTICS_OK`, schedule-screened market acceptance and fixed-book Bet365 common-sample acceptance.
- Artifact [14247557275](https://github.com/Baltas80/Kini-/actions/runs/43906085406/artifacts/14247557275), ZIP size 1,529,552 bytes, digest `sha256:e81ea31be719b5f7eefbe3f3f3f6dfb12857de6c2c8632d5a29ce6598943777e`. It contains `backtest-results.json` and `prediction-ledger.jsonl`.
- Ledger: 5,021 forecast rows plus one manifest; 7,211,592 bytes; SHA-256 `5c8e5a943a06cd5a599e47a048d4105de57c05404a5190e5c7f206ba3688827f`. Independent artifact inspection found 5,021 unique fixture IDs, zero duplicates, zero invalid 1/X/2 labels, zero invalid model probability vectors, zero sign/probability mismatches, and no training or model-fit cutoff on or after the forecast date.
- Manifest dataset: 5,321 rows; dataset SHA-256 `e4b195593118215684ffefc8e70ffe0c8d88b3e28318d9c796f7b3b71c496475`; profile SHA-256 `d7d7fbb5014ad32eb3af620f86aede28381c8e879c351af78a9bc3cfb2207a6b`.
- Market temporal screen: 4,432/5,020 rows with odds eligible; 588 schedule-ambiguous rows excluded. Bet365 benchmark: 4,425/5,013 eligible source rows. Historical LAE eligibility remains zero because no verified historical LAE capture timestamps are present.
- Cold-start fallback: 73/5,021 DC-dependent forecasts (1.45%); ML-only forecasts 0; all DC-dependent ensemble streams report the same 73 cases. The 14 league-season totals reconcile to the aggregate counts.

### Model comparison

Full OOS samples are shown below. Market has fewer fixtures because its existing schedule-time eligibility gate is deliberately conservative.

| Candidate | n | Accuracy | Brier | Log Loss | Mean P(X) | Actual X |
|---|---:|---:|---:|---:|---:|---:|
| Dixon–Coles | 5,021 | 48.18% | 0.616681 | 1.027801 | 27.33% | 27.84% |
| ML | 5,021 | 44.15% | 0.645508 | 1.071342 | 28.82% | 27.84% |
| Baseline ensemble | 5,021 | 47.94% | 0.613642 | 1.023023 | 27.68% | 27.84% |
| Fixed DC/ML | 5,021 | 47.58% | 0.615877 | 1.026395 | 27.67% | 27.84% |
| Adaptive DC/ML | 5,021 | 47.72% | 0.616087 | 1.026701 | 27.56% | 27.84% |
| Schedule-screened market | 4,432 | 50.72% | 0.597534 | 0.999473 | 27.71% | 27.91% |

On the identical 4,432 market-eligible fixtures, the market remains better than every model:

| Candidate | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|
| Dixon–Coles | 48.06% | 0.616397 | 1.027514 |
| ML | 43.80% | 0.647451 | 1.074171 |
| Baseline ensemble | 47.81% | 0.613594 | 1.023024 |
| Fixed DC/ML | 47.41% | 0.616126 | 1.026844 |
| Adaptive DC/ML | 47.50% | 0.616334 | 1.027133 |
| Market | **50.72%** | **0.597534** | **0.999473** |

No model is promoted as market-beating. These are historical schedule-screened comparisons, not proof that odds were captured or executable at the exact forecast time, and not evidence of future profitability.

### Draw error analysis

- Actual draws: 1,398/5,021 (27.84%).
- Mean ensemble P(X): 27.68%, only 0.17 percentage points below observed prevalence. Dixon–Coles is 0.51 pp below; ML is 0.98 pp above. There is no evidence supporting a global upward adjustment to draw probabilities.
- However, X is rarely the single most-probable sign. Top-sign X recall: Dixon–Coles 55/1,398 (3.93%); ML 192/1,398 (13.73%); baseline ensemble 33/1,398 (2.36%); fixed DC/ML 41/1,398 (2.93%); adaptive DC/ML 45/1,398 (3.22%). ML selects X more often but is substantially worse on overall Brier and Log Loss.
- On the common market sample (n=4,432; 1,237 actual draws), X appeared in the model's two highest-probability signs for 867/1,237 draws under DC (70.09%), 862/1,237 under ML (69.69%), 861/1,237 under the baseline ensemble (69.60%), 855/1,237 under the fixed blend (69.12%), and 849/1,237 under the adaptive blend (68.63%). The market's top-two set covered 940/1,237 draws (75.99%).
- Overall top-two empirical coverage on that common sample was 76.53% for the baseline ensemble and 78.27% for the market. This is a descriptive top-two candidate proxy, **not** a completed ticket-optimizer or payout backtest.
- Interpretation: the low frequency of X as the top single sign does not imply that P(X) is globally too low. The more relevant weakness is match-level ranking: the model often places X third even when the aggregate draw probability is close to the observed rate. Do not add a blanket draw bias; investigate ranking and allocate doubles through the optimizer using the complete probability vectors.

### Comparative diagnostics implementation

- Added `read_prediction_ledger()` to verify JSONL structure, manifest, SHA-256, row count, unique fixture IDs, probability vectors, model signs, source eligibility and prior-date cutoffs.
- Added `kini_engine/diagnostics.py` and `scripts/analyze_prediction_ledger.py`. The report includes per-model confusion matrices, classwise precision/recall/F1, probability bias, binary Brier/Log Loss, reliability bins, top-two candidate coverage, model disagreement, competition/season segments and market comparisons on the exact eligible fixture sample.
- Updated `.github/workflows/historical-backtest.yml` to run the diagnostic after backtest acceptance and include `prediction-diagnostics.json` in the 90-day artifact. Updated CI lint/format coverage for the new module, script and tests.
- CI [43917802099](https://github.com/Baltas80/Kini-/actions/runs/43917802099) passed workflow validation, Ruff lint, Ruff formatting and **254 tests passed**. There were 21 upstream NumPy 2.5 / penaltyblog deprecation warnings.
- The full end-to-end run for the new diagnostics step is queued behind an earlier historical comparison. The ledger itself is already validated by run 43906085406; the generated diagnostics artifact is not yet independently verified.

### Open limitations and next action

1. Complete the point-in-time audit of every model feature and its source observation/publication timing. Strict prior-calendar-day filtering is implemented, but exact historical result-publication timestamps are unavailable.
2. Keep odds as schedule-screened benchmark data until exact capture timestamps and timezone provenance are available.
3. SELAE historical archive requests from GitHub Actions continue returning HTTP 403; no original raw archive bytes or source-byte hashes are claimed.
4. Use the validated fixture ledger to finish the error-analysis review, then evaluate actual direct-ticket double/triple allocation on identical OOS fixtures. Keep ticket coverage distinct from model probability quality and economic return.

No changes to `master`; PR #9 remains open, draft and unmerged.


---

## 2026-11-16 — Comparativa de mercado por competición y temporada

### Diagnóstico de predicciones validado

El backtest [43918579838](https://github.com/Baltas80/Kini-/actions/runs/43918579838), sobre el HEAD 217d5d7030176694e25d6a15badffa17f87a2c63, completó las cinco configuraciones con 5.021/5.021 predicciones y cero errores. El artefacto 14256405850 contiene backtest-results.json, prediction-ledger.jsonl y prediction-diagnostics.json; digest ZIP sha256:675efd805f45737c450f9af30cfa40a1bdca912a39835d0db30e115e1db5ae98. El ledger tiene 5.021 filas y SHA-256 532c198247e6d3cf1f2c4aacfe96d40a4969abc335777fd24badd3f3724a13d7.

En la muestra completa OOS (5.021 partidos), Brier / Log Loss:
- Dixon–Coles: 0.616681 / 1.027801.
- ML: 0.645508 / 1.071342.
- Ensemble principal: 0.613642 / 1.023023.
- Ensemble DC/ML fijo: 0.615877 / 1.026395.
- Ensemble DC/ML adaptativo: 0.616087 / 1.026701.

En los mismos 4.432 partidos con mercado temporalmente elegible:
- Mercado: accuracy 0.507220, Brier 0.597534, Log Loss 0.999473.
- Mejor modelo, ensemble principal: accuracy 0.478114, Brier 0.613594, Log Loss 1.023024.
- El mercado supera a todos los modelos en los tres indicadores. Las cuotas continúan siendo un benchmark schedule-screened, no un precio por partido con captura y zona horaria demostradas.

Diagnóstico de empates:
- Empates reales: 1.398/5.021 (27,84%).
- P(X) media del ensemble: 27,68% (sesgo agregado −0,17 puntos porcentuales).
- X fue el signo individual más probable del ensemble en 130/1.398 empates (recall 2,36%; precisión 25,38%).
- En la muestra común con mercado (4.432 partidos; 1.237 empates), X apareció entre los dos signos principales en 861/1.237 empates del ensemble (69,60%) y en 940/1.237 del mercado (75,99%). Cobertura empírica total de los dos signos principales: 76,53% ensemble y 78,27% mercado.
- No se justifica un sesgo global hacia X. El problema descriptivo es el ranking por partido y la cobertura potencial de dobles; no se ha demostrado todavía una mejora del optimizador ni de premios.

### Comparación segmentada implementada

Commits:
- 8186eea2dd2a937b99c4abbab9179dc6b3cb3f46: incorpora comparación modelo/mercado por segmento.
- a9fef2c9bf16988a13d12164611707b8a9c9141c: añade pruebas de muestra común y umbral mínimo.

Cada segmento competición/temporada incluye ahora:
- Métricas de los modelos en todos sus partidos OOS.
- Comparación del mercado y todos los modelos en exactamente las mismas filas con market_eligible=true.
- Diferencias de accuracy, Brier y Log Loss frente al mercado y desacuerdos de signo.
- Estado explícito below_minimum si la muestra común del segmento no alcanza el umbral configurado (100 por defecto); en ese caso se conserva el recuento, pero no se publican métricas segmentadas inestables.

CI [43928094921](https://github.com/Baltas80/Kini-/actions/runs/43928094921): actionlint en 7 workflows, Ruff lint/format correctos y 255 tests pasados. Persisten 21 advertencias upstream de penaltyblog/NumPy 2.5.

El backtest del nuevo diagnóstico [43928097207](https://github.com/Baltas80/Kini-/actions/runs/43928097207) estaba en ejecución al actualizar este registro. No se atribuyen todavía resultados de segmentación al nuevo código; deben confirmarse en el artefacto generado por esa ejecución.

### Próxima acción

1. Inspeccionar el artefacto de 43928097207 y verificar que cada comparación segmentada usa el mismo n elegible para mercado y modelos.
2. Identificar segmentos con diferencias descriptivas relevantes, sin seleccionar modelos por muestras pequeñas ni confundir diferencias con significancia estadística.
3. Continuar la evaluación del optimizador con escenarios conjuntos reales de cupones históricos. Los bloques arbitrarios de 14 partidos no deben presentarse como cupones SELAE.
4. Mantener abiertas las limitaciones de publicación exacta de resultados y captura de cuotas. No declarar P2 completamente demostrado.

No se ha modificado master ni se ha fusionado ninguna PR. La PR #9 permanece abierta y en borrador.


### Cálculo independiente por segmento sobre el ledger validado 43918579838

Antes de disponer del nuevo artefacto segmentado, se calculó de forma independiente la comparación en las mismas filas con mercado elegible. Δ Brier se define como Brier(ensemble) − Brier(mercado); valores positivos favorecen al mercado.

| Competición | Temporada | n común | Brier mercado | Brier ensemble | Δ Brier |
|---|---:|---:|---:|---:|---:|
| LaLiga | 2020/21 | 230 | 0.55716 | 0.59594 | +0.03878 |
| LaLiga | 2021/22 | 336 | 0.58091 | 0.60189 | +0.02098 |
| LaLiga | 2022/23 | 329 | 0.58032 | 0.59140 | +0.01108 |
| LaLiga | 2023/24 | 332 | 0.56425 | 0.57164 | +0.00739 |
| LaLiga | 2024/25 | 335 | 0.56716 | 0.58519 | +0.01803 |
| LaLiga | 2025/26 | 331 | 0.56570 | 0.57115 | +0.00545 |
| LaLiga | 2026/27 parcial | 104 | 0.51253 | 0.54295 | +0.03042 |
| Segunda | 2020/21 | 240 | 0.62182 | 0.65074 | +0.02892 |
| Segunda | 2021/22 | 405 | 0.62964 | 0.64265 | +0.01301 |
| Segunda | 2022/23 | 413 | 0.62868 | 0.63903 | +0.01035 |
| Segunda | 2023/24 | 414 | 0.62983 | 0.64454 | +0.01471 |
| Segunda | 2024/25 | 412 | 0.61028 | 0.62097 | +0.01069 |
| Segunda | 2025/26 | 413 | 0.62016 | 0.64204 | +0.02188 |
| Segunda | 2026/27 parcial | 138 | 0.60822 | 0.62338 | +0.01516 |

El mercado obtiene mejor Brier en los 14/14 segmentos. La diferencia más pequeña es LaLiga 2025/26 (+0.00545) y la mayor LaLiga 2020/21 (+0.03878). Es evidencia descriptiva, no prueba de significancia: no se han calculado intervalos de confianza ni corregido comparaciones múltiples. Las temporadas 2026/27 son parciales y sus muestras son menores. La elegibilidad temporal del mercado sigue siendo el filtro de calendario documentado, no una captura exacta por fixture.


### 2026-11-16 — Incertidumbre pareada de la ventaja del mercado

El artefacto del run 43928779926 ha sido descargado e inspeccionado independientemente. El SHA-256 del ZIP coincide con el digest publicado por GitHub Actions: b657b474d34a99e195cd1a3ceceb63de1e6e245412152ba20b3b891b11f50c99. Contiene 5.021 predicciones individuales, resultados agregados y el diagnóstico segmentado. El manifiesto identifica el código c4995d462257abaa2ef63de9529558299258cfeb, el histórico SHA-256 e4b195593118215684ffefc8e70ffe0c8d88b3e28318d9c796f7b3b71c496475 y 5.021 filas.

La comparación segmentada se confirmó en el artefacto: 14 segmentos competición-temporada, cada uno con 100 o más partidos comunes con el mercado. Los 14 deltas puntuales de Brier favorecen al mercado. Esto no significa que los 14 segmentos sean individualmente concluyentes: varias muestras no son suficientemente precisas para excluir cero.

Se añade a kini_engine/diagnostics.py un intervalo de incertidumbre pareado para las diferencias modelo menos mercado en Brier, Log Loss y accuracy. La unidad de remuestreo es la semana ISO; cada réplica extrae semanas con reemplazo y conserva juntos todos los partidos elegibles de cada semana. La semilla deriva del run, segmento y modelo para hacer reproducible el resultado. Se publican intervalos percentiles del 95%, no p-valores. Los intervalos por segmento son exploratorios y no están ajustados por comparaciones múltiples. No se calcula intervalo si hay menos de ocho semanas distintas.

La CLI acepta --bootstrap-samples (mínimo 100; predeterminado 10.000). Las métricas puntuales no cambian. La convención de signo es modelo menos mercado: delta Brier/Log Loss positivo favorece al mercado; delta accuracy negativo favorece al mercado.

Este análisis no resuelve la limitación temporal de las cuotas: el benchmark sigue siendo schedule-screened y no dispone de timestamp de captura por fixture. Tampoco demuestra rentabilidad futura.


### 2026-11-16 — intervalos pareados y evaluación real de cupones

#### Incertidumbre de la comparación con mercado

La implementación de bootstrap semanal se ha validado en CI. Se calculó de forma independiente sobre el ledger de run 43928779926, con 4.432 fixtures comunes mercado/modelos y 248 semanas ISO. Se usaron 10.000 réplicas por comparación. Las diferencias son modelo menos mercado; Brier y Log Loss positivos, o accuracy negativo, favorecen al mercado.

| Modelo | Δ Brier (IC 95%) | Δ Log Loss (IC 95%) | Δ accuracy (IC 95%) |
|---|---:|---:|---:|
| Dixon-Coles | +0.01886 [0.01469, 0.02320] | +0.02804 [0.02176, 0.03463] | -0.02662 [-0.03745, -0.01631] |
| ML | +0.04992 [0.04195, 0.05786] | +0.07470 [0.06268, 0.08676] | -0.06927 [-0.08426, -0.05437] |
| Ensemble | +0.01606 [0.01232, 0.01983] | +0.02355 [0.01802, 0.02914] | -0.02911 [-0.03956, -0.01893] |
| DC/ML fijo | +0.01859 [0.01455, 0.02279] | +0.02737 [0.02140, 0.03351] | -0.03317 [-0.04373, -0.02250] |
| DC/ML adaptativo | +0.01880 [0.01471, 0.02298] | +0.02766 [0.02161, 0.03393] | -0.03227 [-0.04272, -0.02186] |

Los cinco intervalos globales excluyen cero y apuntan en la misma dirección. El resultado respalda que el benchmark de mercado es superior en esta muestra común; no justifica retocar pesos para ocultar la diferencia. Son intervalos percentiles exploratorios por clúster semanal, sin ajuste por las cinco comparaciones ni por selección posterior.

Por competición/temporada, los 14 deltas puntuales de Brier favorecen al mercado, pero solo 8/14 intervalos de Brier y 8/14 de Log Loss excluyen cero. No se debe describir como 14/14 segmentos estadísticamente concluyentes. Las dos temporadas 2026/27 son parciales. El mercado sigue siendo schedule-screened, no timestamp-verified.

#### Descubrimiento de archivo de cupones

Se identificó HistóricoQuiniela como fuente secundaria que publica partidos, fechas, marcadores, signos y Pleno al 15. Su página de la temporada 2020/21 registra 63 jornadas. El propio sitio declara que no está afiliado a SELAE y que su contenido es informativo. QuinielaFutbol.info también ofrece un PDF de combinaciones históricas y advierte que la oficialidad corresponde exclusivamente a LAE. Ninguna de estas fuentes se tratará como fuente oficial ni se incorporará directamente al entrenamiento.

Piloto manual: la Jornada 21 de 2020/21, celebrada el 13-12-2020, muestra 15 partidos entre el 12 y el 14 de diciembre. Los 15 emparejamientos y marcadores se contrastaron con el histórico Football-Data del repositorio; coincidieron tras aplicar alias de equipo documentados. Esto prueba que existe una ruta potencial de reconciliación para un cupón, no que el archivo completo esté validado.

Fuentes candidatas:
- https://www.historicoquiniela.com/historico/2020-2021
- https://www.historicoquiniela.com/historico/2020-2021/21
- https://www.quinielafutbol.info/historico/resultados-la-quiniela-2020-2021.html
- https://www.quinielafutbol.info/historico/resultados-la-quiniela-2020-2021.pdf

#### Riesgo de leakage específico del optimizador

El ledger actual es de pronósticos por partido, con corte individual por fecha del encuentro. Eso es válido para el backtest de cada partido, pero no basta para evaluar un boleto: los 14 signos se deben fijar antes del primer kickoff. En la Jornada 21 citada, los partidos van del 12 al 14 de diciembre; reutilizar el pronóstico individual del partido del día 14 puede incorporar resultados de partidos del mismo cupón disputados el 12 o 13. Sería leakage a nivel de cupón.

Por tanto, queda prohibido evaluar dobles/triples de un cupón con el ledger actual sin una reconstrucción de pronósticos a un corte común. La próxima unidad P6 será un backtest de cupones walk-forward que:
1. Determine el kickoff más temprano de cada cupón y fije un único cutoff anterior.
2. Entrene DC/ML exclusivamente con resultados disponibles antes de ese cutoff.
3. Genere los 14 pronósticos y el Pleno con la misma instantánea de modelo.
4. Exija reconciliación fixture por fixture con fecha, orden, equipos y resultado.
5. Registre fuente y nivel de verificación de cada jornada.
6. Evalúe cobertura real de columnas, coste y Pleno por separado.
7. Excluya jornadas con partidos sorteados, aplazados no resueltos o fixtures no reconciliados.

No se declara todavía validado el optimizador con cupones históricos. El algoritmo de múltiples directos y sus pruebas sintéticas siguen validados; falta la evaluación temporal real a nivel de jornada.

#### Validación de código

Commit de implementación: 742d3e6. Correcciones de formato: 05aa489, eec3bd0 y abb3799. CI final [43938355598](https://github.com/Baltas80/Kini-/actions/runs/43938355598): actionlint correcto, Ruff lint/format correctos, 257 tests pasados y 21 warnings upstream de penaltyblog/NumPy 2.5.

El backtest completo de la nueva versión está pendiente de terminar. No se declara validado el artefacto con intervalos hasta inspeccionar el resultado de la ejecución correspondiente al head actual.


### 2026-11-16 — backtest finalizado y piloto de cupones implementado

#### Validación del backtest individual

El run [43938706602](https://github.com/Baltas80/Kini-/actions/runs/43938706602) terminó con éxito en el job backtest. Pasaron las puertas de aceptación de modelos no vacíos, registro por fixture, cold-start, mercado schedule-screened, benchmark Bet365 y calibración prequential; también se generó el diagnóstico de errores.

El artefacto historical-backtest (ID 14263259457) se descargó y su SHA-256 local coincide con el digest publicado por GitHub: ed905f32fedae42dad20e19077ad0fb70ff5cb0d526bf8c8af1d164d31f9ff38.

- 5.021 forecasts OOS individuales, 11-12-2020 a 15-11-2026.
- 5.021 filas en prediction-ledger.jsonl, sin IDs duplicados.
- SHA-256 del ledger: 329a86d53c809b791d5edc91fe76fbd4b61b0f3f4da57b68f2660a3a2022ccc0, coincidente con manifiesto y diagnóstico.
- 4.432 fixtures comunes con el mercado.
- 14 segmentos competición-temporada.
- CI [43938706364](https://github.com/Baltas80/Kini-/actions/runs/43938706364): actionlint, Ruff lint/format y 257 tests pasados; 21 warnings upstream de penaltyblog/NumPy 2.5.
- Histórico [43938706414](https://github.com/Baltas80/Kini-/actions/runs/43938706414): 5.311 partidos e integridad validada.

Métricas puntuales en muestra completa: DC Brier 0.616681 / Log Loss 1.027801; ML 0.645508 / 1.071342; ensemble 0.613642 / 1.023023. En la muestra común de 4.432 partidos, mercado Brier 0.597534 / Log Loss 0.999473 y ensemble 0.613594 / 1.023023. El mercado sigue siendo mejor; no se ajustan pesos ni probabilidades para ocultar la diferencia.

El bootstrap pareado por semanas se confirma en el nuevo artefacto: 248 semanas, 10.000 réplicas. Para ensemble menos mercado, Δ Brier +0.01606 [0.01242, 0.01973], Δ Log Loss +0.02355 [0.01821, 0.02903], Δ accuracy -0.02911 [-0.03930, -0.01893]. Son intervalos percentiles exploratorios, sin corrección por comparaciones múltiples.

#### Backtest a nivel de cupón: implementación en curso

Se añade kini_engine/coupons.py con parser de HTML de HistoricalQuiniela y SELAE, reconciliación exacta de los 14 partidos y Pleno al 15, archivo JSONL con hashes, validación de timestamps y evaluación con un corte común por cupón.

El corte de entrenamiento es el día natural anterior al primer kickoff local, por lo que ningún resultado del mismo día de inicio del cupón entra en el modelo. Se generan DC, ML y ensemble DC/ML sobre una única instantánea; Pleno al 15 se estima con Dixon-Coles y queda identificado como tal. El optimizador directo existente recibe las probabilidades sin alteraciones y se evalúan cobertura real de columnas, aciertos, dobles, triples, coste y Pleno. No se usan cuotas históricas sin captura pre-kickoff verificable ni se estima rentabilidad.

Se añaden:
- scripts/import_historical_coupons.py: descarga secuencial, hashes y reconciliación con SELAE.
- scripts/backtest_coupons.py: evaluación walk-forward por cupón.
- tests/test_coupon_backtest.py: parser, orden oficial, inmutabilidad, cutoff común y evaluación del optimizador.
- docs/COUPON_BACKTEST.md: protocolo y limitaciones.
- .github/workflows/quiniela-coupon-backtest.yml: piloto de Jornada 21 de 2020/21.

La implementación local ha superado 5 tests de regresión y compilación sintáctica. Ruff no está instalado en este entorno local; la CI de GitHub debe validar lint/formato y el nuevo workflow debe comprobar el HTML real de ambas fuentes. Hasta ese resultado, el importador y el backtest por cupón están implementados, no validados.

El piloto de una jornada solo valida la ruta técnica; no es una muestra para seleccionar modelos ni inferir rentabilidad. Tras superarlo, ampliar a las 63 jornadas de 2020/21 y reconciliar cada una antes de agregar métricas.

Siguiente acción: revisar CI y el workflow quiniela-coupon-backtest; corregir cualquier discrepancia real de parsing/identidad y no ampliar el histórico hasta que el piloto completo pase.


#### Corrección de identidad del piloto antes de aceptar resultados

La revisión del flujo detectó que los nombres de HistoricalQuiniela no coinciden literalmente con los alias de Football-Data (por ejemplo, Athletic Club/Ath Bilbao y At. Madrid/Ath Madrid). No era aceptable dejar que el motor los tratara como equipos desconocidos ni considerar suficiente la coincidencia de marcadores.

Se incorpora un crosswalk explícito y limitado a la temporada 2020/21 en kini_engine/data/historicoquiniela_team_aliases.json. Cada destino se resuelve mediante el registro canónico Football-Data; no se usa fuzzy matching. Un nuevo módulo, kini_engine/coupon_identity.py, reconcilia los 15 fixtures por fecha, equipo local, equipo visitante y marcador con exactamente una fila del histórico Football-Data. La reconciliación utiliza el dataset completo únicamente para verificar identidad/fecha/resultado; la lista de entrenamiento se filtra después y sigue limitada al día anterior al primer kickoff.

Comprobación independiente del artefacto de datos 14261427836:
- 5.311 partidos.
- SHA-256 de historical_spain.csv: a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab.
- Jornada 21 de 2020/21: los 15 emparejamientos, fechas y marcadores de la fuente secundaria encuentran exactamente una fila en Football-Data tras aplicar el crosswalk; no hay discrepancias.
- El crosswalk incluye 30 nombres de equipo de la jornada y todos sus destinos existen como alias únicos en el registro canónico.

El script de backtest canonicaliza copias en memoria del archivo de cupones y conserva source_home/source_away para trazabilidad. El archivo JSONL original no se modifica. El resultado debe incluir fixture_reconciliation_count=15 para superar la puerta de aceptación.

Se añaden tests específicos para alias ausentes, reconciliación completa y discrepancias de fecha/marcador. Se amplían las listas Ruff de CI para incluir los módulos, scripts y tests nuevos. La ejecución anterior del piloto, iniciada antes de esta corrección de identidad, no se acepta como validación del motor; debe repetirse sobre el nuevo commit.

La nueva implementación está probada localmente con 8 tests del módulo de cupones/identidad y compilación sintáctica. El entorno local no tiene Ruff ni penaltyblog; la validación real de lint, parser de fuentes y motor queda delegada a la CI y al workflow específico del piloto. No se amplía a las 63 jornadas hasta que pase la reconciliación oficial, el crosswalk de 15 fixtures, DC, ML, ensemble y optimizador.


#### SELAE HTTP 403 y snapshot oficial normalizado para el piloto

La primera ejecución del importador, run [43949917492](https://github.com/Baltas80/Kini-/actions/runs/43949917492), descargó la página de HistoricalQuiniela pero recibió HTTP 403 al solicitar el detalle oficial SELAE desde el runner de GitHub Actions. No se aceptó ese intento como verificación oficial. Se mejoraron User-Agent y Referer para futuras consultas HTML, pero el piloto no depende de que el runner pueda acceder directamente a ese endpoint.

Se incorpora kini_engine/data/selae_official_coupon_results/2020-2021-21.json: extracto JSON normalizado de la página pública oficial SELAE de 13-12-2020, revisado manualmente y reconciliado con la página secundaria y el histórico Football-Data. El archivo no es HTML original. Su SHA-256 293660df4bbdd044c944998b2979935451dd19c8dcde5639a6a2f5fc76a35488 cubre exactamente los bytes del JSON normalizado. El registro del cupón conservará el URL oficial, el hash, el tipo de snapshot y el método/fecha de verificación. No se presenta ese hash como digest de la página HTML.

Se añade kini_engine/coupon_snapshot.py para verificar el extracto oficial por orden, nombres, marcadores, signos y Pleno al 15. El importador acepta --official-snapshot para el piloto; el flujo conserva el HTML bruto de HistoricalQuiniela y el snapshot oficial normalizado como evidencia separada. Se añaden tres tests de snapshot y se amplía CI para lint/formato de los módulos y scripts nuevos.

La prueba local de parser/identidad/snapshot suma 11 tests con motor y registry simulados para las partes de integración; no sustituye la CI real ni la ejecución de DC/ML/ensemble. La verificación independiente de los 15 fixtures contra historical_spain.csv sí se ejecutó sobre el artefacto real: 15/15 fechas, equipos y marcadores exactos tras el crosswalk.

Limitación abierta: el piloto J21 dispone de extracto oficial normalizado, pero no de captura HTML oficial automatizada. Para ampliar a las 63 jornadas hay que probar una vía oficial accesible (RSS/PDF/archivo) o mantener snapshots oficiales individualmente revisados; no se deben fabricar ni inferir resultados.


### 2026-11-16 — coupon pilot: source date label is not a publication timestamp

Inspection of the successful pilot artifact from run [43951898206](https://github.com/Baltas80/Kini-/actions/runs/43951898206) exposed a provenance defect in the first coupon-archive schema. The parser had named HistoricalQuiniela's summary field `Fecha 13/12/2020, 22:57` as `result_published_at`. The same coupon includes Pleno fixture Celta–Cádiz with kickoff 14-12-2020 21:00 and final score 4-0. Independent match records confirm that fixture was played on 14-12-2020, so the summary label cannot be interpreted as the publication time of all final results. The value is a page/draw-date label only.

Correction:
- Coupon archive schema bumped to version 2.
- Replaced `result_published_at` with `source_date` and `source_date_label_at`; the latter preserves the source label and timezone but is explicitly not a publication timestamp.
- SELAE result URL selection and normalized-snapshot reconciliation now use the draw date only.
- The coupon backtest still uses a separate conservative training cutoff (the previous local calendar day before the first kickoff); no source date label is used to establish data availability.
- Narrowed expected model/coupon exception handling to known data/model failures. Unexpected programming exceptions now propagate instead of being silently converted to failed coupon records.
- Added regression tests for the date-label distinction, draw-date mismatch and unexpected exception propagation.

Evidence from the pilot HTML:
- First kickoff: 2020-12-12 14:00 Europe/Madrid.
- Final Pleno fixture kickoff: 2020-12-14 21:00 Europe/Madrid.
- HistoricalQuiniela summary label: 2020-12-13 22:57 Europe/Madrid.
- Independent result coverage confirms Celta 4-0 Cádiz on 2020-12-14, after the displayed summary timestamp.
- Therefore the previous `result_published_at` semantics were invalid and have been removed.

The pilot's fixture reconciliation and model predictions remain useful as a technical pipeline test, but the archive generated under schema version 1 is not accepted as a point-in-time publication record. Schema version 2 subsequently passed CI and the coupon pilot; historical expansion still requires an official reconciliation for every jornada. No inference about result availability is made from the source date label.


### 2026-11-16 — coupon pilot schema v2 validated

The corrected coupon archive schema v2 passed the real GitHub Actions pilot on run [43953765300](https://github.com/Baltas80/Kini-/actions/runs/43953765300). Artifact `quiniela-coupon-pilot` ID `14268717790`, SHA-256 `c588b8909f3fbd381a62e43f6a34a16393127c2429265f177a34db1e1f3fa71b`. The archive manifest and coupon both declare schema version 2. `source_date=2020-12-13`, `source_date_label_at=2020-12-13T22:57:00+01:00`; no `result_published_at` is emitted.

The pilot coupon was reconciled with 15/15 fixtures against the normalized official SELAE snapshot (14 main results and Pleno al 15). Its first kickoff is 2020-12-12 14:00 Europe/Madrid; training cutoff 2020-12-11; 303 historical matches entered the fit. DC, ML and DC/ML ensemble each emitted 14 valid predictions. With 8 columns (3 doubles, no triples), cost was €6.00. Single-sign hits were DC 7, ML 5 and ensemble 7; best-column hits were 7, 6 and 8 respectively. No model covered all 14, and none hit Pleno. This is one jornada only: these counts validate the pipeline, not model quality, ticket profitability or the optimizer's general performance.

The official SELAE page for the draw is titled 13-12-2020 and displays a separate page date 14-12-2020; it lists the Celta–Cádiz Pleno result 4-0. This confirms why a source page date label must not be relabelled as a result-publication timestamp. The match itself was played on 14-12-2020 at 21:00 CET and was reported after the match. Sources: https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-13-de-diciembre-de-2020 and https://as.com/futbol/2020/12/14/primera/1607971433_793614.html.

The coupon result now explicitly records that the Pleno category-pair prediction is produced by Dixon-Coles using the maximum aggregated category-pair probability. ML's current 1/X/2 output is not represented as a Pleno score model. The coupon workflow no longer runs on audit-document-only changes; code, tests, data and workflow changes still trigger it.

CI run [43953991624](https://github.com/Baltas80/Kini-/actions/runs/43953991624) on the preceding code revision passed actionlint, Ruff lint, Ruff format and 270 pytest tests (21 upstream dependency warnings). The next commit adds Pleno provenance metadata and a workflow path-filter efficiency change; those changes require their own CI and pilot rerun before being marked validated.


### 2026-11-16 — Pleno provenance and final pilot validation

The Pleno provenance metadata is now present in the coupon backtest result: model `dixon_coles`, selection method `max_aggregated_category_pair_probability`, selected home/away categories, category-pair probability mass and training-match count. This is necessary because ML currently emits only 1/X/2 probabilities and must not be represented as a Pleno score model.

CI for commit `fbc1ce61f36c807cac0dc22164338fc3d42265db`, run [43954418890](https://github.com/Baltas80/Kini-/actions/runs/43954418890), passed actionlint, Ruff lint, Ruff format and 270 pytest tests. There were 21 existing upstream dependency warnings. The coupon pilot, run [43954407921](https://github.com/Baltas80/Kini-/actions/runs/43954407921), passed on the same commit. Artifact ID `14271905847`, SHA-256 `1a8be2606b751db33c39a0fffba5d1e3bd10f2f97cd003c032d8109a9234770c`; schema v2, 15/15 official-snapshot fixture reconciliations, 303 training matches, 14 predictions each for DC, ML and ensemble, and explicit Pleno provenance. The one-coupon hit counts remain a pipeline check only.

Efficiency changes:
- The coupon pilot now runs on PR changes or manual workflow dispatch, not both push and PR events.
- GitHub PR path filters evaluate the full PR diff, not only the latest commit. A dedicated `changes` job now compares paths since the last successful coupon pilot and skips documentation-only commits; its regression is validated by the next workflow run.
- The historical match-level backtest excludes coupon-only modules from its model-change trigger. Coupon changes are validated by the dedicated coupon workflow and do not require re-running the six-season match-level backtest.

These workflow changes are included in commit `5820a67082eedd2dfa1d91998ca4cb3b2fa1796a` and passed actionlint/CI. The coupon pilot also passed on that commit (run [43954807721](https://github.com/Baltas80/Kini-/actions/runs/43954807721), artifact ID `14271856198`, SHA-256 `c1a36492a5280bc14db4811f5de6c3f2925fb6951413a6b94d5e1a035a0ae54e`). The historical match-level backtest run [43954807605](https://github.com/Baltas80/Kini-/actions/runs/43954807605) remains queued behind an older long-running walk-forward; its updated change filter should skip the coupon-only/workflow/audit changes when it starts.


### 2026-11-16 — historical backtest/data-validation snapshot mismatch

The completed match-level backtest run [43951898236](https://github.com/Baltas80/Kini-/actions/runs/43951898236) built 5,321 fixtures and emitted 5,021 OOS forecasts (300-match initial training window). Its ledger manifest records dataset SHA-256 `e4b195593118215684ffefc8e70ffe0c8d88b3e28318d9c796f7b3b71c496475` and profile SHA-256 `fb7b216062d5cecf32141634d41a46a327aea6e756074f19a418ab38a7112000`.

The separate data-validation run [43951898519](https://github.com/Baltas80/Kini-/actions/runs/43951898519) at the same commit produced 5,311 fixtures, CSV SHA-256 `a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab`, and date coverage ending 2026-11-09. Its cache metadata shows Football-Data files were 10.4 hours old. The backtest job had downloaded fresh source CSVs and its build log reported 5,321 fixtures, with forecasts extending to 2026-11-15. These are different dataset snapshots; the validation artifact cannot be used to validate the backtest artifact. The backtest artifact also omitted the CSV and profile, so its exact dataset bytes cannot be independently recovered from that run. Its metrics are therefore exploratory, not a reproducible baseline.

Correction implemented:
- Historical data validation now invokes `build_history.py --refresh` and watches its own workflow file, preventing a restored cache from silently validating an older source snapshot.
- The historical backtest artifact now includes the exact CSV and profile used by that run.
- `scripts/analyze_prediction_ledger.py` accepts `--dataset-csv` and `--dataset-profile`, verifies their SHA-256 digests and byte size against the ledger manifest, checks profile integrity and row counts, and validates CSV required fields, dates, scores and fixture uniqueness.
- The historical backtest workflow passes those files to the diagnostic step; any mismatch fails the workflow rather than producing an apparently reproducible report.
- Added regression tests for exact dataset/profile bytes and tampered CSV rejection.

The next full walk-forward is triggered by the diagnostic-script change. Its artifact must contain the matching dataset/profile and pass the new snapshot verification before its metrics are accepted. The previous run's 5,021 forecast rows were structurally valid (five probability vectors per fixture, valid sums, unique IDs and prior cutoffs), but their dataset snapshot remains unverified because the source bytes were not archived.


### 2026-11-16 — fail-closed acceptance for coupon backtests

A code review found that `scripts/backtest_coupons.py` only required Dixon-Coles to evaluate every coupon before writing a successful result. The batch evaluator can record a failed ML or ensemble candidate inside an otherwise successful coupon result; therefore a multi-coupon workflow could have exited successfully with incomplete candidate coverage.

Correction implemented on `feat/selae-fixture-reconciliation`:
- Added `validate_coupon_backtest_acceptance()` and invoked it before the result JSON is written.
- Require exact coupon ID/order equality with the verified input archive.
- Require all three candidates (DC, ML, fixed DC/ML) to evaluate every coupon with zero failures and 14 valid normalized 1/X/2 vectors per coupon.
- Validate official 14-match and Pleno evidence, 15 ordered canonical fixture reconciliations, timezone-aware first kickoff, previous-local-calendar-day cutoff, minimum/fitted training counts, Pleno model/method/category/probability provenance, optimizer column budget, direct-system cap, ticket metrics and full-coupon coverage consistency.
- Added regression tests for success, failure of each model, malformed probability vectors and inconsistent aggregate model counts.

Commits:
- `37fb291` — initial fail-closed acceptance gate.
- `329e1f6` — validation cleanup and explicit numeric checks.
- `9d39661` — regression tests.

Status at this record: implementation committed; CI and real coupon pilot for this exact code head are pending. The previously validated Jornada 21 pilot does not validate this new acceptance code. Full-season import has not started and no multi-jornada performance conclusions are claimed.

Next action: inspect the PR CI and coupon pilot triggered by these changes; fix any failure before expanding beyond the single verified Jornada 21 snapshot.


### 2026-11-16 — coupon batch acceptance gate and CI lint remediation

A review of the batch coupon runner found that its previous success condition only required Dixon-Coles to evaluate every coupon. Because `evaluate_coupon_batch()` records individual candidate failures inside coupon results, ML or the ensemble could fail while the command still wrote a successful artifact.

Implemented a fail-closed acceptance validator in `scripts/backtest_coupons.py`:
- Exact coupon ID/order match with the verified archive.
- All three candidates (DC, ML, fixed DC/ML ensemble) must evaluate every coupon with zero aggregate failures.
- Exactly 14 valid, finite, normalized 1/X/2 vectors per candidate and coupon.
- Official main-results and Pleno verification plus all 15 ordered canonical fixture reconciliations.
- Timezone-aware first kickoff and previous-local-calendar-day training cutoff.
- Minimum history and fitted-model counts must agree.
- Explicit Dixon-Coles Pleno model/method/category/probability provenance.
- Optimizer budget, 31,104 direct-system cap, doubles/triples, cost/hit metrics and full-coupon coverage consistency.

Regression tests cover a valid result, each candidate failing, malformed probabilities and inconsistent aggregate counts.

Validation history:
- The coupon pilot on head `a2422ece46df3d32d6061639b24555fef862a24f`, run [43958091957](https://github.com/Baltas80/Kini-/actions/runs/43958091957), passed the new acceptance logic. It reconciled 15/15 official results and 15/15 canonical fixtures, used 303 prior matches with cutoff 2020-12-11, and produced 14 predictions for DC, ML and ensemble. Artifact ID `14272024052`, SHA-256 `ff08ab2e2a8db82482e6ec85c10a01e39d53bf1adbae57c35a6b0a8011c0940b`. This pilot validates one-coupon execution only.
- CI [43958234868](https://github.com/Baltas80/Kini-/actions/runs/43958234868) initially failed lint before formatting or pytest. Findings: import ordering, TRY004 exception classes in the new validator, and a pre-existing snapshot-test defect (missing `json` import plus redundant UTF-8 encoding of a literal). These were corrected; the snapshot fixture now uses byte literals and imports `json`.
- Latest code commits: `37fb291` (acceptance gate), `329e1f6` (validator cleanup), `9d39661` (regression tests), `5413cbd` (format), `be362bc` (lint fixes), `5f65bc7` (snapshot-test fix), `2ca450b` (consistent type-error reporting).
- The exact latest-head CI and coupon pilot are pending; the earlier successful pilot does not replace validation of the latest code head.

Status: acceptance implementation committed; latest-head CI/pilot validation pending. No multi-jornada expansion has been accepted. Full-season import still requires official evidence for every coupon; no result is inferred from the secondary source's page-date label.

### 2026-11-16 — coupon pilot artifact inspected; Ruff type-error fix

- The common-cutoff coupon pilot on head `e65d9d2a0a05a7d5e10e57f2acaf56137f9e57a2`, workflow [43958738341](https://github.com/Baltas80/Kini-/actions/runs/43958738341), completed successfully. Artifact `14272863093` (ZIP SHA-256 `5ca98c4e6cf7824fc1e692812fbddc80cbf62278a598fdfe309aa81f73c2409f`) contains the archive, raw secondary-source HTML, normalized SELAE snapshot and coupon backtest JSON.
- Independent artifact inspection confirms one coupon only (`2020-2021:21`), 15/15 canonical fixture mappings, official normalized snapshot flags for 14 main results and Pleno, first kickoff `2020-12-12T14:00:00+01:00`, conservative training cutoff `2020-12-11`, 303 training matches, and 14 probability vectors for each of DC, ML and fixed DC/ML ensemble. All three models completed with valid normalized vectors.
- With an 8-column budget the pilot produced 8 direct columns, 3 doubles, no triples and €6.00 cost. Best-column hits were DC 7, ML 6 and ensemble 8; no model covered all 14 results and Pleno was not hit. This is a pipeline pilot, not a performance sample; no model-selection conclusion is drawn.
- The rebuilt historical CSV in this run contained 5,321 rows (SHA-256 `e4b195593118215684efc8e70ffe0c8d88b3e28318d9c796f7b3b71c496475`), so this run's dataset snapshot differs from earlier 5,311-row profiles. The coupon's 303-match training slice is before its cutoff.
- CI [43958738354](https://github.com/Baltas80/Kini-/actions/runs/43958738354) stopped at Ruff before formatting and pytest. The sole reported finding was `TRY004` at `scripts/backtest_coupons.py:266`: a malformed boolean field is a type error and must raise `TypeError`, not `ValueError`.
- Corrected the exception type in commit [f15498d](https://github.com/Baltas80/Kini-/commit/f15498d6400b59d9826a698bee9f0d2080221fa8) and added a regression test for a string supplied as `covered_14` in [d91232b](https://github.com/Baltas80/Kini-/commit/d91232bf1b8a6eac151ca5457b1fabb320817373). This verifies that malformed boolean fields fail with a type-specific exception.

Status: one-coupon common-cutoff execution and acceptance gate validated on the prior code head; Ruff correction and regression test committed. CI on the updated head is pending. Multi-coupon/full-season evidence and joint ticket performance remain unvalidated.

### 2026-11-16 — multi-journey reviewed SELAE snapshot import

- Added `--official-snapshot-dir` to `scripts/import_historical_coupons.py`. Directory mode loads only `SEASON-JOURNEY.json`, requires every requested journey's snapshot, rejects missing files and symlinked files, validates the season slug/journey number, and never falls back silently to a live result request. Duplicate journey arguments are rejected.
- Each imported coupon and archive manifest now retain the exact normalized snapshot path and SHA-256. The snapshot loader rejects non-object JSON roots. Added tests for exact journey selection, missing snapshots, invalid journey numbers, unsafe season slugs and invalid JSON roots.
- Updated `.github/workflows/quiniela-coupon-backtest.yml` to exercise directory mode in its Jornada 21 pilot. Workflow [43968925804](https://github.com/Baltas80/Kini-/actions/runs/43968925804), head `73de23218dc32c7840e88233afd8e6002dff4264`, completed all steps successfully, including import from the reviewed snapshot directory, common-cutoff backtest, acceptance gate and artifact upload. Artifact `14277778583` (SHA-256 `5ca87635564eb5fdc15306472e49a1d625b3ab79fa53db7cd6cf6c1c4ade02e1`).
- Independent artifact inspection confirms one coupon (`2020-2021:21`), archive manifest snapshot directory `kini_engine/data/selae_official_coupon_results`, one journey-specific entry for `2020-2021-21.json`, and snapshot SHA-256 `293660df4bbdd044c944998b2979935451dd19c8dcde5639a6a2f5fc76a35488`. Both 14 main fixtures and Pleno were verified. DC, ML and fixed ensemble each generated 14 valid probability vectors using the same 303-match history and cutoff `2020-12-11`.
- The pilot's 8-column system generated 3 doubles, 0 triples, 8 direct columns and cost €6.00. Best-column hits: DC 7, ML 6, ensemble 8; no model covered all 14 results and none hit Pleno. One coupon remains a pipeline test, not a predictive-performance sample.
- The historical dataset used by the pilot had 5,321 rows, date coverage 2020-09-12 to 2026-11-15, SHA-256 `e4b195593118215684efc8e70ffe0c8d88b3e28318d9c796f7b3b71c496475`. The independently uploaded profile reports 0 incomplete scores, 0 duplicates, 0 score/result mismatches and 0 unresolved/ambiguous team identities (56 canonical teams, 10,642 references resolved).
- Official 2020/21 schedule crosswalk sources located: regular provisional calendar (journeys 1–53, including Jornada 21 on 2020-12-13, contest code 2020/052): https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Calendarios/CALENDARIO_Quiniela_Temp_20-21.pdf ; summer provisional calendar (journeys 54–63, contest codes 2021/030–039): https://www.loteriasyapuestas.es/f/loterias/documentos/Quiniela/Calendarios/CALENDARIO_VERANO_Quiniela_Temp_20-21.pdf . Both documents are explicitly provisional and are schedule references, not proof of final results.
- The official result page for 13 December 2020 independently confirms the 14 ordered results and Pleno Celta–Cádiz 4–0 (M–0): https://www.loteriasyapuestas.es/es/la-quiniela/resultados/la-quiniela-resultados-del-13-de-diciembre-de-2020 . Its page date is 14/12/2020 while the draw is labelled 13/12/2020; no exact result-publication timestamp is inferred.
- Baseline CI on prior head `e1887d935caa2ce071a28498db5612cd0ab74f73` passed actionlint, Ruff lint/format and 279 tests (21 upstream NumPy/penaltyblog warnings), workflow [43968401391](https://github.com/Baltas80/Kini-/actions/runs/43968401391). This run predates the multi-snapshot importer additions.
- Current branch head: `e063921e3eb78e8ca1ea42cd0963d720bd94f0da`. Latest CI [43969385341](https://github.com/Baltas80/Kini-/actions/runs/43969385341) is in progress. The directory-mode coupon pilot [43969385258](https://github.com/Baltas80/Kini-/actions/runs/43969385258) is queued; the completed pilot above validates the same importer logic on the immediately preceding code head.

Status: multi-snapshot import implemented and exercised end-to-end on one journey; latest full CI still pending. Full-season 2020/21 snapshots, calendar-to-result reconciliation for all 63 journeys, and multi-coupon ticket performance remain unvalidated. Next priority: finish latest CI, then strengthen coupon acceptance by persisting generated direct columns and validating the mathematical relation between doubles/triples, column count, Pleno multiplier, total bets and cost.


## 2026-11-17 — P6 direct-ticket persistence and acceptance hardening

The optimizer already generated its complete direct-column expansion, but the coupon backtest discarded those columns and retained only aggregate counts. That made it impossible for the acceptance gate to independently prove the 2^d × 3^t structure or recompute realized coverage from the actual 14-match result vector.

Implemented on feat/selae-fixture-reconciliation:

- Coupon backtest result schema advanced to version 2.
- Every model result now persists the exact ordered 14-sign columns, Pleno home/away category sets, Pleno multiplier and price per payable bet.
- Coupon results persist the actual 14 main outcomes and actual Pleno categories.
- Canonical Football-Data reconciliation now retains home/away goals and the derived result sign for each of the 15 fixtures; the Pleno categories are retained on fixture 15.
- The acceptance validator now proves column uniqueness and shape, the complete Cartesian direct multiple, column_count = 2^d × 3^t, the double/triple counts, total_bets = column_count × pleno15_multiplier, the 31,104 cap and cost = total_bets × price_per_bet.
- It recomputes single-sign hits, best-column hits, exact 14-match coverage, Pleno hit, full-coupon coverage and independent marginal coverage from the persisted columns, probabilities and reconciled actual outcomes.
- Added regression coverage for missing/duplicate columns, invalid multiple structure, Pleno multiplier, bet/cost arithmetic, actual-result reconciliation and recomputed coverage.
- Corrected the CI Ruff TRY004 finding in the official snapshot loader: a valid JSON document with a non-object root now raises TypeError, with a matching regression expectation.

Validation status at this entry: implementation and regression tests are committed to the PR branch; latest-head CI and the real Jornada 21 coupon pilot must complete before this unit is marked validated. The existing one-coupon pilot remains a pipeline check only. No full-season coupon performance or profitability claim is made. No change to master; no PR merge.


### 2026-11-17 — SELAE minimum participation and single-Pleno-pair acceptance

- Tightened the coupon acceptance gate to verify the optimizer's minimum-total-bets metadata (2), maximum authorized total bets (31,104) and current official unit price (0.75 EUR).
- The coupon backtest now explicitly requires the one predicted Pleno category pair used by the current evaluation path. The lower-level optimizer still supports multiple categories, but this backtest rejects them until their combined Pleno probability mass and set-based realized coverage are modelled.
- Added regression tests for the two-bet minimum, official price and unsupported multi-category Pleno ticket. The workflow's independent artifact check now verifies the same monetary bounds.
- Validation was completed on the subsequent validated head (see the 2026-11-17 P6 validation record below).


## 2026-11-17 — P6 coupon-ticket acceptance validated

Validated branch head: ca03ad7fc9455d2cc6ab6c4e4cec8f8eb3f19279 (PR #9, feat/selae-fixture-reconciliation). No changes to master and no merge.

### Evidence

- CI run 43980635311: success. Ruff lint, Ruff formatting and the full test suite passed; 294 tests passed.
- Coupon pilot run 43980635409: success. The real official Jornada 21 snapshot passed the common-cutoff backtest and coupon-level acceptance gate. Artifact: quiniela-coupon-pilot, run artifact 14282859019.
- Historical data validation run 43980635296: success. Artifact: kini-historical-data, run artifact 14283197530.
- Historical model backtest was skipped by its change filter because this unit did not modify predictive model code; no new Brier/Log Loss or season-level model result is claimed.

### Coupon pilot facts

Coupon 2020-2021:21; first kickoff 2020-12-12 14:00 Europe/Madrid; common training cutoff 2020-12-11; 303 historical matches used by each model. Fourteen main results and Pleno categories were reconciled against the reviewed official snapshot and Football-Data scores.

All three candidates produced 14 valid 1/X/2 probability vectors and a reproducible 8-column direct system with 3 doubles, 0 triples, one Pleno category pair, 8 payable bets, 0.75 EUR per bet and 6.00 EUR total cost.

| Candidate | Single-sign hits | Best column hits | Exact 14 covered | Pleno hit | Full coupon | Independent marginal coverage |
|---|---:|---:|---|---|---|---:|
| Dixon-Coles | 7/14 | 7/14 | No | No | No | 0.0008682 |
| ML | 5/14 | 6/14 | No | No | No | 0.0004538 |
| Ensemble | 7/14 | 8/14 | No | No | No | 0.0004306 |

This is one historical coupon and a pipeline/acceptance validation, not a statistically sufficient model comparison or evidence of profitability. The marginal coverage estimate assumes independent fixture outcomes and must not be described as a joint 14-match probability.

### Historical data quality snapshot

The successful validation artifact contains 5,322 complete fixtures from 14 Football-Data CSV sources (La Liga and Segunda, seasons 2020/21 through the partial 2026/27 season), dated 2020-09-12 to 2026-11-16. No duplicate rows, missing team names, missing final scores, incomplete scores or invalid fixture dates were found.

The canonical identity registry resolved all 10,644 team references to 56 unique teams, with zero unresolved or ambiguous references. Historical dataset SHA-256: 7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44.

Odds coverage is not uniform: B365 1X2 odds are missing for 15 fixtures (0.28%), Pinnacle 1X2 for 734 (13.79%), William Hill 1X2 for 2,230 (41.90%), Interwetten 1X2 for 2,375 (44.63%) and Betfair 1X2 for 4,480 (84.18%). Market comparisons must use same-match samples and must not assume universal odds availability or proven historical publication timestamps.

### Remaining work and next priority

P6 ticket persistence, arithmetic, minimum/maximum bet bounds, current unit price, one-pair Pleno scope and realized-hit recomputation are validated. Still open within P6: dependence-aware joint coverage, multi-ticket diversification and payout/expected-value modelling.

Next priority returns to P1/P2: document source provenance and historical variable availability, then audit every model feature and odds timestamp for leakage. The separate live KinielaGPT details diagnostic still receives HTTP 400 for jornada 23 / temporada 2027; this is an external endpoint diagnostic and did not block CI, data validation or the official coupon pilot.


## 2026-11-17 — P1/P2 preliminary temporal-data audit

This is a code-and-test audit, not yet a final proof of every source timestamp.

### Verified safeguards

- `backtest.py` predicts all fixtures on a calendar date before adding any result from that date to the training history. The model is refitted from prior dates only; same-day fixtures cannot train one another.
- `FeatureModel._training_rows` applies the same day-batched rule when creating supervised labels. Its 12 rolling features use completed results from prior dates (overall, home-only and away-only form); standings and arbitrary context fields without publication timestamps are deliberately excluded.
- Current-fixture ML inference uses the latest permitted feature history without refitting the estimator.
- Dixon-Coles, ML, recent-form and H2H paths contain explicit prior-history assertions/filters. Tests cover same-day and future-result exclusion, including date-decay behavior.
- LAE data requires a timezone-aware capture timestamp before kickoff, a matching fixture identity, evidence URL, freshness within 24 hours and a valid probability vector.
- Market odds are drawn from pre-closing columns, overround is removed, Pinnacle is excluded from 2025-07-23 onward, and missing/unparseable kickoff times plus Tuesday/Friday snapshot days fail closed. The market backtest reports metrics on the eligible common fixture sample; the model-only DC/ML ensemble is separate from the market/LAE ensemble.

### Remaining temporal uncertainty

Football-Data's historical odds rows do not carry an individual capture timestamp or explicit timezone. The current `schedule_compatible` market status is therefore a documented collection-schedule heuristic, not proof that every quoted price was observable before each kickoff. The full ensemble can include this market vector at 7% weight when that heuristic passes. Treat market-only and market-inclusive results as provisional/sensitivity evidence until source-level publication timing is independently documented; do not present them as timestamp-verified. The `ensemble_dc_ml` path remains available without this market dependency.

The latest data profile also shows materially uneven odds coverage (B365 1X2 missing 15/5,322; Pinnacle 734; William Hill 2,230; Interwetten 2,375; Betfair 4,480). Provider comparisons must use each provider's exact common fixture sample and a common model sample; filling absent prices with uniform probabilities would not be a valid market benchmark.

### Next executable unit

Complete P1 provenance for the Football-Data and LAE feeds: locate and record the source's actual collection/publication schedule, distinguish capture time from kickoff time, and decide whether schedule-compatible Football-Data odds stay as a clearly labelled sensitivity benchmark or can be promoted to a timestamp-verified input. Then continue P2 by tracing every remaining feature and calibration/ensemble fitting boundary through the walk-forward ledger.


## 2026-11-17 — Football-Data odds timing and usage terms verified

Official source pages reviewed:

- `https://football-data.co.uk/data.php`: since 2019/20, the unsuffixed first odds set is collected after market opening at the times on the fixtures page; closing odds use the additional `C` suffix. The source also warns that Pinnacle's public feed has been systematically stale since 2025-07-23.
- `https://football-data.co.uk/matches.php`: weekend snapshots are collected Friday afternoons, generally no later than 17:00 British time; midweek snapshots Tuesday, no later than 13:00 British time.
- `https://football-data.co.uk/notes.txt`: `Date` and `Time` mean match date and kickoff time; the unsuffixed bookmaker columns are pre-closing, while the closing versions carry `C`.
- `https://football-data.co.uk/contact.php`: the free CSV service is stated to be for private/personal betting or academic research, at most light automated downloads (twice weekly maximum); commercial and AI/data-training use is not granted by default.

### Consequences for this project

1. The existing code's pre-closing column selection, exclusion of Tuesday/Friday fixtures, missing-kickoff rejection and Pinnacle cutoff are consistent with the provider's published schedule. This supports a schedule-compatible classification, but the CSV still has no per-fixture capture timestamp or timezone.
2. A fair market comparison needs a common information cutoff. The current walk-forward model for a Saturday/Sunday fixture can include Friday/Saturday results, while the corresponding odds snapshot was taken Friday by 17:00. For Wednesday/Thursday fixtures, model history can include Tuesday results after the Tuesday 13:00 snapshot. The existing same-match sample therefore does not, by itself, prove equal information sets.
3. The next implementation should derive the documented snapshot day for each market row and add a strict common-time comparison. At minimum, exclude a row from that strict sample if the model's feature/training history contains any result dated on or after the odds snapshot day. Keep the larger schedule-compatible market sample as a separately labelled sensitivity benchmark.
4. The source's usage terms are a production blocker if Quiniela Predictor is distributed commercially or uses the data for commercial AI training. Do not increase automated download frequency; the existing weekly scheduled refresh is within the source's stated light-download limit, but written permission or a licensed provider is required before commercial use. TheStatsAPI is the source's named subscription alternative.

This finding does not invalidate the existing historical-data integrity checks. It limits what can be claimed about market timing and what use of the data is permitted.


## 2026-11-17 — Football-Data download frequency guard

The historical-data validation workflow previously ran `build_history.py --refresh` for every matching push/PR event as well as its weekly schedule. Because refresh bypasses the 24-hour cache, repeated PR synchronizations could cause repeated automated downloads, conflicting with the provider's twice-weekly maximum.

Implemented a fail-closed `--offline` mode in `scripts/build_history.py`: it accepts a valid stale cache but never creates an HTTP request; it fails if the cache is absent or invalid. The workflow now refreshes only on the weekly schedule or an explicitly opted-in manual dispatch. Push/PR validation uses offline cache only. Regression tests prove stale-cache reuse and no-network failure when no cache exists.

This limits automated refresh to once weekly by default and preserves a manual second refresh only when explicitly requested. Commercial/AI-training permission remains unresolved and must be obtained before commercial deployment.


The separate `historical-backtest` workflow was also using `build_history.py` without an offline guard and had no shared cache restore. It now restores the validated Football-Data cache and builds offline; its weekly schedule runs after the Monday data refresh. Only the scheduled/explicitly opted-in data-validation workflow can refresh and save the source cache. PR, push and historical-backtest runs cannot download Football-Data CSVs.


## 2026-11-17 — Strict common-information-time market benchmark implemented

The prior schedule-screened comparison used the same fixtures for model and market metrics, but the information cutoffs were not necessarily aligned: a Saturday forecast could use Friday results after the Friday odds snapshot, and a Wednesday forecast could use Tuesday results after the Tuesday snapshot.

Implemented on `feat/selae-fixture-reconciliation`:

- Derive the documented snapshot calendar date for Wednesday/Thursday fixtures (Tuesday) and Saturday/Sunday fixtures (Friday). Monday, Tuesday and Friday fixture dates fail closed in this stricter benchmark because no unambiguous prior snapshot date is assigned.
- Persist `market_snapshot_date`, `strict_common_time_eligible` and an explicit exclusion reason in every forecast-ledger row.
- Require both the latest available training-history date and the actual model-fit cutoff to be strictly earlier than the market snapshot date. Same-snapshot-day results are excluded.
- Add a separate common-information-time comparison for all five model streams against the consensus market and, independently, Bet365. The larger schedule-screened comparison remains available as a sensitivity benchmark.
- Add regression tests for weekday-to-snapshot mapping and for fixtures whose prior training history falls on or after the odds snapshot date.
- Add a historical-backtest CI gate requiring non-empty, identical model/market samples and checking the persisted ledger eligibility decisions.

This is deliberately a conservative **date-level** alignment. It does not create exact odds-capture timestamps, does not prove that a particular quote was observable at a precise instant, and does not resolve the Football-Data commercial-use restriction. Validation is pending on the updated PR head; no new model metrics are claimed yet.

## 2026-11-17 — Live round resolution verified; CI regression corrected

### Changes and regression diagnosis

- CI run [43989398909](https://github.com/Baltas80/Kini-/actions/runs/43989398909) reached pytest and reported **305 passed, 1 failed**. The only failure was a test-double contract mismatch: `summarize_probability_payload()` calls `KinielaGPTSource._probability_map()`, while the monkeypatched `FakeSource` did not expose that parser.
- Commit [7233232](https://github.com/Baltas80/Kini-/commit/7233232413ed22eba23b174999c9672774d6e51d) updates the fake to delegate to the real static parser. It does not alter production parsing or source behavior.
- The next CI attempt [43989909946](https://github.com/Baltas80/Kini-/actions/runs/43989909946) reached Ruff formatting and identified one pre-existing formatting mismatch in the new live round-resolution diagnostic. Commit [d17c8c9](https://github.com/Baltas80/Kini-/commit/d17c8c901f62ae4b9ba0ade58827ce84522439cb) applies the formatter's exact single-line form.
- CI [43990123507](https://github.com/Baltas80/Kini-/actions/runs/43990123507) passed on `d17c8c9`: actionlint, Ruff lint, Ruff formatting and **308 tests passed** (21 third-party warnings). The earlier test and formatting failures are therefore closed on that head.

### Live LAE round-resolution evidence

Read-only live diagnostic [43990123543](https://github.com/Baltas80/Kini-/actions/runs/43990123543), artifact [14287650911](https://github.com/Baltas80/Kini-/actions/runs/43990123543/artifacts/14287650911), exercised the resolver against the public LAE feed:

- BASE feed reported jornada 23.
- Jornada 23 was explicitly inactive and had zero valid probability vectors.
- Jornada 22 was explicitly active, with 15 fixture rows and 14 valid normalized 1/X/2 vectors.
- `KinielaGPTSource.last()` correctly resolved **jornada 22 / temporada 2027**, reason `active_lae_round`. This validates the new resolver against the live feed, not merely a fixture test.
- The workflow ended with `blocked_missing_authorization`: `KINIELAGPT_AUTHORIZATION` was empty in Actions, so the separate details endpoint and its fixture-order crosswalk could not be queried. This is a real external credential dependency, not a prediction or parser failure. No token is fabricated and the public LAE probabilities remain subject to the existing kickoff/provenance eligibility gate.

### Current data validation

Historical-data validation [43990123230](https://github.com/Baltas80/Kini-/actions/runs/43990123230) passed on `d17c8c9`:

- 5,322 completed fixtures from seven seasons and two leagues.
- Zero duplicate fixtures, zero score/result mismatches, zero unresolved canonical team identities and zero ambiguous identities.
- `integrity_passed=true`.
- Artifact `kini-historical-data`, ID `14287970645`, ZIP SHA-256 `bec9a06d63a8504650918a5021a62c548e5bf958dd000df5f57f4912d102f890`.

The coupon workflow [43990123283](https://github.com/Baltas80/Kini-/actions/runs/43990123283) succeeded but its pilot job was skipped by the change filter; it is not new coupon acceptance evidence.

### Current head and next action

A subsequent workflow-only commit [577633f](https://github.com/Baltas80/Kini-/commit/577633fa9c623f812ce80e00c366e9f6b9e6e6aa) tightens the live-diagnostic baseline filter: a completed attempt counts only when the inspect step actually ran and the evidence artifact uploaded. This prevents a skipped diagnostic job from being mistaken for a completed inspection.

Current PR #9 head is `577633fa9c623f812ce80e00c366e9f6b9e6e6aa`; its CI [43990312616](https://github.com/Baltas80/Kini-/actions/runs/43990312616), historical backtest [43990312610](https://github.com/Baltas80/Kini-/actions/runs/43990312610), data validation [43990312584](https://github.com/Baltas80/Kini-/actions/runs/43990312584) and live diagnostic [43990312660](https://github.com/Baltas80/Kini-/actions/runs/43990312660) are pending or running. The backtest run on the immediately preceding head was cancelled when this newer commit arrived; no strict common-information-time metrics are claimed yet.

Next priority: finish the current-head walk-forward run and inspect its artifact for non-empty, identical strict common-time model/market samples. Keep the benchmark labelled date-aligned rather than timestamp-verified. The missing provider-issued `KINIELAGPT_AUTHORIZATION` and Football-Data commercial-use permission remain explicit external blockers. PR #9 remains a draft stacked on PR #8; no merge or direct change to `master`.


## 2026-11-17 — First completed walk-forward metrics and market comparison

Historical-backtest run [43983233928](https://github.com/Baltas80/Kini-/actions/runs/43983233928) completed successfully on code revision `76cf820caa5841efe129e96c52777810bb2832f8`. This is a completed baseline run, not yet the final validation of the newer snapshot-time and live-source changes.

### Non-empty prediction streams

- Dataset snapshot: 5,322 rows, SHA-256 `7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44`.
- Forecast ledger: 5,022 fixtures, 2020-12-11 through 2026-11-16; ledger SHA-256 `ee612fffe69e56e1fb55707949f27f54c5d113eb9ae7495c626a89d22aa1abb6`.
- All five modes produced **5,022 forecasts**: Dixon–Coles, ML, ensemble, DC+ML ensemble and adaptive DC+ML ensemble. The former `n=0` condition did not recur in this run.
- Market probabilities were available for 4,433 fixtures. The wider model/market comparison therefore uses the same 4,433 fixtures, but not necessarily the same information cutoff.

### Wider common-fixture benchmark (not snapshot-time fair)

Market consensus on the 4,433-fixture common sample: accuracy **0.507331**, multiclass Brier **0.597459**, log loss **0.999371**.

The best model mode was the standard ensemble, but it remained materially worse: accuracy **0.478231**, Brier **0.613559**, log loss **1.022974**. Its paired model-minus-market differences were:

- Brier: **+0.016099**, 95% weekly-cluster bootstrap CI **[+0.012319, +0.019869]**.
- Log loss: **+0.023603**, 95% CI **[+0.018076, +0.029212]**.
- Accuracy: **−0.029100**, 95% CI **[−0.0395, −0.0190]**.

ML was substantially weaker: accuracy **0.438078**, Brier **0.647430**, log loss **1.074138**. Market Brier was lower in all **14/14 competition-season segments** in this wider sample. The paired uncertainty used 10,000 bootstrap resamples clustered by ISO week (249 weeks).

This is strong evidence that the current learned models are not adding value on this dataset, even though their forecasts may have access to later information than the market snapshot. It is not a fair same-information-time market comparison and must not be used to claim market superiority under strict temporal parity.

### Strict common-information-time sample

The conservative existing-cutoff gate produced only **111 fixtures**. On that sample market Brier was **0.595927**, versus **0.623886** for the ensemble and **0.670224** for ML. The direction is consistent, but 111 fixtures are insufficient for a robust model-selection decision. The current gate filters existing forecasts whose history/model-fit cutoff predates the snapshot; it does not yet regenerate each model at the snapshot date.

The prequential-calibration diagnostic had a larger 3,856-fixture common market sample, but it is also not the strict snapshot-time comparison. Calibrated ensemble Brier/log loss were approximately **0.61153 / 1.0217**, against market **0.59665 / 0.99799**. Calibration does not close the observed gap.

### Decision and next engineering unit

- Keep the market as the strongest measured reference; do not promote ML or an ensemble as superior on the present evidence.
- Do not discard Dixon–Coles or the ensemble solely from this non-parity comparison. First implement **snapshot-aligned walk-forward forecasts**: for each market snapshot date, refit using only results strictly earlier than that date, predict the corresponding fixtures, and compare model and market on the resulting identical sample.
- Raise the strict common-time acceptance floor to at least **500 fixtures** (or report the benchmark as insufficient and fail the acceptance gate). The current `n=111` must not be labelled a validated market comparison.
- Keep the wider 4,433-fixture comparison as a sensitivity benchmark, explicitly labelled with its information-time limitation.

The next full historical run [43988937525](https://github.com/Baltas80/Kini-/actions/runs/43988937525) is still running on revision `4892fc6`; the newer current-head run [43990435803](https://github.com/Baltas80/Kini-/actions/runs/43990435803) is queued. Current PR head at this log update is `a83661f27a42da0f43b8d9c376e9e6a8da7f17ee`. PR #9 remains unmerged; `master` has not been modified.



## 2026-11-17 — Inspección del artefacto de backtesting y suficiencia del benchmark

La ejecución [43988937525](https://github.com/Baltas80/Kini-/actions/runs/43988937525) terminó correctamente sobre la revisión de código `4892fc622c98832f7cf990502be8d22c86f0db63`. Se descargó e inspeccionó el artefacto `historical-backtest` ID `14286994505` (SHA-256 `51c67b5870204aa9013ce0dbe4b76a8ec96cb5982aa4ac25f423cdee280c07cc`).

- Dataset: 5.322 partidos; el manifiesto de la ejecución conserva el hash `7251b84acd803047746c0c55c6bdabb60d9499208cfd6c781f72080295346f44`.
- Forecast ledger: 5.022 predicciones, del 2020-12-11 al 2026-11-16.
- Dixon–Coles, ML, ensemble, DC/ML fijo y DC/ML adaptativo: **5.022 predicciones cada uno**, con **cero errores registrados**.
- Mercado con filtro de calendario: 4.433 partidos; se excluyeron 588 filas ambiguas.
- La comparación de corte temporal estricta actual solo contiene **111 partidos**. Mercado: Brier 0,595927 y Log Loss 1,001731. Dixon–Coles: Brier 0,627083 y Log Loss 1,045139. Ensemble principal: Brier 0,623886 y Log Loss 1,047315. ML: Brier 0,670224 y Log Loss 1,106471.
- Motivos de exclusión en el filtro actual: 3.880 por corte de entrenamiento/refit posterior o igual al snapshot y 442 por fecha de snapshot no asignable.

La inspección confirma una deficiencia en la puerta de aceptación: el workflow exige actualmente que el conjunto estricto sea no vacío, pero no aplica el umbral mínimo de 500 partidos acordado en el propio registro. Por tanto, un workflow verde con n=111 **no valida** la comparación temporal de mercado.

Se realizó además un preflight sobre el CSV y el ledger del mismo artefacto: **3.991 fixtures** con mercado elegible, snapshot de martes/viernes asignable y al menos 300 resultados históricos anteriores a la fecha del snapshot, repartidos en 319 fechas de snapshot. Es un recuento de candidatos, no predicciones ni métricas. Indica que una evaluación realmente alineada —reentrenar/refitar en cada fecha de snapshot y predecir conjuntamente los partidos cubiertos por esa captura— puede superar el mínimo de 500 sin relajar el corte temporal.

La siguiente unidad P0 queda definida: implementar el walk-forward por fecha de snapshot, mantener todos los partidos cubiertos por una misma captura con el mismo modelo y el mismo historial anterior al snapshot, y hacer fallar la aceptación si la muestra común resultante es inferior a 500. El filtro actual de predicciones ordinarias se conserva como diagnóstico histórico, no como benchmark temporal definitivo.

La ejecución más reciente de histórico [43990598086](https://github.com/Baltas80/Kini-/actions/runs/43990598086) seguía en el paso de comparación cuando se inspeccionó; no se le atribuyen métricas nuevas. PR #9 continúa en borrador y sin fusionar. No se ha modificado `master`.


## 2026-11-17 — Walk-forward completado y aceptación temporal reforzada

La ejecución [43990598086](https://github.com/Baltas80/Kini-/actions/runs/43990598086) terminó correctamente antes de incorporar la nueva puerta de aceptación. Su artefacto es [14288932539](https://github.com/Baltas80/Kini-/actions/runs/43990598086/artifacts/14288932539), digest SHA-256 `44ec2d6c90d6f8a68861f0f2f206620749da9f2ef3ac5fdd162153c05dd64e3f`.

- Periodo de test: 2020-12-11 a 2026-11-16; entrenamiento inicial: 300; refit ordinario cada 30 fechas de pronóstico.
- Los cinco streams generaron **5.022/5.022 predicciones** y registraron **cero errores**.
- Mercado schedule-screened: 4.433 partidos. La comparación amplia usa los mismos fixtures para cada modelo, pero no acredita igualdad del instante informativo.

| Stream | n | Accuracy | Brier | Log Loss |
|---|---:|---:|---:|---:|
| Dixon–Coles | 5.022 | 48,19% | 0,616650 | 1,027756 |
| ML | 5.022 | 44,17% | 0,645490 | 1,071314 |
| Ensemble principal | 5.022 | 47,95% | 0,613610 | 1,022979 |
| DC/ML fijo | 5.022 | 47,59% | 0,615849 | 1,026356 |
| DC/ML adaptativo | 5.022 | 47,73% | 0,616060 | 1,026662 |
| Mercado | 4.433 | **50,73%** | **0,597459** | **0,999371** |

En el filtro temporal estricto heredado solo quedan **111/4.433** fixtures. Los cinco modelos y el mercado se comparan sobre esos mismos 111 partidos, pero esta muestra no es suficiente para seleccionar modelos. Brier/Log Loss del mercado son 0,595927/1,001731; Dixon–Coles 0,627083/1,045139; ML 0,670224/1,106471; ensemble principal 0,623886/1,038656; DC/ML fijo 0,627702/1,043891; DC/ML adaptativo 0,629634/1,047315. Las exclusiones del filtro actual son 3.880 por corte de entrenamiento/refit no anterior al snapshot y 442 por snapshot no asignable.

### Puerta de aceptación para la siguiente validación

El commit [c53c143](https://github.com/Baltas80/Kini-/commit/c53c143a94cf043973fe3f31dbaff1685fff2955) añade al workflow una aceptación separada para `snapshot_aligned_market`. Exige:

- Al menos **500 fixtures comunes**.
- Refit por fecha de snapshot, usando resultados completados estrictamente anteriores a esa fecha.
- Las cinco configuraciones con el mismo conjunto de fixtures que el mercado.
- Cero errores de predicción por configuración.

El filtro anterior de 111 filas queda como diagnóstico, no como sustituto. El nuevo gate todavía no ha sido ejercitado por un backtest completo: el workflow de la nueva revisión [43994090734](https://github.com/Baltas80/Kini-/actions/runs/43994090734) omitió el job pesado porque el cambio era únicamente de documentación/workflow. CI [43994090719](https://github.com/Baltas80/Kini-/actions/runs/43994090719) sí validó actionlint, Ruff, formato y **308 tests pasados** (21 warnings upstream de penaltyblog/NumPy 2.5). La validación de datos [43994090764](https://github.com/Baltas80/Kini-/actions/runs/43994090764) pasó con **5.322 fixtures**, `integrity_passed=true`, cero duplicados, cero conflictos, cero identidades no resueltas y cero ambiguas.

El preflight ya realizado sobre el CSV y ledger del artefacto anterior identificó **3.991 fixtures candidatos** con mercado elegible, fecha de snapshot asignable y al menos 300 resultados previos; se distribuyen en **319 fechas de snapshot**. Es un recuento de candidatos, no un backtest ni una métrica predictiva. La próxima implementación debe generar las predicciones de nuevo en cada fecha de snapshot y conservar una misma información de entrenamiento para todos los partidos cubiertos por esa captura.

PR #9 sigue abierto y en borrador, con base en `feat/canonical-team-identity-registry`. No se ha fusionado ninguna PR ni se ha modificado `master`.

**Siguiente acción P0:** implementar el motor walk-forward alineado a snapshot y ejecutar el benchmark completo contra la nueva puerta de aceptación. Mantener la limitación de fecha (no timestamp) explícita; no afirmar que las cuotas históricas tienen hora exacta de captura.

## 2026-11-17 — Implementación del walk-forward alineado por snapshot

Se incorpora el motor snapshot-aligned y su integración en el comando compare.

- Agrupa los partidos con mercado explícitamente elegible por la fecha de captura documentada de Football-Data: martes para miércoles/jueves y viernes para sábado/domingo.
- Para cada fecha de snapshot construye de nuevo el historial con resultados completos cuya fecha de partido sea estrictamente anterior al snapshot. Se excluyen resultados del propio día del snapshot.
- Ejecuta un único ajuste de KiniEngine por fecha de snapshot. Todos los partidos asignados a esa captura comparten el mismo historial y el mismo modelo.
- Predice Dixon–Coles, ML, ensemble, DC/ML y DC/ML adaptativo. El peso adaptativo solo utiliza predicciones OOF de snapshots anteriores cuyos partidos ya son anteriores al snapshot actual.
- El ensemble solo recibe LAE si la captura LAE verificada es anterior a la fecha del snapshot. Los valores capturados el mismo día o después se excluyen de la predicción snapshot-aligned.
- La muestra común se forma únicamente cuando los cinco modelos y el mercado producen vectores 1/X/2 válidos para el mismo fixture. Se registran errores por modelo y no se normalizan silenciosamente vectores inválidos.
- Se genera un ledger inmutable separado, snapshot-aligned-prediction-ledger.jsonl, con SHA-256 del dataset, revisión de código, fixture, snapshot, historial de entrenamiento y probabilidades de cada modelo.
- La puerta de CI exige al menos 500 fixtures comunes, cero errores, un único ajuste por snapshot, cutoff estrictamente anterior, historial idéntico para todos los partidos de una captura y coincidencia del hash de fixtures entre ledger, modelos y mercado.

La implementación y las nuevas pruebas se incorporan en una sola revisión de la rama. La validación CI y el backtest completo deben finalizar antes de declarar el benchmark aceptado. La limitación de timestamps exactos de captura de cuotas permanece abierta: el benchmark es de alineación conservadora por fecha, no de verificación por hora.

