# Fase 3 del plan de mejora: verificador que ejecuta el código

Rama `mejora/fase-3`, desde el tag `mejora-1`. En curso: este reporte se completa al cerrar la fase.

Todo lo nuevo va detrás de `VERIFIER_ENABLED` (apagado por defecto). Con la variable apagada, la API se comporta igual que en `mejora-1`: las tareas existentes y el motor de análisis estático no cambian.

## Diseño

### Dónde corre cada cosa

| Pieza | Dónde | Por qué |
| --- | --- | --- |
| Generar la suite oculta (modelo) | API | La VM no guarda credenciales del modelo |
| Validar la suite (correrla contra una entrega vacía y un stub) | VM | Ejecuta código |
| Ingesta (código pegado, ZIP o repo público con SHA) | VM | Clona y descomprime material ajeno |
| Higiene, build de dependencias, suite en caja negra | VM | Ejecuta código ajeno |
| Juez (modelo), regla final, `verdict_hash`, `release` | API | Necesita el modelo y la llave del árbitro |

La VM solo tiene el token de la cola (`VERIFIER_QUEUE_TOKEN`). Con él puede pedir un trabajo, informar su avance y entregar la evidencia de ese trabajo. No puede pagar, ni leer tareas, ni escribir en otros trabajos: cada trabajo reclamado trae su propio `lease_id`.

### Tareas con verificación por ejecución

- Una tarea nueva puede pedir `verification: "execution"`. Además de lo de v1, lleva una `interface`: el módulo y las funciones que la entrega debe exponer (por ejemplo `descuentos.aplicar_descuento`).
- `rules_hash` de estas tareas usa `version: 2`: es el mismo objeto de la versión 1 más `interface` y `verification`. Las tareas de `version: 1` no cambian.
- Los criterios siguen siendo texto, como en v1. Al generar la suite, el modelo clasifica cada criterio:
  - `test`: se comprueba ejecutando; tiene su archivo `test_cN.py`.
  - `lectura`: no se puede comprobar ejecutando (por ejemplo, «no importa ningún módulo»). Lo decide el análisis estático de v1 y el juez leyendo el código.
- La suite no entra al `rules_hash`: se genera después de crear la tarea. Su `suite_hash` entra al veredicto. El programador ve el plan (una frase por test) antes de aceptar, y `/accept` exige la suite lista (`409 SUITE_NOT_READY`).

### Cola

- Tabla `verifier_jobs` en Postgres, reclamada con `FOR UPDATE SKIP LOCKED` y un plazo de arrendamiento. Si el trabajador muere, el trabajo vuelve a la cola al vencer el plazo.
- Con `STATE_BACKEND=json` (laptop) la cola vive en memoria, con la misma interfaz.
- Dos clases de trabajo: `suite` (validar una suite candidata) y `verify` (verificar una entrega).

### Veredicto `version: 2`

`verdict_hash` = SHA-256 de `canonical_bytes({"version": 2, "task_id", "rules_hash", "suite_hash", "workspace_hash", "approved", "stage", "criteria": [{"index", "status"}], "video_url"})`. En el `release`, `code_hash` lleva el `workspace_hash` (32 bytes).

## Partes

| Parte | Qué | Estado |
| --- | --- | --- |
| A | Núcleo del verificador portado de v2: `verifier/` con sandbox, caja negra, ingesta, higiene. gVisor y proxy configurables | Hecha |
| B | Contrato ejecutable en la API: `interface`, `rules_hash` v2, adaptador de modelo, generación de la suite | Hecha |
| C | Cola en Postgres, rutas del trabajador y trabajador (`verifier/worker.py`) | Hecha |
| D | Juez y regla final en la API; veredicto v2 y `release` | Hecha |
| E | Frontend: crear tarea con ejecución, entregar (pegar, ZIP, repo), progreso en vivo | Hecha (falta revisarla en el navegador con Pollar) |
| F | Perfil web (Playwright, capturas en Cloud Storage) | |
| G | VM Spot sin credenciales con gVisor y proxy (pide permiso antes de crearla) | Scripts listos y probados en Docker local; sin crear |
| H | Corpus de 60 casos, elección del modelo, prueba de escape | Prueba de escape local hecha; faltan el corpus y el modelo |

## Parte A: núcleo del verificador

