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

## Identidad canónica de equipos

El registro de identidades por proveedor está en `kini_engine/data/team_identity_registry.json`. Solo resuelve alias exactos y documentados por fuente, competición y temporada; no utiliza coincidencias aproximadas.

    python -m scripts.validate_team_identity_registry --csv data/historical_spain.csv

Los cruces masculinos SELAE/Football-Data se limitan a las diez asociaciones exactas documentadas en el manifiesto. Los tres encuentros femeninos del cupón tienen evidencias oficiales independientes de Liga F, pero no se incorporan a Football-Data ni al entrenamiento. La reconciliación de cupones exige un crosswalk por partido con nombres exactos, competición, temporada, kickoff con zona horaria y evidencia independiente:

```bash
python -m scripts.reconcile_selae_fixtures \
  --draws data/selae_quiniela_draws.jsonl \
  --crosswalk data/selae_fixture_crosswalk.json \
  --historical data/historical_spain.csv \
  --output data/selae_fixture_reconciliation.json
```

El manifiesto `data/selae_fixture_crosswalk.json` contiene diez asociaciones verificadas con horarios oficiales y coincidencia exacta en Football-Data. Los tres encuentros femeninos se conservan en `data/ligaf_fixture_evidence.json` y siguen fuera del crosswalk masculino. Para ejecutar la reconciliación, primero genera `data/historical_spain.csv` con `python scripts/build_history.py` y pasa `--historical data/historical_spain.csv`. Los partidos no disputados con signo por sorteo público se excluyen de las etiquetas futbolísticas; los encuentros aún no reconciliados bloquean la exportación de etiquetas. Véanse `docs/TEAM_IDENTITY.md` y `docs/SELAE_RECONCILIATION.md`.


## Histórico oficial de Liga F (evidence-only)

El importador \`scripts/import_ligaf_history.py\` descarga las páginas oficiales de resultados por jornada y los detalles de cada encuentro. Por defecto cubre las temporadas 2022/23 a 2025/26 completas y las jornadas 1–10 de 2026/27:

\`\`\`bash
python scripts/import_ligaf_history.py
\`\`\`

El resultado se escribe en \`data/ligaf_history.jsonl\` y su perfil de integridad en \`data/ligaf_history.profile.json\`; ambos son artefactos locales ignorados por Git. Las páginas HTML originales y sus hashes se conservan en \`.cache/ligaf\`. Se puede usar \`--refresh\` para renovar la caché o \`--offline\` para reconstruir el resultado solo con fuentes previamente almacenadas.

El importador exige ocho encuentros por jornada, identificadores oficiales únicos, fechas del partido coincidentes con la sección de resultados de la jornada, marcador y signo coherentes y, para temporadas completas, 240 partidos, 16 equipos y 15 encuentros como local y visitante por equipo. Los títulos de algunas fichas históricas muestran un año estático incorrecto; por eso el año de temporada se toma de la ruta oficial del archivo y la fecha del encabezado de la ficha se contrasta con las fechas de la jornada.

**Límite de entrenamiento:** todos los registros llevan \`training_label_eligible=false\`. Todavía faltan el registro de identidades históricas por temporada, la auditoría completa de cambios de nombre/ascensos/descensos y una validación temporal de las variables prepartido. Este importador no modifica \`historical_spain.csv\`, los modelos ni las predicciones. Véase \`docs/SELAE_RECONCILIATION.md\`.

## Licencia y procedencia

El proyecto es **AGPL-3.0-or-later**. KinielaGPT también es AGPL-3.0-or-later; penaltyblog es MIT, scikit-learn BSD-3-Clause, XGBoost Apache-2.0 y Optuna MIT. Ver `NOTICE.md`.

No se incorpora código de repositorios para los que no se pudo verificar una licencia compatible.
