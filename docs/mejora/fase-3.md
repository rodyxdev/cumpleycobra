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
| F | Perfil web (Playwright, capturas en Cloud Storage) | Hecha: en staging con pago en testnet (22 de noviembre de 2026) |
| G | VM Spot sin credenciales con gVisor y proxy | Hecha en staging (21 de noviembre de 2026) |
| H | Corpus de 60 casos, elección del modelo, prueba de escape | Hecha: 0 falsas aprobaciones en 3 corridas (Gemini; Muse sin medir) |

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
3. ~~**Parte F**: perfil web~~: hecho (ver «Parte F: perfil web»).
4. **Revisar en el navegador las pantallas nuevas**: necesitan iniciar sesión con Pollar.
5. ~~Encender y apagar la VM según la cola~~: hecho (ver «Encendido y apagado automático de la VM»).

## Riesgos

- **La suite depende del modelo.** Sin la referencia hubo dos fallos en tres corridas; con la referencia, la tercera corrida aprobó y pagó. Hace falta el corpus para medirlo en serio.
- **El juez corre dentro de la petición del trabajador.** Si el modelo tarda más que el plazo del trabajo (180 s), el trabajo vuelve a la cola, pero el veredicto ya quedó en la caché de la tarea, así que el reintento responde desde la caché.
- **El paso de build sigue ejecutando código de dependencias permitidas** (sin red, en gVisor). Un paquete permitido comprometido es un riesgo de cadena de suministro que esto no cubre.

## Parte G aplicada: staging con la VM (21 de noviembre de 2026)

Con tu permiso para staging. Producción (`cumpleycobra-api`) no se tocó.

| Recurso | Estado |
| --- | --- |
| Secreto `cyc-verifier-queue-token` | Valor aleatorio, nunca impreso; lo lee la cuenta `cyc-api` |
| `cumpleycobra-api-staging` | Imagen `api:23ae909` (rama `mejora/fase-3`), revisión `00003-jlk`, `VERIFIER_ENABLED=true`, token desde Secret Manager. La migración `002_verificador` se aplicó sola en Cloud SQL (base `cyc`) |
| Firewall | `cyc-verificador-iap-ssh` (22 solo desde IAP), `cyc-verificador-deny-ingress`, `cyc-verificador-allow-443`, `cyc-verificador-deny-egress` |
| VM `cyc-verificador` | `us-central1-a`, e2-standard-2 Spot, Debian 12, **sin cuenta de servicio ni scopes**, Shielded VM, IP externa sin entrada abierta. El propio agente de Google lo confirma al arrancar: «metadata: … service-accounts/default/token … not defined» |

### Lo que apareció al desplegar (y quedó corregido en el código)

| Problema | Causa | Arreglo |
| --- | --- | --- |
| La API no alcanzaba al contenedor de la entrega | Bajo gVisor el DNS interno de Docker no resuelve alias (`sut`): el stack de red de runsc no usa las reglas iptables del contenedor. Confirmado con dos contenedores runsc: por alias, «name resolution»; por IP, OK | La caja negra pasa `CC_SUT_URL` con la IP del contenedor; el build obtiene la IP del proxy con `BUILD_PROXY_CONTAINER` |
| El proxy respondía 500 a `CONNECT pypi.org` | En GCE el DNS es el servidor de metadatos, bloqueado para los contenedores | Excepción solo para la red del proxy (`172.30.250.0/24`) y solo al puerto 53 del servidor de metadatos. El HTTP de metadatos sigue bloqueado para todos |
| No se construía la imagen del proxy | `apt` de Debian por HTTP (80), y el firewall solo deja salir al 443; además, el DNS de los contenedores | La imagen se construye con la red del host y `apt` usa HTTPS con los certificados de la VM |
| `extractall(filter=…)` y `rmtree(onexc=…)` no existen | Debian 12 trae Python 3.11.2 | Extracción segura propia y `onerror` en 3.11 (con test) |
| El build no leía `requirements.txt` | `mkdtemp` crea 0700 y el contenedor corre como `nobody` | El directorio pasa a 0755 |
| Docker no veía los temporales del trabajador | `PrivateTmp=true` en systemd | `TMPDIR=/var/lib/cyc/tmp` |
| Una falla de infraestructura dejaba la suite en `validando` para siempre | `/fail` no reintentaba | Una suite fallida se reencola (hasta 3 trabajos) y reanuda la validación sin pedirle tests otra vez al modelo (2 tests nuevos). La tarea `o7g2IZemWSoE132E` de staging quedó trabada de antes del arreglo |
| `startup.sh` con CRLF | `core.autocrlf` en `git archive` | `.gitattributes` con `eol=lf` |
| `gpg --dearmor` pedía confirmación en el segundo arranque | El archivo ya existía | `--batch --yes` |

