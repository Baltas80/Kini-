# Ingesta de escrutinios oficiales de La Quiniela (SELAE)

**Estado:** parser e importador implementados; pruebas deterministas en CI. La descarga directa desde GitHub-hosted runners está bloqueada por HTTP 403 y no se considera validada en ese entorno.

## Fuente y alcance

El importador consulta páginas públicas de escrutinio de SELAE con una URL determinista por fecha:

`https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/la-quiniela-premios-y-ganadores-del-DD-de-MES-de-AAAA`

La página oficial de cada jornada publica los 14 encuentros, equipos, marcadores y signos 1/X/2, el Pleno al 15 y el desglose de categorías de premios. Se ha comprobado, entre otras, la página del 8 de noviembre de 2026:

- https://www.loteriasyapuestas.es/es/la-quiniela/escrutinios/la-quiniela-premios-y-ganadores-del-08-de-noviembre-de-2026
- https://www.loteriasyapuestas.es/es/la-quiniela/resultados
- Calendario provisional de jornadas 2026/2027: https://www.loteriasyapuestas.es/f/loterias/web_corporativa/Comunicacion/Avisos_de_interes/Calendario%20Provisional%20AD%20Tda%202026-2027.pdf

No se ha identificado ni se presupone una API pública estable de SELAE. El importador consume HTML de páginas oficiales y, por tanto, depende de una estructura web que puede cambiar. Un workflow separado ejecuta una prueba de integración contra el escrutinio real del 8 de noviembre de 2026. Si la página cambia, la validación debe fallar; no se aceptan registros parciales.

## Uso

Indicar fechas de sorteo explícitas evita rastrear días sin jornada y evita generar peticiones masivas:

```powershell
python scripts/import_selae_results.py --dates 2026-11-08 2026-11-01
```

También se puede usar un archivo UTF-8 con una fecha ISO por línea:

```powershell
python scripts/import_selae_results.py --date-file data/selae_draw_dates.txt --refresh
```

Por defecto se generan:

- `data/selae_quiniela_draws.jsonl`: un registro JSON por sorteo.
- `data/selae_quiniela_draws.profile.json`: perfil de procedencia e integridad.
- `.cache/selae-quiniela/`: HTML original y metadatos de recuperación por fecha.

El caché se valida de nuevo antes de reutilizarse. Las respuestas se guardan atómicamente y se calcula SHA-256 del contenido recibido. Tanto la descarga como el modo offline validan que la URL de procedencia pertenezca al dominio oficial SELAE. Se permiten reintentos acotados para fallos transitorios; una respuesta que no pase la validación no sustituye una caché válida.

## Contrato de datos

Cada sorteo incluye:

- Fecha del sorteo, URL de origen, hora de recuperación UTC y SHA-256 del contenido bruto.
- Exactamente 14 partidos con posición, nombres de local/visitante, marcador y signo.
- Marcadores numéricos no negativos y comprobación de que el signo coincide con el marcador.
- Marcadores Pleno al 15; admite marcadores no numéricos como `M - M` y deja los goles como `null`.
- Categorías de premio, acertantes y premio unitario en céntimos de euro cuando aparecen en la tabla oficial; las categorías con BOTE se conservan con importe unitario `null` y estado `bote`.

Los sufijos `(M)` y `(F)` se conservan como marcadores de categoría publicados por SELAE. No se transforman en una competición concreta ni en un ID canónico de equipo.

## Límites que no deben ocultarse

1. **La fecha del sorteo no es la fecha de inicio de los partidos.** El escrutinio consultado no acredita el día/hora de inicio individual. Por ello `kickoff_date` y `kickoff_time` quedan a `null`; no se debe usar `draw_date` como fecha del partido.
2. **No se obtiene un ID de sorteo verificable desde el contenido importado.** `draw_id` permanece a `null` hasta que exista un identificador oficial recuperable y validado.
3. **Los marcadores y signos son resultados observados.** Son etiquetas objetivo y nunca deben entrar como variables predictoras prepartido.
4. **(M)/(F) no identifica por sí solo liga, competición, temporada ni categoría completa.** Se requiere un registro de equipos y una fuente de fixtures con fechas para resolver la identidad.
5. **Los premios unitarios y acertantes no reconstruyen el valor esperado.** Faltan datos completos de recaudación/pools, reparto por categoría, botes, número y tipo de apuestas, reglas aplicables a cada jornada y, cuando corresponda, datos de sistemas reducidos/condicionados.
6. **No se afirma que exista un archivo histórico íntegro y paginable.** Las fechas se suministran explícitamente desde calendarios o fuentes verificadas. La página de resultados muestra jornadas recientes, pero no se ha validado un contrato de archivo histórico completo.

En consecuencia, este importador crea una fuente canónica de composición y resultados de cupones, pero **no habilita todavía un backtest prepartido completo de todos los encuentros**. Antes de entrenar con estos partidos deben resolverse fechas reales de juego, competición y equipo mediante fuentes independientes y un emparejamiento inequívoco. Los casos ambiguos deben permanecer sin resolver, no inferirse por proximidad de fechas.

## Reproducibilidad y validación

Pruebas deterministas: `pytest -q tests/test_import_selae_results.py`.

Prueba de fuente real: el workflow `selae-coupon-source-validation` intenta importar el sorteo 2026-11-08, pero la infraestructura de GitHub Actions recibe HTTP 403 del dominio SELAE en la página de escrutinio, el HTML estático de resultados, el RSS, el índice de resultados y el PDF oficial de prensa. Ese paso es no bloqueante para que una restricción geográfica externa no oculte fallos del parser; **un 403 no equivale a validación de la fuente**. La descarga debe ejecutarse desde un entorno en España con acceso legítimo al sitio o se deben guardar las páginas HTML oficiales y procesarlas con `--html-dir`.

La integración en el flujo de modelos queda pendiente de una fase separada de identidad de equipos/competiciones y fechas de inicio.

## Uso de marca y datos

El proyecto conserva enlaces de procedencia y no incorpora logotipos ni elementos gráficos de SELAE. El uso de marcas, distintivos o materiales protegidos debe respetar el aviso legal y las condiciones de SELAE; la existencia de una página pública no equivale a una licencia general de reutilización.


## Ejecución desde España o importación offline

Si el acceso HTTP desde la máquina de trabajo está permitido, se puede ejecutar directamente:

```powershell
python scripts/import_selae_results.py --dates 2026-11-08 --refresh
```

Si el HTML se ha guardado manualmente desde la página oficial, nombrar los archivos por fecha ISO (`2026-11-08.html`) y ejecutar:

```powershell
python scripts/import_selae_results.py --dates 2026-11-08 --html-dir .\data\selae-html
```

El importador combina las nuevas fechas con el JSONL existente. Repetir la misma importación (mismo SHA-256) es idempotente. Si SELAE corrige una página ya importada y cambia su SHA-256, el proceso se detiene; solo se sustituye el registro después de revisar el cambio y pasar `--replace-existing`.

## Fuentes secundarias evaluadas

Se ha revisado una web independiente que publica fechas de partido, resultados y premios, y se han contrastado manualmente tres jornadas recientes con páginas/PDF oficiales de SELAE. No se incorpora como proveedor automatizado: su aviso legal declara que no es fuente oficial, no se ha identificado una licencia explícita de reutilización y su `robots.txt` excluye expresamente los agentes de IA. No se automatiza su extracción ni se usa para alimentar el modelo. La procedencia primaria del dataset de cupones seguirá siendo SELAE.
