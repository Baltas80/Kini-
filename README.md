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