### Salida real en la VM, con gVisor (`CYC_TEST_RUNTIME=runsc`)

```
$ sudo env CYC_TEST_RUNTIME=runsc ... python -m pytest verifier/tests -q -m "not network"
83 passed, 5 deselected in 57.30s
```

Prueba de escape bajo gVisor (el kernel que ve la entrega es el de gVisor, no el de la VM):

```
"metadatos_gce": "bloqueado (TimeoutError)",
"internet_ip": "bloqueado (TimeoutError)",
"dns_externo": "bloqueado (gaierror)",
"api_host_docker": "bloqueado (gaierror)",
"puerta_de_enlace": "bloqueado (TimeoutError)",
"escribir_workspace": "bloqueado (PermissionError)",
"escribir_raiz": "bloqueado (PermissionError)",
"escribir_usr": "bloqueado (PermissionError)",
"suite_oculta": "no existe",
"canal_confiable": "no existe",
"salida_junit": "no existe",
"secretos_en_entorno": [],
"usuario": 65534,
"kernel_visto": "4.19.0-gvisor",
"bomba_de_procesos": "bloqueado tras 109 (OSError)"
```

Desde la red del build (`cc-build`, runsc):

```
directo a pypi por IP: bloqueado
pypi por el proxy: PERMITIDO
github por el proxy: rechazado
metadatos por el proxy: rechazado
build exit 0 | Successfully installed six-1.17.0
squid: CONNECT pypi.org:443 y files.pythonhosted.org:443, nada más
```

### Recorrido real: staging + VM + testnet

`CYC_API_URL=<staging> python scripts/verificador_testnet.py --casos b_calidad.py a_feliz.py`

```
tarea xBj3Nccly4GvACgP · rules_hash 10ec6d0885a7e6c049e4301effcb5843d927bb384aa0520af40e268af79860c7
suite lista en 54.0 s · suite_hash 81eb336da557f7c7ee70d081ce6bcdf1d4ad5dad7ee96825632c453309a98128
depósito 32006c96643b6f29eedafd1e617975478b52d9ed6edbd6bc8bd8d47bd4413e6d
b_calidad.py: done en 90.1 s (ingesta → higiene → tests → juez)   approved=False stage=tests
a_feliz.py: done en 19.3 s (ingesta → higiene → tests → juez)     approved=True stage=final
  tx 02f1764813e942785ef1017243c8b033e7e8ca4a31dff3440c10380e4430c22f
on-chain: Released · programador GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK
```

### Cómo volver atrás

- **API de staging:**
  ```powershell
  gcloud run services update-traffic cumpleycobra-api-staging --region us-central1 --to-revisions cumpleycobra-api-staging-00001-fnl=100
  ```
  También basta `VERIFIER_ENABLED=false`, que apaga todas las rutas nuevas.
- **VM:** `gcloud compute instances stop cyc-verificador --zone us-central1-a` (detenerla no cuesta CPU) o `delete`.
- **Firewall:** borrar las 4 reglas `cyc-verificador-*`.
- **Secreto:** `gcloud secrets delete cyc-verifier-queue-token`.
- **Migración `002`:** solo agrega tablas; la versión anterior las ignora.

### Pendiente de esta parte

- ~~Apagar la VM sola tras 15 minutos sin trabajos, y encenderla desde la API al encolar~~: hecho el 22 de noviembre (sección siguiente al corpus).

## Parte H: corpus de 60 entregas (21 de noviembre de 2026)

`scripts/corpus_verificador/`: 5 acuerdos y 60 entregas, 18 correctas y 42 que no deben aprobarse.

