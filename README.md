# Kini-

Motor de predicción de La Quiniela española.

## Arquitectura

La columna vertebral es **KinielaGPT**: probabilidades LAE, forma reciente, H2H, clasificación/contexto, detección de divergencias y estrategias. Encima incorporamos componentes maduros, preferentemente como dependencias y no copiando código:

- Dixon-Coles y grids de marcador mediante `penaltyblog` como backend estadístico mantenido, incluyendo ponderación temporal y salidas de marcador/1X2.
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

El cargador acepta el formato histórico habitual de Football-Data/DataHub (`Date`, `HomeTeam`, `AwayTeam`, `FTHG`, `FTAG`, `FTR`) y normaliza H/D/A a 1/X/2 sin usar el resultado futuro como variable de entrada.

```bash
python scripts/build_history.py
python -m kini_engine.cli backtest data/historical_spain.csv --min-train 300
```

Para validación histórica seria, `scripts/build_history.py` descarga seis temporadas de Primera y Segunda directamente desde Football-Data y genera `data/historical_spain.csv`. El proyecto no incorpora esos CSV en el repositorio: son datos externos y sus condiciones de uso deben respetarse según su fuente.

El backtest informa `accuracy`, `brier`, `logloss`, `rps` y `ece`. La métrica principal para comparar modelos debe ser probabilística (log-loss/Brier/RPS), no únicamente el porcentaje de signos acertados.

## Licencia y procedencia

El proyecto es **AGPL-3.0-or-later**. KinielaGPT también es AGPL-3.0-or-later; penaltyblog es MIT, scikit-learn BSD-3-Clause, XGBoost Apache-2.0 y Optuna MIT. Ver `NOTICE.md`.

No se incorpora código de repositorios para los que no se pudo verificar una licencia compatible.
