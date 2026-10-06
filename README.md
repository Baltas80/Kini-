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


## 0.3 — estabilización y evaluación

La versión 0.3 incorpora:

- **Elo causal** como modelo estadístico independiente para comparación y futura combinación.
- **Optimizador DP exacto** para presupuestos de columnas, con estados definidos por el número de columnas generadas.
- **Walk-forward estricto**: cada predicción utiliza únicamente partidos anteriores.
- Métricas **Brier, log loss, RPS y ECE**.
- Benchmark causal contra frecuencia histórica.
- CLI: `kini benchmark data/matches.csv`.
- Pruebas de regresión para optimización, Elo y métricas de calibración.

Los pesos actuales del ensemble siguen siendo provisionales. Ningún modelo se considera superior hasta demostrar mejora fuera de muestra.

### Próximo bloque

1. dataset histórico normalizado;
2. validación de fuentes y nombres de equipos;
3. calibración temporal de probabilidades;
4. benchmark Elo / Poisson / Dixon-Coles / ML / ensemble;
5. aprendizaje de pesos del ensemble;
6. optimización matemática de la cartera de columnas.