| Acuerdo | Entregas | Qué prueba |
| --- | --- | --- |
| descuentos (demo) | 20, las del corpus de v1 | Bucle sin fin, redondeo, orden, generador, `None`, `eval`, dunders, escritura, inyección, secretos |
| ventas (v2) | 10 | Los 8 casos de v2 (incompleta, memoriza ejemplos, inyección, lee los tests, `os._exit`, `conftest` que fuerza el pase) y 2 nuevos |
| fizzbuzz | 10 | Orden de condiciones, desde 0, error equivocado, enteros en vez de texto, memoriza el ejemplo, inyección |
| contar_palabras | 10 | `split(" ")`, mayúsculas, signos, palabras vacías, `re` no permitido, secretos, memoriza ejemplos; `Counter` como dict |
| mediana | 10 | Sin ordenar, par, `//`, **modifica la lista del cliente** (no se ve por el canal: lo detecta el juez leyendo), vacía con `None` o `IndexError`, memoriza ejemplos |

`scripts/correr_corpus.py`: corre todo en un proceso, con la API, la cola en memoria, el trabajador real contra Docker local, Gemini real por Vertex y un contrato falso (no toca testnet). Cada entrega va como ZIP y se genera una suite nueva por acuerdo en cada corrida. Escribe `scripts/.logs/corpus-<n>.json`.

### Resultado

3 corridas completas con Gemini 3.5 Flash en los dos roles (suite y juez):

| Corrida | Entregas | Falsas aprobaciones | Falsos rechazos |
| --- | --- | --- | --- |
| 1 | 60 | **0** | 1: `mediana/correcta-statistics` |
| 2 | 60 | **0** | 2: `mediana/correcta-statistics` y `contar_palabras/correcta` (el juez no respondió: error 5xx de Gemini) |
| 3 | 60 | **0** | 1: `mediana/correcta-statistics` |

Causas y arreglos:

1. **`statistics.median([])` lanza `StatisticsError`, que hereda de `ValueError`.** Al cruzar el canal, una excepción que no era builtin llegaba como un tipo nuevo sin esa herencia, y `pytest.raises(ValueError)` no la atrapaba. Ahora el adaptador manda la excepción builtin más cercana de la herencia y el canal la recrea como subclase (con test).
2. **Cuota de Vertex.** Con 3 corridas en paralelo hubo muchos `429 RESOURCE_EXHAUSTED` y un 5xx. Primero el juez se quedaba sin respuesta: la regla deja eso en revisión manual, así que no paga, pero cuenta como falso rechazo. El adaptador ahora espera de 4 a 40 s con variación al azar ante 429 y 503, sin gastar los reintentos de errores pasajeros. Además, el cliente de v1 fijaba 20 s por petición y Vertex respondía `504 DEADLINE_EXCEEDED` al juez: cada rol usa ahora su propio tope (90 s).

Repetición tras los arreglos: 3 corridas con suite nueva de mediana (6 entregas) y de contar_palabras (5) dieron **33 de 33 correctas**, incluidas `correcta-statistics` (aprobada) y `ordena-en-su-lugar` (rechazada por el juez).

| | |
| --- | --- |
| Verificaciones | 213 (180 + 33) |
| Falsas aprobaciones | **0** |
| Falsos rechazos por el sistema, después de los arreglos | 0 |
| Suites | 15 de 15 listas; 6 necesitaron 2 rondas (la referencia o la validación atraparon un test) |
| Tiempo por entrega | Mediana de 19.5 s; hasta 4.7 min cuando hubo esperas por cuota o tests que vencen |
| Costo por corrida de 60 entregas (Gemini 3.5 Flash, $1.50 / $9.00 por M) | Suites ≈64k / 17k tokens; juez ≈380k / 49k. Total ≈$1.30, unos 2 centavos por entrega |

### Elección del modelo

Con Gemini 3.5 Flash en los dos roles se cumple el criterio del plan: 0 falsas aprobaciones en 3 corridas. **Muse Spark no se midió**: su `MODEL_API_KEY` solo está en el `.env` de v2. El adaptador ya lo soporta (`LLM_SUITE_PROVIDER=muse`, `LLM_JUEZ_PROVIDER=muse`); para compararlo hay que poner la llave en `backend/.env` y correr `scripts/correr_corpus.py` con esas variables.

Decisión por ahora: **Gemini en los dos roles**. Lo cubren los créditos de Google y no agrega otro proveedor ni otro secreto a la API.

### Riesgos que deja el corpus

