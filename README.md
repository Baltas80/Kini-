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
python -m kini_engine.cli compare data/historical_spain.csv --min-train 300
```

Para validación histórica seria, `scripts/build_history.py` descarga temporadas de Primera y Segunda desde Football-Data y genera `data/historical_spain.csv` (por defecto, desde 2020/21 hasta la temporada actual). La ingesta aplica reintentos HTTP acotados, valida esquema/fechas/marcadores y comprueba que la columna `Div` coincida con la liga solicitada (para no aceptar redirecciones a otra división), mantiene una caché independiente por CSV en `.cache/football-data` durante 24 horas y usa la última caché válida si la fuente falla. Tanto la caché como el CSV final se escriben mediante reemplazo atómico; el histórico final se ordena cronológicamente y elimina duplicados por liga, temporada, fecha y equipos. El workflow histórico restaura y guarda la caché entre ejecuciones. Una ejecución correcta del workflow publica `data/historical_spain.csv` junto a los resultados como artefacto descargable; tras fusionar esta PR, se puede lanzar manualmente desde GitHub Actions. Usa `python scripts/build_history.py --refresh` para forzar un intento de actualización, `--seasons 2526 2627` para seleccionar temporadas o `--leagues la-liga` para limitar las ligas. El proyecto no incorpora los CSV en el repositorio: son datos externos y sus condiciones de uso deben respetarse según su fuente.

El backtest informa `accuracy`, `brier`, `logloss`, `rps` y `ece`. `compare` enfrenta Dixon-Coles, ML, ensemble y mercado bajo exactamente las mismas divisiones temporales. La métrica principal para comparar modelos debe ser probabilística (log-loss/Brier/RPS), no únicamente el porcentaje de signos acertados.

## Licencia y procedencia

El proyecto es **AGPL-3.0-or-later**. KinielaGPT también es AGPL-3.0-or-later; penaltyblog es MIT, scikit-learn BSD-3-Clause, XGBoost Apache-2.0 y Optuna MIT. Ver `NOTICE.md`.

No se incorpora código de repositorios para los que no se pudo verificar una licencia compatible.
