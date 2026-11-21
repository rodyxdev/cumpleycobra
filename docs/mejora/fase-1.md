# Fase 1 del plan de mejora: base de producción (parte A, código)

Fecha: 21 de noviembre de 2026. Rama `mejora/fase-1`. **No se desplegó:** la cumbre es el 23 de noviembre y producción sigue con el puente de Cloud Run (`state.json` en Cloud Storage). Todo lo nuevo queda apagado por defecto (`STATE_BACKEND=json`).

## Qué se hizo

| Pieza | Archivos |
| --- | --- |
| Estado en Postgres con la misma interfaz que `StateStore` | `backend/storage/__init__.py`, `backend/storage/postgres.py`, `backend/storage/migrations/001_inicial.sql` |
| Candados entre instancias (por tarea y para el release del árbitro) | `PostgresStore.lock`, `PostgresStore.sync_lock`; `backend/main.py` (lifespan) |
| Retos SEP-10 en una tabla | `identidad.PgChallenges` (y `Challenges` separado en métodos de almacenamiento) |
| Sesión de documentos por petición | `StoreSessionMiddleware` en `backend/main.py` |
| `APP_MODE` (`local`, `demo`, `live`) | `backend/config.py` |
| Importar y exportar `state.json` ↔ Postgres | `backend/storage/transfer.py` (`python -m backend.storage.transfer`) |
| Hashes iguales a v2 | `backend/hashing.py`, `backend/tests/test_hashing_v2.py` |
| Un solo comando | `compose.yaml` (Postgres + API + frontend), `Makefile` |
| Tests contra Postgres real | `backend/tests/test_storage_postgres.py`, `backend/tests/conftest.py` (`CYC_TEST_DATABASE_URL`) |
| Documentación | `CLAUDE.md` (estado, variables, reglas), este reporte |

## Decisiones

- **Documento por entidad, no tablas normalizadas.** Cada tarea, perfil y propuesta es una fila con el mismo JSON que tenía `state.json`.
  - El backend no cambia de forma (lee, modifica, `save()`), la importación es directa y exportar devuelve el mismo archivo.
  - Normalizar se puede hacer después, con migraciones que solo suman.
- **`json` y no `jsonb`.** `jsonb` reordena las claves, y el backend depende del orden de inserción: por ejemplo, la última entrega aprobada de `task["codes"]`. Además, `jsonb` no acepta `\u0000` dentro de un texto, y `json` sí.
- **Candados sin reescribir los endpoints.**
  - Al entrar a `lock(clave)` se toma un `pg_advisory_lock` y los documentos ya leídos en la petición se recargan *en el mismo dict*.
  - Así, el patrón actual (leer la tarea, tomar el candado, modificarla) es correcto también con varias instancias.
  - Lo prueba `test_candado_entre_dos_instancias_no_pierde_escrituras`: dos stores con pools distintos agregan 10 envíos en paralelo a la misma tarea, y no se pierde ninguno.
- **Driver síncrono (psycopg 3 + pool).** Cada consulta tarda milisegundos, igual que escribir `state.json`, que también bloqueaba el event loop. Si la API llega a tener mucho tráfico, se cambia a psycopg asíncrono sin tocar la interfaz.
- **Siguen en memoria por instancia:** el límite de peticiones por IP, las cuotas diarias y la caché de lecturas del contrato. Con N instancias, la cuota diaria efectiva es N veces la configurada; mientras la API corra con una o dos instancias, es aceptable. Cloudflare puede poner un límite global.
- **Hashes.** Se queda `hashing.py`, con los mismos rechazos que v2. El test compara contra una copia fiel del codificador de v2 con 10 vectores (controles, NFC/NFD, emojis, ` `, anidados, extremos de enteros) y 6 casos de rechazo, y confirma que el `rules_hash` de la demo sigue siendo `391136734bc9…c4f79c96`.

## Desviaciones de CLAUDE.md

- Se reescribieron las partes que ya no eran ciertas: "sin bases de datos", "backend local en la demo" y la sección de estado. La API, el contrato, los tokens y el motor no cambiaron.
- `test_delivery_fx.py`: el test guardaba una referencia a la tarea y esperaba que se actualizara sola entre peticiones, cosa que solo pasa con el diccionario en memoria. Ahora vuelve a leer la tarea; la aserción es la misma.

## Comandos y salida real

```text
# Postgres de prueba (Docker Desktop)
$ docker run -d --name cyc-pg-test ... -p 55432:5432 postgres:17-alpine

# Suite completa con state.json
$ backend/.venv/Scripts/python -m pytest backend/tests -q
312 passed, 8 skipped

# Suite completa con Postgres
$ CYC_TEST_DATABASE_URL=postgresql://cyc:…@localhost:55432/cyc_test backend/.venv/Scripts/python -m pytest backend/tests -q
320 passed            # incluye los 8 de test_storage_postgres.py
```

**Recorrido real contra `docker compose`** (Postgres + la imagen de la API, Gemini por Vertex con las credenciales ADC montadas, Stellar testnet):