- **La cuota de Vertex** limita el paralelismo. Una suite pide hasta 8 llamadas a la vez. Con varias tareas creándose juntas habrá esperas, nunca pagos indebidos. Si crece el volumen, conviene un semáforo global de llamadas o pedir más cuota.
- **Los falsos rechazos los paga el programador** (no cobra sin la aprobación manual del cliente). Por eso se miden aparte, aunque la métrica que manda sea la de falsas aprobaciones.

## Encendido y apagado automático de la VM (22 de noviembre de 2026)

La VM ya no queda prendida: se apaga sola tras 15 minutos sin trabajos y la API la enciende cuando hay trabajo.

### Cómo funciona

- **Apagado (VM).** Con `VERIFIER_IDLE_SHUTDOWN_SECS` (900 por defecto en la VM; metadato opcional `verifier-idle-secs`, `0` lo desactiva), el trabajador cuenta el tiempo desde el último trabajo. Al cumplirse, **deja de pedir trabajo** y corre `systemctl poweroff`; en GCE la instancia queda detenida y no cobra CPU. Como deja de pedir antes de apagar, nunca corta un trabajo a medias. La unidad pasó a `Restart=on-failure` para que systemd no lo reviva mientras se apaga.
- **Encendido (API).** `backend/ejecucion/arranque.py` lee el estado de la instancia en la API de Compute Engine y, si está `TERMINATED` o `STOPPED`, la enciende. Se dispara:
  - al encolar un trabajo (`POST /tasks` con ejecución y `POST /tasks/{id}/verificaciones`);
  - al consultar un trabajo que sigue en cola (`GET /tasks/{id}`, `GET /tasks/{id}/suite`, `GET /verificaciones/{id}`). Eso cubre la carrera de un trabajo encolado justo mientras la VM se apagaba, y las VMs Spot que Google detuvo.
  - Como mucho una revisión cada 30 s (5 s si la VM estaba `STOPPING`), en segundo plano: nunca retrasa ni hace fallar la petición.
- **Variables de la API:** `VERIFIER_VM_NAME`, `VERIFIER_VM_ZONE` y `VERIFIER_VM_PROJECT`. Sin `VERIFIER_VM_NAME` no hace nada (en local, el trabajador se corre a mano).
- **Permiso mínimo.** El rol personalizado `cycVerificadorArranque` solo tiene `compute.instances.get` y `compute.instances.start`. Está otorgado a la cuenta `cyc-api` **solo sobre la instancia `cyc-verificador`** (`deploy.ps1 -Arranque`): no puede detenerla, borrarla, cambiarle metadatos ni tocar otra VM. Como la VM no tiene cuenta de servicio, encenderla no pide `iam.serviceAccounts.actAs`.
- **Pantallas:** la línea de espera ahora dice que encender el verificador tarda 1 o 2 minutos si estaba apagado.

### Arreglo de seguridad que salió de esto

Las reglas de iptables (los contenedores no hablan con los metadatos ni con el host) no sobreviven a un reinicio. Antes solo las ponía `startup.sh`, y el trabajador estaba habilitado para arrancar al encender. Tras un reinicio, el trabajador podía empezar a ejecutar entregas **antes** de que existieran las reglas. Con encendidos frecuentes eso dejaba de ser teórico. Ahora:

- `verifier/deploy/red.sh` + `cyc-red.service` aplican las reglas **antes de Docker** en cada arranque (`Before=docker.service`, `RequiredBy=docker.service`: si fallan, Docker no arranca).
- El trabajador ya no arranca solo: lo arranca `startup.sh` cuando la red y las imágenes están listas, y su unidad exige `cyc-red.service` y comprueba la regla de los metadatos en `ExecStartPre`.

### Comprobado en staging

| Paso | Resultado |
| --- | --- |
| Tests | 445 del backend y del verificador (12 nuevos: `test_arranque.py`, `test_worker_idle.py`), 26 del frontend, lint y tipos |
| Imagen y API | `api:1152108`, revisión `cumpleycobra-api-staging-00004-7tn` con las tres variables. Producción no se tocó |
| Reinicio de la VM | `cyc-red` terminó a las 06:55:21, Docker arrancó a las 06:55:44 y el trabajador a las 06:55:45, con las reglas ya puestas |
| Apagado | Con el límite bajado a 120 s para la prueba, la VM quedó `TERMINATED` a las 06:58:49 sin intervención |
| Encendido desde la API | Con la VM apagada, `scripts/verificador_testnet.py --casos a_feliz.py` creó la tarea `h4gfUOOuYpErrb9u` a las 06:59:07. La VM pasó a `STAGING` a las 06:59:16 y a `RUNNING` a las 06:59:32 |
| De punta a punta | Suite lista en 105.9 s contando el arranque. Caso A aprobado en 16.1 s y pagado: release `4b946bff34bb3e5a38e25646d36ec1eee9bee38cb8c26d0923f72f9d2d904c46` (on-chain `Released`) |

