# Kini-

Motor de predicción de La Quiniela española.

## Arquitectura

La columna vertebral es **KinielaGPT**: probabilidades LAE, forma reciente, H2H, clasificación/contexto, detección de divergencias y estrategias. Encima incorporamos componentes maduros, preferentemente como dependencias y no copiando código:

- Dixon-Coles y grids de marcador mediante la familia de modelos de penaltyblog.
- XGBoost opcional + fallback scikit-learn.
- Backtesting walk-forward sin información futura.
- Optimización de dobles/triples bajo presupuesto.
- Adaptadores de datos KinielaGPT/Quinielista y SELAE.
- SQLite, FastAPI y MCP como capas opcionales.

## Instalación

```bash
python -m pip install -e ".[all]"
pytest -q
```

## Backtest

```bash
python -m kini_engine.cli backtest data/matches.csv --min-train 300
```

## Licencia y procedencia

El proyecto es **AGPL-3.0-or-later**. KinielaGPT también es AGPL-3.0-or-later; penaltyblog es MIT, scikit-learn BSD-3-Clause, XGBoost Apache-2.0 y Optuna MIT. Ver `NOTICE.md`.

No se incorpora código de repositorios para los que no se pudo verificar una licencia compatible.

## Fase 2.1 — Instante de información

Cada predicción prepartido debe declarar explícitamente `information_at`: el instante exacto, en UTC, hasta el que el modelo puede considerar información.

El contrato temporal exige:

- `information_at` debe ser timezone-aware y se normaliza a UTC.
- `information_at` debe ser estrictamente anterior al kickoff del partido objetivo.
- El resultado de una predicción conserva `information_at` y `target_kickoff_at` para reproducibilidad y auditoría.
- El motor rechaza una predicción si el histórico con el que fue ajustado contiene un partido con kickoff igual o posterior a `information_at`.
- El instante de información es el límite temporal; la enumeración y congelación de snapshots de fuentes se implementa en la siguiente etapa de causalidad temporal.

La API y MCP requieren ahora `kickoff_at` e `information_at` al solicitar una predicción.

## Fase 2.3 — Regla anti-leakage

La única regla de causalidad del motor es:

> Un dato solo puede entrar en una predicción si su `availability_at <= information_at`.

Las excepciones son los eventos históricos usados como resultado/modelo de entrenamiento: su instante de evento debe ser estrictamente anterior a `information_at`, porque un evento que ocurre exactamente en el corte todavía no puede considerarse históricamente consumado para una predicción prepartido.

La comprobación está centralizada en `kini_engine/causality.py`. Las rutas de predicción y backtesting no implementan reglas temporales alternativas.

Un dato que cruza la frontera provoca `CausalityViolation`; no se sustituye silenciosamente, no se recorta y no se utiliza como fallback.

## Fase 3 — Baselines

Antes de comparar modelos sofisticados, Kini dispone de tres referencias probabilísticas auditables:

- **uniforme:** `1/X/2 = 1/3`;
- **prior histórico expansivo:** frecuencia acumulada con suavizado de Laplace;
- **prior reciente:** frecuencia de las últimas `N` observaciones causales, también con suavizado de Laplace.

Las referencias se evalúan mediante walk-forward y exactamente el mismo corte temporal que se utilizará para los modelos avanzados. `baseline_suite` exige `information_at` y vuelve a validar la causalidad del histórico.

El prior histórico expansivo es la referencia principal para determinar si un modelo complejo aporta señal adicional sobre una estrategia que solo conoce la distribución histórica de resultados.
