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
| G | VM Spot sin credenciales con gVisor y proxy (pide permiso antes de crearla) | |
| H | Corpus de 60 casos, elección del modelo, prueba de escape | |

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
