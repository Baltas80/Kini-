# Histórico reproducible de Kini

Esta carpeta define el formato versionable del histórico. Cada release de datos es inmutable: una nueva extracción genera otro directorio y nunca modifica uno ya publicado.

## Estructura

data/historical/
  templates/
    matches.csv
    observations.jsonl
  releases/
    <dataset_id>/
      matches.csv
      observations.jsonl
      manifest.json

### matches.csv
Tabla canónica de eventos deportivos. Contiene identidad, tiempo, estado y resultado del partido.

### observations.jsonl
Una línea por observación/captura de una fuente. Conserva `source_id`, `captured_at`, `source_record_id` y `payload_hash` junto con el payload normalizado.

`payload_hash` es el SHA-256 del payload JSON canónico, serializado con claves ordenadas y separadores compactos. Así puede verificarse que el contenido observado no ha cambiado.

### manifest.json
Describe exactamente un release: versión del esquema, rango temporal, conteos y hashes SHA-256. No incluye su propio hash.

`generated_at` identifica cuándo se generó el release y no forma parte de los hashes de `matches.csv` ni `observations.jsonl`.

## Reglas

- Todos los timestamps se almacenan en UTC y en ISO-8601 con Z.
- Un release publicado no se sobrescribe.
- Las observaciones son append-only.
- `matches.csv` contiene eventos canónicos; la información que cambia con el tiempo pertenece a `observations.jsonl`.
- Las observaciones con estado `scheduled` deben capturarse antes del kickoff.
- La reproducción depende del contenido del release, su manifest y el commit de código indicado.
- El release demo incluido es un fixture sintético basado en los 12 partidos de prueba actuales. No se presenta como el histórico real de La Quiniela.

## Pipeline de validación

La validación estricta requiere una fecha de corte (as_of), el registro de equipos canónicos y la expectativa de partidos por jornada. El comando devuelve código 0 solo cuando no existen errores y genera un informe JSON opcional.

Los equipos se expresan como una lista de team_id en JSON:

```json
["team:A", "team:B", "team:C", "team:D"]
```

La expectativa de jornadas usa competitions -> temporada -> jornada -> número de partidos:

```json
{
  "competitions": {
    "competition_id": {
      "2024-25": {
        "1": 15
      }
    }
  }
}
```

Ejecución:

```text
python scripts/validate_dataset.py <matches.csv> --observations <observations.jsonl> --known-teams <known_teams.json> --expected-rounds <expected_rounds.json> --as-of <UTC_TIMESTAMP_Z> --report-out validation_report.json
```

El pipeline controla duplicados de identidad y fixture, partidos imposibles, puntuaciones y signos inválidos, coherencia temporal entre temporadas y jornadas, completitud de jornadas, equipos desconocidos y datos posteriores a as_of.

## Fase 2.2 — Snapshots temporales

Las observaciones de fuentes forman un historial de eventos. Para reconstruir qué conocía el sistema en un instante concreto se crea un `TemporalSnapshot`.

Reglas del snapshot:

- solo entran observaciones con `captured_at <= information_at`;
- para cada combinación `source_id + match_id` se selecciona la observación más reciente disponible;
- una observación futura nunca participa aunque esté presente en el release histórico;
- dos observaciones de la misma fuente, partido e instante de captura se consideran ambiguas y se rechazan;
- el snapshot se ordena de forma determinista y obtiene un `snapshot_id` SHA-256 derivado de su contenido y de `information_at`;
- el snapshot conserva el payload y su `payload_hash`, permitiendo auditar exactamente qué versión de una fuente quedó disponible.

Esto permite reconstruir el estado de las fuentes para un instante concreto sin modificar los releases inmutables.