Después se quitó el metadato `verifier-idle-secs`, así que desde el siguiente arranque vuelve a 15 minutos.

### Costo y espera

- Apagada, la VM solo cobra el disco de 30 GB (≈1.2 USD al mes). Prendida, ≈0.03 USD por hora.
- El primer trabajo tras un apagado espera 1 o 2 minutos más (arranque de la VM y de `startup.sh`). El margen de 300 s de plazo on-chain para encolar (`VERIFY_MIN_SECONDS`) sigue alcanzando.

### Cómo volver atrás

- Quitar `VERIFIER_VM_NAME` en Cloud Run: la API deja de encender la VM.
- Metadato `verifier-idle-secs=0` y reiniciar la VM: deja de apagarse sola.
- Quitar el permiso:
  ```powershell
  gcloud compute instances remove-iam-policy-binding cyc-verificador --zone us-central1-a --member serviceAccount:cyc-api@<proyecto>.iam.gserviceaccount.com --role projects/<proyecto>/roles/cycVerificadorArranque
  gcloud iam roles delete cycVerificadorArranque --project <proyecto>
  ```
- API de staging a la revisión anterior: `gcloud run services update-traffic cumpleycobra-api-staging --region us-central1 --to-revisions cumpleycobra-api-staging-00003-jlk=100`.

## Parte F: perfil web (22 de noviembre de 2026)

Una tarea puede acordar un **sitio web** (HTML, CSS y JS; estático o un proyecto npm con `build`) en lugar de funciones de Python. Se revisa en un navegador real, aislado y sin internet, a 1440 px y a 390 px. Portado de v2 (`backend/web/`) sin la grabación de video, como pide el plan.

### Acuerdo

- `POST /tasks` con `verification: "execution"`, `language: "web"` y `web: {"pages": ["/", "/contacto"]}` (1 a 5 rutas), sin `interface`.
- `rules_hash` v2 agrega la clave `web` solo en estas tareas: ningún hash anterior cambia (`backend/hashing.py`).
- `allowed_deps` son nombres de npm.

### Suite: chequeos públicos del catálogo

El modelo (rol `suite`) clasifica cada criterio:

| Tipo | Cómo se decide |
| --- | --- |
| `navegador` | 1 a 4 chequeos del catálogo fijo de v2 (`verifier/contract.py: WebCheck`): `text_present`, `title_contains`, `element_visible`, `link_navigates`, `form_submits`, `no_horizontal_overflow`. Los corre Playwright del lado confiable: resultado determinista, sin modelo |
| `visual` | Lo juzga el modelo con las capturas y debe citar al menos una captura que exista |
| `lectura` | Lo juzga el modelo leyendo el código (como en el perfil script) |

- A diferencia de los tests ocultos, **los chequeos son públicos**: repiten el criterio, y el programador acepta exactamente eso.
- Se validan igual que la suite del perfil script:
  - contra un sitio vacío ninguno puede pasar (salvo «sin desborde»);
  - contra un sitio de referencia que escribe el modelo, todos deben pasar.
- La «suite» que entra al `suite_hash` es el hash del runner (código nuestro), los chequeos, la clasificación y la referencia.

### Ejecución en la VM

| Paso | Qué hace |
| --- | --- |
| Higiene | Sitio estático con `index.html`, o `package.json` + `package-lock.json`. Dependencias solo de las permitidas, todas de `registry.npmjs.org` con `integrity`. Sin `.npmrc` ni `node_modules/` |
| Build | `npm ci` en la red del build (salida solo por el proxy con lista blanca) y `npm run build` sin red, bajo gVisor como `nobody` |
| Servido | `http.server` (código nuestro) en una red interna sin internet |
| Navegador | Contenedor confiable con Playwright (`verifier/web/runtime/web_runner.py`). Corre los chequeos, toma capturas JPEG (máximo 3000 px de alto) y recoge texto visible, texto oculto y desborde. Solo deja pedir recursos a la entrega |

