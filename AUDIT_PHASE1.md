# Phase 1 audit — data integrity, temporal validation and model comparison

Date: 2026-11-15  
Repository: Baltas80/Kini-  
Working branch: `audit/phase-1-temporal-validation`  
Base branch: `master`  
Backtest code commit evaluated: `fbffca8b1600346ca728e19f010ab3f61f35f198`  
Latest fully validated baseline: `2963e7dcbc3f0aca6680011e9c347367c79af44e`  
Latest code HEAD: `3fff53c52d4b60efe851eba18d9bd4e85a463f88` (44 tests and historical-data validation passed; calibrated historical backtest pending)

## Executive status

- **P0 backtesting:** validated. Dixon-Coles, ML, the market-assisted ensemble, fixed DC/ML-only ensemble and adaptive DC/ML-only ensemble each generated 5,011/5,011 predictions with zero prediction errors.
- **P1 historical ingestion:** validated on 5,311 completed matches, with the integrity profile passing.
- **P2 temporal validation:** same-calendar-day exclusion, date-based refit cadence and strictly pre-match ML feature history are implemented and tested.
- **P6 ticket optimizer:** probability validation, budget constraints, exhaustive small-budget DP comparison, minimum stake and Pleno al 15 aggregation are implemented and CI-tested.
- **Predictive performance:** the market remains materially better than every model configuration on accuracy, Brier and Log Loss.
- **Ensemble weighting:** fixed and rolling prequential DC/ML-only comparisons are now evaluated. The adaptive variant did not improve Brier or Log Loss over the fixed DC/ML blend and is not selected as the default.
- **Calibration diagnostics:** one-vs-rest reliability, prevalence, mean predicted probability, binary Brier/Log Loss and ECE by 1/X/2 class and football season are implemented on out-of-sample forecasts.
- **Prequential calibration experiment:** a regularized multinomial vector-bias/shared-scale calibrator is implemented for every model and the market. It is fitted only on prior OOF forecasts, with a 500-row warm-up, 1,500-row rolling window, minimum 20 observations per class and refits every 30 forecast dates. Same-day outcomes are appended only after the entire date has been forecast. Its full backtest evaluation is pending; it is not selected as a production default.
- **Not complete:** timestamped odds provenance, canonical team identity, correlation-aware ticket coverage and expected-payout modelling.

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

GitHub Actions run: [43641695219](https://github.com/Baltas80/Kini-/actions/runs/43641695219)  
Code commit evaluated: `fbffca8b1600346ca728e19f010ab3f61f35f198`

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
| Market | **0.5085** | **0.5980** | **1.0002** | **0.2002** | 0.0261 |

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

El workflow histórico rechaza muestras calibradas vacías, tamaños distintos entre muestras originales y calibradas, calibradores sin ajuste válido o comparaciones comunes con el mercado inexistentes. La aceptación comprueba que el experimento se ejecutó; no exige que mejore las métricas. Solo se promoverá si reduce Brier y Log Loss fuera de muestra sobre la misma muestra temporal. El resultado del backtest completo sigue pendiente.

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

- The market outperforms every model configuration on accuracy, Brier and Log Loss.
- The market-assisted ensemble is marginally better than Dixon-Coles on Brier and Log Loss, but not accuracy; this does not establish a meaningful predictive advantage.
- ML remains materially weaker than Dixon-Coles and market.
- The fixed model-only DC/ML blend slightly improves Brier and Log Loss relative to Dixon-Coles but has lower accuracy.
- The adaptive DC/ML blend has slightly higher accuracy than the fixed model-only blend, but worse Brier and Log Loss. Its ECE is lower, but ECE alone is insufficient to claim better calibration. The adaptive method is retained as an experiment, not selected as the production default.
- No result establishes that model probabilities are profitable or that they outperform market prices at an executable betting cutoff.

Football-Data odds columns do not carry a capture timestamp. Their exact availability at an operational betting cutoff is not established; the market comparison is a historical benchmark, not proof of executable prices at a specified time.

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

Baseline validado: `2963e7dcbc3f0aca6680011e9c347367c79af44e`. Último HEAD: `3fff53c52d4b60efe851eba18d9bd4e85a463f88`.

- [CI del último HEAD — 44 tests superados](https://github.com/Baltas80/Kini-/actions/runs/43652728930). Permanecen cuatro advertencias deprecatorias de `penaltyblog` 1.13.1 al asignar la forma de un array bajo NumPy 2.5.
- [Validación histórica del último HEAD](https://github.com/Baltas80/Kini-/actions/runs/43652728953): 5.311 partidos, `integrity_passed: true`, cero duplicados; LaLiga 2026/27: 119 partidos y Segunda 2026/27: 140.
- [Backtest histórico anterior](https://github.com/Baltas80/Kini-/actions/runs/43642060879): 5.011 predicciones para cada una de las cinco configuraciones, cero errores y `BACKTEST_ACCEPTANCE_OK`. El backtest del nuevo calibrador está pendiente de confirmación.

El constructor de la ingesta consolida el DataFrame normalizado antes de añadir `_ParsedDate` y concatena `League`, `Season` y `SourceURL` como un único bloque de metadatos. CI detectó que el primer intento había comentado accidentalmente la asignación de la fecha parseada; el commit `2963e7d` la restauró. La implementación corregida conserva las 5.311 filas y elimina los avisos de fragmentación de pandas.

## Remaining work — priority order

1. **Calibration correction:** evaluate the new prequential vector-bias/shared-scale calibrator against raw forecasts on its identical post-warm-up sample. Promote it only if Brier and Log Loss improve on the same chronological evaluation; otherwise retain raw probabilities and document the result.
2. **Odds provenance:** establish a usable pre-match cutoff or explicitly constrain the market benchmark to the available Football-Data semantics. Do not describe closing odds as executable at an earlier cutoff.
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
8. Fixed and adaptive independent model-only ensembles — **implemented and validated on 5,011 walk-forward fixtures**; adaptive weighting did not improve Brier or Log Loss over the fixed blend. Class-wise and seasonal one-vs-rest diagnostics — **implemented and validated on 5,011 OOF fixtures**. Prequential calibrator — **implemented with same-day isolation and acceptance checks; full backtest result pending**. Timestamped odds and expected-payout model — **pending**.

## Integration status

- PR #5 (resilient ingestion): [open](https://github.com/Baltas80/Kini-/pull/5).
- PR #6 (temporal validation and models): [open, draft](https://github.com/Baltas80/Kini-/pull/6).
- PR #6 branch includes PR #5 as the second parent of the merge commit. For the cleanest eventual integration, merge PR #5 first and then PR #6.
- No PR has been merged.
- `master` remains at `ef331c3a3f50220b5d2b1a71900a2d7003b259c4` and has not been modified.