- `verifier/` no importa nada de `backend/` y no lee `.env`.
- Igual que v2: contenedores con `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, usuario `nobody`, límites de CPU, memoria y PIDs, `/out` en tmpfs acotado. Caja negra con dos contenedores en una red `--internal`: la entrega (relay + adaptador) y los tests confiables (`cc_channel`).
- Nuevo:
  - `SANDBOX_RUNTIME` (`runsc` en la VM) agrega `--runtime` a todos los contenedores.
  - `BUILD_NETWORK` y `BUILD_PROXY`: el paso que instala dependencias sale solo por el proxy con lista blanca. Sin variables, usa `bridge` (solo en desarrollo).
  - `ExecutionSpec` (perfil, interfaz y dependencias permitidas) en lugar del contrato completo de v2: el verificador no necesita ver criterios ni ejemplos.
- Fuera: la GitHub App y la migración de suites de la fase 2 de v2.

```
$ backend/.venv/Scripts/python.exe -m pytest verifier/tests -q -m "not network"
78 passed, 1 skipped, 4 deselected in 27.34s
$ backend/.venv/Scripts/python.exe -m pytest verifier/tests -q -m network
4 passed, 79 deselected in 24.88s
```

El test omitido crea un symlink, y Windows no lo permite sin modo de desarrollador.

## Partes B a D: la API

Archivos nuevos: `backend/llm.py`, `backend/ejecucion/` (`suite.py`, `cola.py`, `juez.py`, `regla.py`, `senales.py`, `seguridad.py`, `rutas.py`), `backend/storage/migrations/002_verificador.sql` (solo agrega tablas), `verifier/worker.py` y `verifier/verification/stub.py`. Cambios en `backend/main.py`: la cola en el arranque, `POST /tasks` con `verification` e `interface`, `/accept` exige la suite lista, `/evaluate` responde `409 EXECUTION_TASK` para estas tareas, y `GET /tasks/{id}` agrega `verification` y `suite` (el plan, nunca el código de los tests).

Rutas nuevas (todas 404 sin `VERIFIER_ENABLED`):

| Ruta | Quién | Para qué |
| --- | --- | --- |
| `POST /verifier/claim` | Trabajador (`Authorization: Bearer <VERIFIER_QUEUE_TOKEN>`) | Pide un trabajo; 204 si no hay |
| `POST /verifier/jobs/{id}/progress` | Trabajador, con `lease_id` | Avance; renueva el plazo del trabajo |
| `POST /verifier/jobs/{id}/suite/generate` y `/suite/validation` | Trabajador | Rondas de la suite oculta |
| `GET /verifier/jobs/{id}/source` | Trabajador | El ZIP de la entrega |
| `POST /verifier/jobs/{id}/result` y `/fail` | Trabajador | Evidencia (la API juzga y paga) o fallo de infraestructura (no cuenta envío) |
| `GET /tasks/{id}/suite` | Cualquiera | Plan de la suite |
| `POST /tasks/{id}/verificaciones` | Programador (`X-Freelancer-Token`) | Encola una entrega: `{"kind": "code"}`, `{"kind": "zip", "zip_b64"}` (máx. 2 MB) o `{"kind": "github_public", "repo", "sha"}`. 202 con `verification_id` |
| `GET /verificaciones/{id}` | Programador o cliente | Avance real y, al final, el veredicto con los mismos campos de `/evaluate` |

Errores nuevos: `SUITE_NOT_READY` 409, `EXECUTION_TASK` 409, `NOT_EXECUTION_TASK` 409, `VERIFICATION_IN_PROGRESS` 409, `LEASE_INVALID` 409, `VERIFIER_NOT_CONFIGURED` 503. Para encolar quedan al menos 300 s de plazo on-chain (`DEADLINE_TOO_CLOSE`). Las mismas guardias de `/evaluate`: token, `Funded`, monto, cliente y `rules_hash` on-chain, máximo 3 envíos.

### Decisiones

- **Implementación de referencia** (no estaba en v2). En la primera prueba con Gemini, un test generado esperaba `19.475 → 19.48`; en binario ese float es `19.47499…` y `round()` da `19.47`. El juez lo marcó como test defectuoso con evidencia y la entrega correcta quedó en revisión manual. En la segunda prueba, el juez dijo `fail` y la rechazó. Por eso cada test, además de fallar contra la entrega vacía y el stub, debe **pasar** contra una implementación de referencia que el modelo escribe aparte. Si un test no pasa, se regenera con el valor real que dio Python. Si la referencia no pasa ningún test, se descarta y se genera otra sin culpar a los tests.
- **Seguridad de v1 sobre la entrega de varios archivos**: los mismos imports y llamadas prohibidos (protegen al cliente que va a correr el código). Los módulos propios de la entrega cuentan como permitidos y los tests propios del programador no se revisan (nunca se ejecutan).
- **Revisión manual** = no se paga solo. En v1 eso es lo mismo que un rechazo: el cliente decide con `client_release`. `comparison` marca esos criterios con ✗ para que la regla «un ✗ = rechazo» siga valiendo en la vista de v1.
- `stage` en un veredicto por ejecución: `hygiene`, `build`, `static`, `tests`, `judge`, `final` o `cache` (los de v1 no cambian).
- El juez corre dentro de la petición del trabajador (`/result`), para que Cloud Run tenga CPU asignada mientras se llama al modelo.

## Parte E: frontend

Detrás de `NEXT_PUBLIC_VERIFIER_ENABLED=true`:

- Al crear la tarea, una casilla «Verificar ejecutando el código (beta)» con módulo, función y firma. Se proponen desde la descripción y el cliente los edita; con la casilla, el plazo mínimo es de 15 minutos.
- El cliente y el programador ven «Cómo se va a verificar»: el tipo de cada criterio y una frase por test, nunca el código.
- El programador solo puede aceptar con la suite lista. Entrega con un caso de la demo, código pegado, ZIP o repositorio público con SHA.
- La terminal imprime cada evento real del verificador con su segundo, y al final el veredicto.

Sin verificar todavía en el navegador: las pantallas están detrás del login de Pollar. Sí pasan `tsc`, `eslint` y los tests (26, 5 nuevos).

## Pruebas

```
$ CYC_TEST_DATABASE_URL=... python -m pytest backend/tests -q        # Postgres, con Docker
352 passed, 2 warnings in 160.05s
$ python -m pytest backend/tests -q -k "not ejecutando and not zip"   # state.json, sin Docker
338 passed, 9 skipped, 5 deselected
$ python -m pytest verifier/tests -q
84 passed, 1 skipped in 50.59s
$ npm test                                                            # frontend
pass 26, fail 0
```

`backend/tests/test_verificador.py` incluye:
- los casos A–D de la demo, ejecutados de verdad en Docker por el trabajador real a través del TestClient, con un modelo falso que siempre dice «pass». Así se comprueba que la regla y las señales mandan sobre el juez;
- una entrega por ZIP de dos archivos;
- la cola en Postgres con cuatro hilos: ningún trabajo se entrega dos veces.

### Con el modelo real (Gemini 3.5 Flash por Vertex), Docker real y testnet

`scripts/verificador_testnet.py`: crea la tarea, espera la suite, deposita con la Stellar CLI, acepta y entrega.

| Corrida | Suite | Entrega | Resultado |
| --- | --- | --- | --- |
| Tarea `Wk646tCZ3fIFDUWv` (sin referencia) | 32 s, 1 ronda | B | Rechazado en `tests` (los tests vencen por el bucle), 75 s |
| | | A | Revisión manual: test mal calculado, señalado por el juez con evidencia |
| Tarea `kJT5LWQdBn0qfgwp` (sin referencia) | 58 s | A | Rechazado: el mismo tipo de test mal calculado (falso rechazo) |
| Tarea `BZRQ3-H_7RSm1xwp` (con referencia) | 62 s, 2 rondas: la referencia atrapó un test del criterio 1 | A | **Aprobado y pagado** en 22.8 s. Tx `18fa1282d8e23bb59304590d1433aff5e457e5b5664c5267b833c09826869831`; on-chain `Released` al programador |

Uso del modelo en la tarea pagada: la suite fueron 8 llamadas (≈13.3k tokens de entrada y 4.6k de salida, ≈$0.06); el juez, 1 llamada de 4 s (≈6.5k y 0.8k, ≈$0.02). Los tests ocultos tardaron 7.6 s.

Antes, con el modelo falso: C (inyección) pasa todos los tests y aun así no se aprueba (señal determinista más el juez); D se rechaza en `static`.

## Parte H (avance): prueba de escape

`verifier/tests/test_escape.py`. Una entrega maliciosa lo intenta todo desde el contenedor de la entrega. Con Docker local (runc):

```
"metadatos_gce": "bloqueado (OSError)",
"internet_ip": "bloqueado (OSError)",
"dns_externo": "bloqueado (gaierror)",
"api_host_docker": "bloqueado (gaierror)",
"puerta_de_enlace": "bloqueado (OSError)",
"escribir_workspace": "bloqueado (OSError)",
"escribir_raiz": "bloqueado (OSError)",
"escribir_usr": "bloqueado (OSError)",
"suite_oculta": "no existe",
"canal_confiable": "no existe",
"salida_junit": "no existe",
"secretos_en_entorno": [],
"usuario": 65534,
"bomba_de_procesos": "bloqueado tras 253 (BlockingIOError)"
```

La bomba de memoria termina como fallo de la entrega (`SubmissionCrashed`), no como un test que pasa. En la VM se repite con gVisor (`SANDBOX_RUNTIME=runsc`).

## Parte G (preparada, sin aplicar): VM del verificador

`verifier/deploy/`:

- **`startup.sh`** (arranque de la VM, idempotente):
  - instala Docker y gVisor (`runsc install`);
  - agrega las reglas `DOCKER-USER` (ningún contenedor llega a `169.254.169.254`) e `INPUT` (ningún contenedor llega al host);
  - crea la red interna `cc-build` y el proxy squid;
  - construye la imagen de los tests con la red del host;
  - instala el trabajador como servicio de systemd.
- **`proxy/`**: squid con lista blanca. Solo deja pasar `pypi.org`, `files.pythonhosted.org` y `registry.npmjs.org`, y solo por CONNECT al 443.
- **`deploy.ps1`**: sin `-Aplicar` solo imprime los comandos. Con `-Aplicar` hace esto:
  1. Crea las reglas de firewall: SSH solo desde IAP, ninguna otra entrada, salida solo al 443.
  2. Crea la VM Spot `e2-standard-2` sin cuenta de servicio ni scopes, con Shielded VM y el token de la cola como metadato (leído de Secret Manager desde tu gcloud, nunca impreso).
  3. Copia el código por IAP. No clona el repositorio: la VM no tiene credenciales de GitHub.
- `verifier/tests/test_proxy.py` levanta la misma topología en Docker local:
  - pip instala `six` por el proxy;
  - sin proxy, el contenedor no sale a internet;
  - el proxy rechaza github.com y los metadatos.
- `.gitattributes` fija LF para `verifier/` y `*.sh`: con `core.autocrlf` de Windows, `git archive` sacaba `startup.sh` con CRLF, y bash en la VM habría fallado.

Antes de aplicarlo (pide tu permiso; regla 14):

1. Crear el secreto `cyc-verifier-queue-token` en Secret Manager.
2. Habilitar el verificador en **staging** (`cumpleycobra-api-staging`): `VERIFIER_ENABLED=true` y `VERIFIER_QUEUE_TOKEN` desde ese secreto.
3. Correr `deploy.ps1 -ApiUrl <URL de staging> -Aplicar`.
4. Repetir en la VM la prueba de escape con gVisor y el recorrido de `scripts/verificador_testnet.py`.

Costo: la VM Spot con 30 GB es de unos 6 a 10 USD al mes si se apaga sin trabajos, o de unos 24 USD si queda prendida; la cubren los créditos.

## Pendientes

1. **Aplicar la parte G en staging** (permiso arriba) y repetir la prueba de escape bajo gVisor. Falta comprobar que Playwright corre bajo gVisor (parte F).
2. **Parte H**: corpus de 60 casos ejecutables y elección del modelo por rol, con 3 corridas y 0 falsas aprobaciones. Para comparar con Muse Spark hace falta `MODEL_API_KEY` en `backend/.env`; hoy solo está en el `.env` de v2.
3. **Parte F**: perfil web de v2 (Playwright, capturas en Cloud Storage con URL firmada de 15 minutos, juez visual).
4. **Revisar en el navegador las pantallas nuevas**: necesitan iniciar sesión con Pollar.
5. Encender y apagar la VM según la cola (plan: apagar tras 15 minutos sin trabajos).

## Riesgos

- **La suite depende del modelo.** Sin la referencia hubo dos fallos en tres corridas; con la referencia, la tercera corrida aprobó y pagó. Hace falta el corpus para medirlo en serio.
- **El juez corre dentro de la petición del trabajador.** Si el modelo tarda más que el plazo del trabajo (180 s), el trabajo vuelve a la cola, pero el veredicto ya quedó en la caché de la tarea, así que el reintento responde desde la caché.
- **El paso de build sigue ejecutando código de dependencias permitidas** (sin red, en gVisor). Un paquete permitido comprometido es un riesgo de cadena de suministro que esto no cubre.
