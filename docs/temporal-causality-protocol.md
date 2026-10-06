# Protocolo temporal certificado

## 1. Objetivo

Este protocolo verifica que el motor Kini no puede entrenar, predecir ni reconstruir un snapshot utilizando información que no estaba disponible en el instante declarado como `information_at`.

El protocolo no busca demostrar únicamente que una función filtra fechas. Introduce deliberadamente datos futuros en las rutas críticas y comprueba que:

1. la frontera temporal los bloquea;
2. una predicción contaminada se aborta antes de ejecutar el modelo;
3. un snapshot contaminado por observaciones futuras es idéntico al snapshot limpio;
4. los eventos históricos tienen una regla más estricta que las observaciones de fuentes.

## 2. Regla normativa

Para cualquier dato de fuente:

`availability_at <= information_at`

Para eventos históricos utilizados como conocimiento consumado del entrenamiento:

`event_at < information_at`

Una violación debe producir `CausalityViolation`. No se permite corregirla silenciosamente, sustituir el dato, truncar la historia ni generar una predicción alternativa.

El objetivo siempre debe cumplir:

`information_at < target_kickoff_at`

## 3. Pruebas de ataque temporal

| ID | Inyección deliberada | Resultado obligatorio |
| --- | --- | --- |
| TC-01 | Observación de fuente exactamente en el corte | Aceptada |
| TC-02 | Observación de fuente posterior al corte | Rechazada por la regla causal |
| TC-03 | Partido histórico con kickoff exactamente en el corte | Rechazado |
| TC-04 | Histórico con un partido futuro mezclado con datos válidos | Rechazado completo |
| TC-05 | Histórico futuro inyectado en una predicción | `CausalityViolation` antes de `_predict_one` |
| TC-06 | Snapshot limpio frente a snapshot con observación futura | Ambos snapshots deben ser idénticos |
| TC-07 | Partido canónico no terminado usado como histórico | Rechazado |

## 4. Evidencia automatizada

Las pruebas están en:

`tests/test_causality.py`

La implementación normativa está en:

`kini_engine/causality.py`

La congelación temporal de fuentes está en:

`kini_engine/snapshots.py`

El backtesting aplica la misma regla central antes de cada ajuste en:

`kini_engine/backtest.py`

## 5. Criterios de certificación

El protocolo se considera certificado únicamente cuando, en GitHub Actions sobre el commit que contiene estas pruebas:

- `python -m pytest -q` termina con resultado `success`;
- la validación del dataset histórico termina con resultado `success`;
- no existe un fallo de pruebas oculto por `xfail`, filtros o ejecución parcial.

La certificación es reproducible ejecutando desde la raíz del repositorio:

```bash
python -m pytest -q
python scripts/validate_dataset.py data/historical/releases/demo-v1/matches.csv \
  --observations data/historical/releases/demo-v1/observations.jsonl \
  --known-teams tests/fixtures/known_teams.json \
  --expected-rounds tests/fixtures/expected_rounds.json \
  --as-of 2025-01-12T23:59:59Z
```

## 6. Alcance de la certificación

La certificación demuestra la barrera temporal del núcleo actual. No certifica todavía que todos los proveedores externos expongan `captured_at` correctamente ni que todos los campos dinámicos de dominio estén integrados en snapshots; esas integraciones deberán someterse al mismo protocolo cuando se incorporen.

Cualquier nueva fuente, feature, modelo o ruta de predicción que introduzca información temporal debe añadir un caso negativo al protocolo antes de considerarse apto para producción.

## 7. Estado

**CERTIFICACIÓN PENDIENTE DE CI PARA ESTE COMMIT.**

La marca de certificación solo se puede elevar a **CERTIFICADO** después de una ejecución verde de CI que ejecute la batería completa y la validación histórica indicadas arriba.