Las capturas viajan a la API en la evidencia: la VM no tiene credenciales.

### API: juez, regla y evidencia

- **Juez web** (`backend/ejecucion/juez_web.py`): recibe las capturas como imágenes (el adaptador de modelos ahora acepta partes de imagen en Gemini y en Muse).
  - El código y el texto de las páginas van en un bloque con nonce, como en el perfil script.
  - Una cita de captura vale solo si esa captura existe; una cita de código, si aparece literalmente.
- **Regla** (`regla.decide_web`):
  - `navegador` pasa solo si todos sus chequeos pasan;
  - `visual` pasa con veredicto pass que cite una captura; sin cita, va a revisión manual;
  - texto (visible u oculto) dirigido al evaluador en la página o en el código impide aprobar.
- **Evidencia** (`backend/ejecucion/evidencia.py`):
  - las capturas van a Cloud Storage (`EVIDENCE_BUCKET`) o a una carpeta local;
  - se ven con una URL firmada de 15 minutos, `GET /evidencia/{clave}?exp=&sig=`, un HMAC con una llave derivada de `VERIFIER_QUEUE_TOKEN`;
  - el SHA-256 de cada captura entra al `verdict_hash` v2 (clave `evidence`, solo en veredictos web).
- **Respuestas:**
  - `GET /verificaciones/{id}` trae `verification.screenshots` con URL nueva en cada consulta;
  - `GET /tasks/{id}/verdicts` agrega `screenshots` solo a los veredictos que tienen capturas (la respuesta de las tareas anteriores no cambia).
- **Frontend:**
  - «Código de Python» o «Sitio web» al crear la tarea, con las páginas a revisar;
  - el plan muestra los chequeos;
  - la entrega web solo acepta ZIP o repositorio;
  - galería de capturas para el programador y en cada veredicto del cliente.

### Corpus web y lo que corrigió

`scripts/corpus_verificador/web_cafe.py` (8 entregas) y `web_portafolio.py` (5 entregas, dos páginas): 3 correctas y 10 que no deben aprobarse. Las que no deben aprobarse:
- formulario por GET;
- título equivocado;
- franja que desborda a 390 px;
- encabezado chico al final;
- fuente de Google Fonts;
- texto oculto dirigido al evaluador;
- enlace roto;
- correo equivocado;
- dos proyectos en vez de tres;
- nombre que falta en una página.

Una de las correctas es un proyecto npm con `build`.

Las primeras corridas no llegaron a verificar nada: la suite se rechazaba. Lo que salió y quedó corregido:

| Corrida | Qué pasó | Arreglo |
| --- | --- | --- |
| 1 | El modelo puso `index.html` como página, en lugar de la ruta `/`, aun después de la retroalimentación | Se normaliza la ruta (`index.html` → `/`, `contacto/` → `/contacto`) y el prompt da las rutas válidas |
| 2 | Para «todas las páginas» escribió `/*` | `*` se expande a un chequeo por página |
| 3 | Escribió `...` como página. El sitio de referencia enlazaba a `contacto/index.html` y el chequeo esperaba `/contacto` | Con una sola página, cualquier página es esa. El runner trata `/x`, `/x/`, `/x.html` y `/x/index.html` como la misma página (solo con destinos relativos) |
| 4 | 2 falsos rechazos: el juez aprobó citando la captura S1 con el texto «Café Luna» (9 caracteres) y exigíamos 10 | Mínimo de 3 caracteres, igual que las citas de código |

**Resultado con los arreglos: 3 corridas seguidas (5, 6 y 7), 39 verificaciones, 0 falsas aprobaciones y 0 falsos rechazos.** Las suites quedaron listas en las 6 (mediana 25.6 s). En la corrida 6 hubo 429 de cuota, absorbidos por la espera del adaptador.

| Métrica | Valor |
| --- | --- |
| Tiempo por entrega (con navegador y juez) | Mediana 14.2 s; máximo 141.5 s, con esperas por cuota |
| Juez por entrega | ≈6.6k tokens de entrada (con 3 a 5 imágenes) y 0.4k de salida: ≈1.4 centavos de dólar |
| Suite por acuerdo | ≈7.4k / 2.2k tokens: ≈3 centavos |

### Comprobado en staging y en la VM

