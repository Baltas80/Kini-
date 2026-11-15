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

Open limitation: the registry covers only Football-Data SP1/SP2 labels. SELAE coupon teams, Liga F, cup and European fixtures remain unresolved until independently verified aliases, competition IDs and kickoff dates are available. No model probabilities or backtest metrics were changed by this identity-layer work.


## SELAE fixture reconciliation layer — 2026-11-15

A separate, fail-closed reconciliation layer has been implemented on branch `feat/selae-fixture-reconciliation`, stacked on the canonical identity registry branch and proposed as [PR #9](https://github.com/Baltas80/Kini-/pull/9).

- `kini_engine/fixture_reconciliation.py` validates imported SELAE JSONL records (schema v1/v2), official SELAE provenance, all 14 positions, played score/sign consistency and the public-draw non-played contract.
- `data/selae_fixture_crosswalk.json` now contains ten evidence-backed mappings for coupon positions 1–10: Málaga–Racing de Santander, Osasuna–Athletic Club, Valencia–Real Madrid, Elche–Betis, Real Sociedad–Rayo Vallecano, Celta–Levante, Villarreal–Getafe, Cádiz–R. Oviedo, Girona–Almería and Sporting–R. Valladolid. The kickoff times are supported by official club schedule pages; Football-Data competition/season/date/team labels and full-time scores were checked against the historical CSV artifact.
- Historical CSV artifact: workflow run [43698382204](https://github.com/Baltas80/Kini-/actions/runs/43698382204), SHA-256 `a01a68393de69c7ad37d2088864093a50108df9e299f1993d855cad87147acab`. The ten crosswalk rows were matched 10/10 to unique SP1/2627 or SP2/2627 rows with identical full-time scores.
- Each crosswalk entry carries the exact SELAE display labels, Football-Data labels, competition, season, gender, independently sourced timezone-aware kickoff, exact Football-Data calendar date, stable official schedule-page URL, schedule source, HTTPS evidence and UTC verification timestamp.
- The reconciler now loads the generated `data/historical_spain.csv` and requires an exact competition/season/date/home/away row. It rejects absent or duplicate rows and any full-time score discrepancy. The Football-Data `Time` field is retained for provenance but is not treated as an authoritative timezone-aware kickoff.
- Both Football-Data identities are resolved through the canonical registry with exact provider, competition, season and gender scope. Unknown, ambiguous, mismatched, out-of-scope and duplicate records are rejected or reported unresolved.
- For the full 8 November 2026 coupon, 13 fixtures were played and one was resolved by public draw. Ten of the 13 played fixtures are now mapped; the three women's fixtures remain unresolved pending a source-specific Liga F historical identity dataset. The public-draw fixture is excluded from football labels.
- Reconciled goals and 1/X/2 remain targets only; the tool does not add them to model training. Candidate-label export is refused unless every played fixture in the supplied coupon sample is reconciled and there are no unused crosswalk entries.
- CI runs Ruff on the new implementation and the full pytest suite. Identity-only reconciliation files are excluded from the expensive model backtest and historical-data rebuild path filters.

The first CI attempts exposed test-fixture construction mistakes and Ruff import-order issues; those were corrected. Latest PR CI [43699765076](https://github.com/Baltas80/Kini-/actions/runs/43699765076) passed on code head `7c5ef9555b5acbcf7e5daf106be0a3ec71d83a57`: Ruff reported all checks passed and pytest reported 90 passed, 4 upstream NumPy/penaltyblog deprecation warnings, in 2.16 seconds. The subsequent `666fa56b9027ce212209fb82872e9ee63df695c5` commit updates the audit record only; no code or test files changed after validation.

The incidental model backtest triggered before the workflow path exclusions were committed completed successfully in [run 43698454758](https://github.com/Baltas80/Kini-/actions/runs/43698454758). It used no changed model code or model inputs; it does not constitute a new model-performance result.

PR #9 is a draft targeting PR #8's identity branch. PR #7's SELAE importer remains a separate draft dependency and is not copied into this branch. The next data task is to source and validate Liga F historical identities and results for the three remaining women's fixtures, without borrowing men's identities or fabricating competition mappings. No full-coupon training-label export or model training join has been enabled; no PR has been merged and `master` remains untouched.


## Liga F official fixture evidence — 2026-11-15

A source-specific evidence layer has been added for the three played women's fixtures in the 8 November 2026 Quiniela coupon. This does **not** extend the Football-Data training dataset or alter forecasts.

- Separate registry: `kini_engine/data/ligaf_team_identity_registry.json`; six internal IDs, with exact provider-scoped aliases for Liga F and SELAE and gender fixed to `women`, competition `LIGA_F`, season `2026-27`.
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

These pages expose match-result links; the match-detail pages expose stable Liga F match IDs and kickoff details. This is a viable primary-source candidate for a multi-season Liga F dataset. It has **not** yet been bulk-downloaded, parsed, reconciled across seasons, or admitted to model training. The next implementation unit is to inspect the official page markup/data endpoint, create a rate-limited and cacheable importer with saved HTML fixtures, validate expected match counts and duplicates per season, and retain all source URLs and match IDs. Team promotion/relegation, club renames and historical identity changes must be represented by season-scoped aliases rather than current-team assumptions.

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

Implementation: **committed to `feat/selae-fixture-reconciliation`**. CI run 43704125275 passed: Ruff lint and 118 tests. Live bulk ingestion is still running and is not yet validated. The next action is to inspect CI results, fix any parser/test regressions, then run the manual workflow from a supported GitHub Actions environment. If the official host blocks GitHub runners, retain the fail-closed result and use the same CLI with official HTML captured from an accessible Spain-based environment; do not fabricate or relax source checks.


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

The validated Liga F profile is being extended to expose the exact observed team names separately for each season. Commit `1a45b825ba2fec351024e6d64c36b7eda84c8f94` adds the inventory to each season profile: observed display strings, scheduled and played appearances, home/away played counts, and first/last played kickoff in UTC. Grouping uses only the existing case-fold/whitespace normalization; accents and punctuation remain significant, so this report does not infer renamed-club aliases or canonical IDs.

Regression tests in `dac9edee68edfda3f88af807fd05eb81bdac6c4d` assert 16 team profiles and 30/15/15 appearance counts for a complete season, and explicitly keep `Málaga` distinct from `Malaga`. The regenerated live import [43713031093](https://github.com/Baltas80/Kini-/actions/runs/43713031093) passed; its artifact profile reports 16 exact team labels in each of the five season ranges. The current-season inventory is `Athletic Club`, `Atlético de Madrid`, `Costa Adeje Tenerife`, `Deportivo Abanca`, `Deportivo Alavés`, `FC Badalona Women`, `FC Barcelona`, `Granada CF`, `Logroño United`, `Madrid CFF`, `RCD Espanyol`, `Real Madrid CF`, `Real Sociedad`, `SD Eibar`, `Sevilla FC`, and `VCF Femenino`. Consecutive-season set differences are recorded as entrants/exits only; they are not treated as proof of club renaming or continuity.

The current-season identity registry was expanded to 16 official Liga F labels in commit `431a12df8a38d86a8f372eeeeb7f870a7808a4ff`; six retain the verified SELAE aliases. `data/ligaf_team_profile_crosswalk.json` (commit `201bbfcbee843fa294d15dbed70cf35cf476a676`) records 16 official team profile IDs/URLs and one official match-detail evidence URL per team. Tests in `5fb7ad5b425b7c27c9f90086a0ba94b6b3f8c059` validate exact registry resolution, unique provider IDs and official source URLs. CI found one formatting-only failure in the long assertion; it was corrected in `8217f8166c02aa310e0758f611078db66f4fcc88`. Historical-data validation [43713637624](https://github.com/Baltas80/Kini-/actions/runs/43713637624) passed after the crosswalk was added. The implementation/test head passed in [43713913706](https://github.com/Baltas80/Kini-/actions/runs/43713913706); a subsequent audit-only commit also passed [43714148651](https://github.com/Baltas80/Kini-/actions/runs/43714148651). Both CI runs completed Ruff, formatting and pytest successfully (121 tests, four upstream deprecation warnings).

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
