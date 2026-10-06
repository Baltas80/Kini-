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
