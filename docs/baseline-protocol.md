# Fase 3 — Protocolo de Baselines

## Objetivo

Antes de comparar Dixon-Coles, aprendizaje automático, ensemble o cualquier módulo contextual, Kini debe superar referencias simples y completamente auditables.

## Referencias

### Uniforme

`1/X/2 = 1/3`.

No aprende nada. Es la referencia neutral para una distribución sin información específica.

### Prior histórico expansivo

Calcula la frecuencia acumulada de `1/X/2` en el histórico disponible hasta el corte. Usa suavizado de Laplace `alpha=1` para mantener las tres probabilidades estrictamente positivas y hacer comparable el log-loss.

### Prior reciente

Calcula la misma frecuencia, pero únicamente sobre las últimas `window` observaciones del histórico causal. Por defecto, `window=50` y `alpha=1`.

## Protocolo

Para cada partido objetivo:

1. ordenar cronológicamente;
2. definir `information_at = target_kickoff - 1 microsecond`;
3. usar exclusivamente `history[:i]`;
4. validar ese histórico con la regla central anti-leakage;
5. ajustar cada baseline únicamente con ese prefijo;
6. predecir;
7. registrar el resultado real y las métricas.

La función `baseline_suite` exige explícitamente `information_at` y vuelve a comprobar el histórico causal. Así se evita que una llamada directa pueda convertir accidentalmente una historia completa en entrada de evaluación.

No se permite reutilizar el histórico completo ni acceder al resultado del partido objetivo durante la construcción de la predicción.

## Métricas

Cada baseline se evalúa con el mismo conjunto básico actual:

- `accuracy`
- `brier`
- `logloss`

Una evaluación vacía produce error explícito. No se presentan ceros como si fueran resultados válidos.

## Uso

Desde Python:

```python
from kini_engine.backtest import baseline_walk_forward

result = baseline_walk_forward(
    matches,
    min_train=80,
    recent_window=50,
    alpha=1.0,
)
print(result["metrics"])
```

La salida contiene la configuración del protocolo, el número de filas de prueba y las métricas por baseline.

## Interpretación

El prior histórico expansivo es la referencia principal para la primera comparación probabilística. El baseline reciente sirve para comprobar si una simple adaptación temporal ya explica parte de la señal que pretende capturar un modelo más complejo.

Ningún modelo avanzado debe declararse superior basándose solo en accuracy. La comparación deberá considerar conjuntamente log-loss y Brier, y posteriormente las métricas de calibración de la fase de evaluación avanzada.

## Datos de demostración

`data/historical/releases/demo-v1` contiene únicamente 12 partidos sintéticos. Sirve para validar contratos, reproducibilidad y tests, pero no para afirmar superioridad estadística de un modelo.

Los benchmarks de rendimiento deben ejecutarse sobre un histórico real suficientemente amplio y sometido previamente a los controles de Fases 1 y 2.

## Criterio de paso

Fase 3 queda lista cuando:

- las tres referencias funcionan;
- el walk-forward de baselines es estrictamente causal;
- una inyección futura produce una violación causal;
- el conjunto de métricas no admite una evaluación vacía;
- CI ejecuta toda la batería y la validación histórica correctamente.

Estado: **PENDIENTE DE CI**.
