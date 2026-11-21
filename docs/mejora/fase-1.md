# Fase 1 del plan de mejora: base de producción

Fecha: 21 de noviembre de 2026. Rama `mejora/fase-1`, cerrada con el tag `mejora-1`. Partes: A (código), B (Cloud SQL y staging), C (modo demo del frontend) y D (corte de producción a Postgres). En local todo sigue apagado por defecto (`STATE_BACKEND=json`); producción corre con Postgres desde la parte D.

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

1. ~~Corte de producción~~: hecho el 21 de noviembre, con el visto bueno de Rodrigo (ver «Parte D»).
2. ~~Dominio propio de la API~~: sale de la fase 1. `api.rodyxdev.com` es de un proyecto personal de Rodrigo y no se usa; la API sigue en `run.app` hasta que haya un dominio del producto (ver «Decisiones de hosting» en el plan). Nota para entonces: la sesión de `wrangler` solo trae `zone:read` y no puede crear registros DNS; hará falta un token con «Zone → DNS → Edit» para esa zona.
3. ~~Alertas de presupuesto en Google Cloud~~: Rodrigo ya tiene una alerta de presupuesto en la cuenta de facturación (confirmado por él el 21 de noviembre; no la pude leer porque la API de facturación no está activa en el proyecto).
4. ~~Modo `demo` en el frontend~~: hecho el 21 de noviembre (ver «Parte C»).
5. ~~Borrar los recursos temporales del ensayo~~: la instancia `cyc-pg-restauracion`, el secreto `cyc-database-url-restauracion` y el job `cyc-verificar-restauracion` se borraron el 21 de noviembre.

## Parte C: modo demo del frontend (21 de noviembre de 2026)

Desplegado en Vercel el 21 de noviembre de 2026, con el visto bueno de Rodrigo: copia limpia de `56ee430` (`git archive HEAD frontend`, sin `.env` ni estado), `vercel deploy --prod` → `https://cumpleycobra-3i59nyco7-rodyx-dev.vercel.app`, alias `cumpleycobra.vercel.app`. El primer intento respondió `Not authorized` y el reintento pasó sin cambiar nada. Revisado en producción: aviso de testnet con enlace al faucet de Circle, 404 propio, tarea inexistente con «Esta tarea no existe» (respuesta real del backend en Cloud Run), lista de programadores cargada y portada sin desbordar a 375 px. Para volver atrás: `vercel promote https://cumpleycobra-l5qvy4vlg-rodyx-dev.vercel.app` (el despliegue anterior).

| Pieza | Archivos |
| --- | --- |
| `NEXT_PUBLIC_APP_MODE` (`local`, `demo`, `live`); sin valor, un build de producción es `demo`, así que Vercel no necesita variables nuevas | `frontend/src/lib/app-mode.ts` |
| Aviso fijo «Demo en la testnet de Stellar» con enlace al faucet de USDC de Circle; también en celular, donde el chip «Testnet» del encabezado se oculta | `frontend/src/components/demo-banner.tsx`, `layout.tsx` |
| Sin comandos de terminal fuera de `local`: saldo insuficiente → faucet de Circle y tu dirección para copiar; el respaldo con `tarea_respaldo.py` solo en `local` | `frontend/src/app/cliente/page.tsx` |
| Estado vacío o de error con salida (`EmptyState`) y textos por tipo de falla (`loadProblem`: no existe, enlace inválido, red o RPC) | `frontend/src/components/empty-state.tsx`, `frontend/src/lib/load-problem.ts` |
| Página 404 y límite de error con «Intentar de nuevo» | `frontend/src/app/not-found.tsx`, `frontend/src/app/error.tsx` |

Páginas sin salida que se corrigieron:

- **Tarea que no existe o backend caído** (`/tarea/{id}`): antes, una línea de texto; ahora explica y ofrece inicio, crear tarea o reintentar.
- **Tarea creada en otro navegador** (`/cliente?tarea=…`): se avisa *antes* de pedir la wallet, con enlace a la vista pública.
- **Tarea tomada por otra wallet** y **programador sin invitación**: explican qué hacer; si quien la abre es el cliente, enlace a su vista.
- **Programadores**: error con reintento automático cada 5 s y botón; lista vacía con «Crear la primera tarea».
- **Perfil con dirección inválida**: mensaje propio y enlaces a la lista y al inicio.
- **Buzón**: botón para iniciar sesión, y con el buzón vacío, enlace al perfil público.