- **Tests:**
  - local: 467 del backend y del verificador (incluye `backend/tests/test_web.py`, `verifier/tests/test_web.py` y una corrida de punta a punta con Chromium real), 27 del frontend, lint y tipos;
  - en la VM, bajo gVisor (`CYC_TEST_RUNTIME=runsc`): los 6 tests web y la prueba de escape pasan (7 en 69 s). **Chromium corre bajo gVisor**: era la duda abierta del plan.
- **Escape desde el JavaScript del sitio:**
  - un sitio intenta alcanzar el servidor de metadatos, internet y el host de Docker;
  - los tres quedan `bloqueado` en la VM y en local.
- **Infraestructura:**
  - VM: imagen `cumpleycobra-web-runner:vm` (Playwright 1.64.1, 2.6 GB) y `node:22-slim`, que construye y descarga `startup.sh` con la red del host;
  - API de staging: revisión `cumpleycobra-api-staging-00005-9wh`, imagen `api:5429fa0`, con `EVIDENCE_BUCKET`;
  - bucket `cyc-evidencia-staging-1017372721585`: privado (acceso uniforme y prevención de acceso público), borra los objetos a los 90 días, y `cyc-api` solo tiene `objectCreator` y `objectViewer`.
- **De punta a punta con testnet:** `scripts/verificador_testnet.py --web --casos formulario-get correcta` contra staging:
  - tarea `ayQbmUldqXKfejlK`; suite lista en 37.5 s (4 navegador, 1 visual, 1 lectura); depósito `b1d046b7…`;
  - `formulario-get`: rechazado solo en el criterio 3 (el formulario no hace POST);
  - `correcta`: aprobado y pagado, release `698dada572c3b3cd2cd42802ac0ae07edfad0d118252c0133e99e9dc7796b0d8` (on-chain `Released`);
  - las 6 capturas quedaron en el bucket y la URL firmada respondió `200 image/jpeg`.

### Riesgos y límites

- **El JavaScript de la entrega corre en el Chromium del contenedor confiable**, sin el sandbox propio de Chromium (Playwright lo desactiva en contenedores). Un exploit del navegador podría alterar el reporte de ese contenedor.
  - Lo acota: gVisor, sin red fuera de la red interna, sin secretos ni credenciales, y el juez y la regla en la API.
  - Pendiente: probar `chromium_sandbox=True` bajo gVisor.
- **Lo visual depende del modelo.** Por eso un `visual` sin cita de captura va a revisión manual, nunca a aprobación.
- **Sin mockups del cliente** (v2 los tenía): el juez compara contra el texto del criterio, no contra un boceto. Se puede agregar después.
- **Las capturas muestran el diseño al cliente antes del pago** (no el código). Es la misma decisión de v2.

### Cómo volver atrás

- API de staging a la revisión anterior: `gcloud run services update-traffic cumpleycobra-api-staging --region us-central1 --to-revisions cumpleycobra-api-staging-00004-7tn=100`. Las tareas de script no cambian: el perfil web solo aparece con `web` en `POST /tasks`.
- Bucket: `gcloud storage rm -r gs://cyc-evidencia-staging-1017372721585` (solo tiene capturas de testnet).


## Hotfix en producción: librería de Stellar (22 de noviembre de 2026)

Al revisar las pantallas con una sesión real de Pollar apareció «No se pudo leer tu cuenta: LedgerHeader.scpValue.ext.v: unknown enum value 3».

- **Causa:** testnet subió al protocolo 30 y `@stellar/stellar-sdk` 17.1.0 ya no lee el encabezado del ledger, así que `getAssetBalance` y `getLatestLedger` fallaban. Se reprodujo fuera del navegador; con la 17.4.0 se arregla.
- **Arreglo:** rama `hotfix/stellar-sdk-17.4` desde `main`, que solo cambia `package.json` y `package-lock.json`. Pasan tipos, lint, tests y el build de producción.
- **Despliegue:** con el permiso de Rodrigo se fusionó a `main` (`3ef4df3`), Vercel lo desplegó en producción y el JavaScript publicado trae la 17.4.0. La rama `mejora/fase-3` tiene la misma versión.
- **Probado en local con Pollar:**
  - **Tarea normal:** depósito `689b1064…`; el caso B rechazado; aprobación manual `259426ac…`.
  - **Tarea web:** depósito; entrega por ZIP; pago `4503b6d9…`; galería de capturas en la vista del cliente.