1. `scripts/tarea_respaldo.py` creó la tarea `VmY6iX03ZdT0E1ES` y depositó 1 USDC: tx `d617fef085a19b9090d3bef063a2960819de18414c5e47b988bfdd1cec45776c`.
2. `cyc-freelancer` aceptó la tarea y envió el caso A: aprobado (`stage: llm`) en 10.7 s, y el release pagó con la tx `1d5633bc0083359b366d49783c9103ec3a1f23ba6fbaf64c9132dcd71308524b`.
3. `docker compose restart api` y luego `GET /tasks/{id}/verdicts`: el veredicto con su transacción sigue ahí. El contrato reporta `Released`. La tabla `tasks` tiene 1 fila y `schema_migrations` tiene `001_inicial`.

## Parte B: Cloud SQL y staging (21 de noviembre de 2026, hecho)

Producción no se tocó: `cumpleycobra-api` sigue con el puente de Cloud Storage.

| Recurso | Configuración |
| --- | --- |
| Cloud SQL `cyc-pg` | Postgres 17, Enterprise, `db-f1-micro`, 10 GB SSD con crecimiento automático. Respaldo diario a las 08:00 UTC (se guardan 7) y recuperación a un punto en el tiempo (7 días de bitácora). IP pública **sin redes autorizadas** y `ssl-mode=ENCRYPTED_ONLY`: solo se entra por el conector de Cloud SQL, con IAM y TLS. Base `cyc` y usuario `cyc_api` |
| Secreto `cyc-database-url` | URL con socket `/cloudsql/<conexión>`; la contraseña se generó al azar y nunca se imprimió |
| Cuenta `cyc-api` | Se agregó `roles/cloudsql.client` y acceso al secreto |
| Imagen | `cumpleycobra/api:feb8cd2` (rama `mejora/fase-1`) |
| Servicio `cumpleycobra-api-staging` | `https://cumpleycobra-api-staging-1017372721585.us-central1.run.app`; `STATE_BACKEND=postgres`, `APP_MODE=demo`, de 0 a 2 instancias, Cloud SQL por conector |
| Job `cyc-estado` | La misma imagen; monta el bucket de producción **solo lectura** en `/prod` y corre `python -m backend.storage.transfer` (importar, contar o exportar) |

### Salida real

1. **Migraciones:** al arrancar, staging aplicó `001_inicial` en Cloud SQL (`/health` → `{"ok":true}`).
2. **Importación desde producción:** el job `cyc-estado` dio `tasks: 1, profiles: 0, proposals: 0`, igual que el `state.json` del bucket. En staging, la tarea importada `IOBR3hBqNPWoM6Ko` devuelve su veredicto con la tx `e5284043bdfd…`.
3. **Recorrido con pago en staging** (tarea `_9Jlc_YIYzlyI4rb`, depósito `5fa5a437b0132d15964f03eedeba6484886b02fa6479b89c81436631eac4c980`):
   - caso B: rechazado, 4.4 s, envío 1;
   - caso A: aprobado y pagado, 8.1 s, envío 2, tx `c6e8da3d5fe22935f92bfd022ed022c70cfb3473c13694ebee2f084541597c0a`;
   - caso A otra vez: `stage: cache`, 1.6 s, no cuenta como envío.
   - El contrato quedó en `Released`.
4. **Respaldo y restauración** (evidencia del SOW):
   - Antes del respaldo, `contar` en `cyc-pg` daba `tasks: 2, profiles: 0, proposals: 0`.
   - Respaldo a pedido `1795241023879` (`ON_DEMAND`, `SUCCESSFUL`, 06:03 UTC).
   - Se restauró en la instancia temporal `cyc-pg-restauracion`: operación `RESTORE_VOLUME` en estado `DONE` a las 06:26 UTC.
   - El job `cyc-verificar-restauracion` contó la copia restaurada: `tasks: 2, profiles: 0, proposals: 0`, igual que el original.

Nota: staging y producción firman con la misma llave de árbitro (el contrato tiene un solo árbitro). Si los dos pagaran en el mismo segundo, uno podría fallar por número de secuencia y se reintentaría. **No usar staging durante la cumbre.**

## Pendiente de la fase 1

1. **Corte de producción** (después de la cumbre, con tu visto bueno):
   - `STATE_BACKEND=postgres` en `cumpleycobra-api`;
   - quitar el volumen de Cloud Storage y `--max-instances=1`;
   - `--min-instances` de vuelta a 0.
   - Antes del corte: volver a correr el job `cyc-estado` con `--forzar`, para traer el estado más reciente.
2. `api.rodyxdev.com`: necesita tu acceso a Cloudflare.
3. Alertas de presupuesto en Google Cloud: son de la cuenta de facturación y necesitan tu permiso.
4. Modo `demo` en el frontend: estados vacíos y sin páginas sin salida, revisado en celular.
5. ~~Borrar los recursos temporales del ensayo~~: la instancia `cyc-pg-restauracion`, el secreto `cyc-database-url-restauracion` y el job `cyc-verificar-restauracion` se borraron el 21 de noviembre.

## Riesgos

- Cloud SQL `db-f1-micro` no tiene SLA. Para la demo y el piloto alcanza; para mainnet hay que subir de tamaño.
- Con varias instancias, las cuotas diarias son por instancia (ver Decisiones).