Verificación (build de producción con `next start`, es decir, modo `demo`, contra el backend local):

- Celular (375 × 812): 404, tarea inexistente, tarea de otro navegador, tarea propia, buzón, perfil inválido e inicio. Sin desplazamiento horizontal (`scrollWidth` 375).
- Escritorio: programadores con el backend apagado («No se pudo conectar con el servidor») y recuperación sola al volver a encenderlo.
- `npm test`: 21 de 21 (2 nuevos: modo de la app y textos de carga). `tsc`, `eslint` y `next build` sin errores.

## Parte D: corte de producción a Postgres (21 de noviembre de 2026)

| Paso | Resultado |
| --- | --- |
| Respaldo | `gs://…-cyc-state/respaldos/state-20261121-antes-de-postgres.json` (6130 bytes, copia de `state.json`, que no cambió desde las 03:43 UTC) |
| Base propia de producción | Base `cyc_prod` y usuario `cyc_api_prod` en `cyc-pg`, secreto `cyc-database-url-prod` (contraseña al azar, nunca impresa). Staging se queda con la base `cyc`: sus tareas de prueba no entran a producción |
| Importación | Job nuevo `cyc-estado-prod` (imagen `api:feb8cd2`, bucket de producción solo lectura, secreto de producción): `tasks: 1, profiles: 0, proposals: 0` |
| Nueva revisión | `cumpleycobra-api-00003-cez`, imagen `api:feb8cd2` (el backend no cambió desde ese commit). `STATE_BACKEND=postgres`, `APP_MODE=demo`, sin `STATE_FILE` ni volumen, Cloud SQL por conector, de 0 a 3 instancias. Se desplegó sin tráfico (etiqueta `postgres`), se probó y luego recibió el 100 % |
| Revisión anterior | `cumpleycobra-api-00002-7w2` (puente con `state.json`, imagen `api:159f336-limites`) |

### Salida real

1. Revisión nueva sin tráfico: `/health` → `{"ok":true}`; la tarea importada `IOBR3hBqNPWoM6Ko` responde; `/programadores` lista al programador con su pago.
2. Con tráfico, en la URL pública de la API:
   - la tarea importada devuelve su veredicto con la tx `e5284043bdfd…`;
   - tarea nueva `yI2oLY2sHxAheJd-` con 1 USDC, depósito `03dad77536d257a646a2a21e64dfff4715695ec25d243e44ee88d0ed9bed040b`;
   - caso B: rechazado, 3.9 s, envío 1;
   - caso A: aprobado y pagado, 10.1 s, envío 2, tx `c51f1695362d346ca13aa418b225dce39271455fa48349ea9e2906acd63a271b`;
   - caso A otra vez: `stage: cache`, 0.5 s, no cuenta como envío;
   - el contrato quedó en `Released`.
3. Reto SEP-10 desde Postgres: correcto (`home_domain` `cumpleycobra.vercel.app`). CORS: `access-control-allow-origin: https://cumpleycobra.vercel.app`.
4. Frontend en Vercel: `/tarea/yI2oLY2sHxAheJd-` muestra la tarea con depósito, aceptación y verificación hechos.
5. Tests antes del cierre: backend 312 pasados con `state.json` y 320 con Postgres; frontend 21 de 21, `tsc` y `eslint` sin errores.

### Cómo volver atrás

- **API al puente con `state.json`:** `gcloud run services update-traffic cumpleycobra-api --region us-central1 --to-revisions cumpleycobra-api-00002-7w2=100`.
  - Si nada cambió desde el corte, basta eso: `state.json` sigue intacto en el bucket.
  - Si hubo escrituras, antes se exportan: una copia del job `cyc-estado-prod` con el bucket montado **con escritura** y `--args=-m,backend.storage.transfer,exportar,/prod/state.json` (el job actual lo monta en solo lectura a propósito).
- **Frontend:** `vercel promote https://cumpleycobra-l5qvy4vlg-rodyx-dev.vercel.app`.
- **Código:** `main` en el tag `mejora-0`.

## Riesgos

- Cloud SQL `db-f1-micro` no tiene SLA. Para la demo y el piloto alcanza; para mainnet hay que subir de tamaño.
- Con varias instancias, las cuotas diarias son por instancia (ver Decisiones).
- Staging y producción usan la misma cuenta de servicio (`cyc-api`), así que staging podría leer el secreto de la base de producción. Están en bases separadas, pero no aisladas por permisos; separar las cuentas cuando haya usuarios reales.
