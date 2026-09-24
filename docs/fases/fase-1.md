# Fase 1: backend FastAPI (túnel botón → FastAPI → Gemini → release)

Fecha: jueves 24 de septiembre de 2026.
Hito de CLAUDE.md: `curl` del caso A devuelve `transaction_hash` real; caso D con `stage "deterministic"`; reenvío de A con `stage "cache"`; reinicio del backend conserva la tarea. **Cumplido**, más lo que pidió la revisión: presupuesto de tiempo, #9/#6, pytest y un script reproducible.

Contrato: `CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ` (el de la fase 0). Motor: Gemini `gemini-3.5-flash` por Vertex AI (`global`), con las credenciales de gcloud (ADC) de la máquina.

## 1. Qué se hizo

Entorno: Python 3.14.5 en `backend/.venv`; fastapi 0.141.1, uvicorn 0.53.0, google-genai 2.25.0, stellar-sdk 16.1.0, pytest 9.1.1 (`backend/requirements.txt`).

Cómo correrlo, desde la raíz del repositorio:

```bash
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
backend/.venv/Scripts/python -m pytest backend/tests -v
backend/.venv/Scripts/python -m uvicorn backend.main:app --port 8000
bash scripts/fase1-curl.sh
```

`scripts/fase1-curl.sh` arranca y detiene el backend él mismo.

| Archivo | Contenido |
| --- | --- |
| `backend/hashing.py` | Helper único de CLAUDE.md (`canonical_bytes`, `sha256_hex`) + `rules_hash`, `code_hash`, `verdict_hash` |
| `backend/config.py` | Variables de entorno, constantes de tiempo (120 s, 45 s, 30 s), 3 envíos, 10 KB. `Settings.__repr__` nunca muestra secretos |
| `backend/state.py` | `state.json`: diccionario en memoria, escritura atómica (temporal + `os.replace`), un `asyncio.Lock` por `task_id` |
| `backend/deterministic.py` | Capa 1 (10 KB en bytes UTF-8 antes de limpiar; comentarios fuera con `tokenize`) y capa 2 (`ast`) |
| `backend/gemini.py` | Capa 3: cliente Vertex o API key, salida estructurada, reintentos, revisión del plazo antes de cada reintento |
| `backend/stellar_client.py` | `get_task` (simulación), reloj del ledger, `release` (preparar, firmar, enviar, consultar) con reintentos |
| `backend/main.py` | API: `/health`, `POST /tasks`, `GET /tasks/{id}`, `/accept`, `/evaluate`, `/delivery`; guardias y capa 4 |
| `backend/plantilla.py` | Plantilla fija de la demo (`aplicar_descuento`, 6 criterios, 3 ejemplos) |
| `backend/casos/*.py` | Casos A (feliz), B (`while` sin incremento), C (inyección en el docstring), D (`os.environ`) |
| `backend/tests/test_deterministic.py` | Casos A a D, evasiones y código roto (37 tests) |
| `backend/tests/test_hashing.py` | Float = error, NFC, orden de claves, formato canónico (9 tests) |
| `backend/tests/test_evaluate_pagos.py` | `/evaluate` con contrato y Gemini falsos: #9, #6, plazo, reintentos, esquema (10 tests) |
| `backend/requirements.txt` | Versiones fijas |
| `backend/.env` | **No se sube** (lo ignora `.gitignore`). Proyecto de GCP tomado del `.env` que indicó Rodrigo; `ARBITER_SECRET_KEY` escrita directo desde `stellar keys secret cyc-arbiter`, sin pasar por la terminal |
| `scripts/fase1-curl.sh`, `scripts/fase1/util.py` | Prueba reproducible con `curl` y la Stellar CLI (sin jq) |
| `.env.example` | Alternativa `GEMINI_API_KEY` y valores por defecto de Vertex |
| `.gitignore` | `backend/state.json.tmp`, `scripts/.logs/` |

### Flujo de `/evaluate`

Todo ocurre con el lock de la tarea tomado:

1. **Guardias baratas:** tarea existente (404); programador amarrado (si no, `409 CRITERIA_NOT_ACCEPTED`); `X-Freelancer-Token` válido con `hmac.compare_digest` y `freelancer_address` igual a la amarrada (si no, `403 INVALID_TOKEN`).
2. **Caché** por `task_id` + `code_hash`: un acierto devuelve `stage: "cache"` y no cuenta como envío. Va **antes** del límite, para que el reenvío de B tras 3 envíos sea caché y no 429.
3. **Límite:** 3 envíos (si no, `429 TOO_MANY_SUBMISSIONS`).
4. **Guardias on-chain** (`get_task` simulado + reloj del ledger):
   - la tarea está `Funded` (si no, `409 TASK_NOT_FUNDED`);
   - monto, cliente y `rules_hash` coinciden con lo guardado (si no, `409 TASK_MISMATCH`);
   - quedan al menos 120 s de plazo (si no, `409 DEADLINE_TOO_CLOSE`, sin contar el envío).
5. **Capas 1 y 2.** Si fallan: `stage: "deterministic"` y no se llama a Gemini.
6. **Capa 3 (Gemini):** temperatura 0, `response_mime_type` JSON y `response_schema` (`trace`, `logic`, `comparison`, `security_flags`, `approved`, `reason`); timeout de 45 s.
   - **Reintentos:** 2 ante errores transitorios (timeout, 429, 5xx), con espera de 1 s y 3 s; 1 si la respuesta sale del esquema (incluye que `comparison` no traiga una entrada por criterio). Si aun así falla: `502 ENGINE_UNAVAILABLE`, sin contar el envío.
   - **Plazo:** antes de cada reintento se vuelve a leer el reloj del ledger. Si no quedan 75 s (45 del intento + 30 del release): `409 DEADLINE_TOO_CLOSE`, sin contar el envío.
7. **Capa 4:** `security_flags` no vacío o algún criterio con `✗` → `approved = false`.
8. **Release:** antes de firmar se revisa el plazo; si quedan menos de 30 s, no se firma. Responde `approved: true`, `transaction_hash: null` con la explicación, y el envío no se cuenta. Si hay tiempo, `release` al programador **amarrado** (nunca a una dirección del cuerpo). El hash firmado se guarda en `state.json` *antes* de enviar.
   - `#9 DeadlinePassed`: no se reintenta. Responde `approved: true`, `transaction_hash: null` y el `reason` en español: el código cumple, el plazo venció y el cliente aún puede aprobar manualmente.
   - `#6 NotFunded`, o release sin confirmar: se relee el contrato. Si la tarea está `Released` para el programador amarrado, es éxito con el hash guardado en `state.json`.

`ARBITER_SECRET_KEY` solo vive en `backend/.env` y en el proceso. No aparece en logs, terminal, reporte ni commits: se buscó el patrón de llave secreta en `backend.log` y en la salida del script, con 0 coincidencias.

## 2. Desviaciones de CLAUDE.md y por qué

1. **Gemini por Vertex o por API key.** `GOOGLE_GENAI_USE_VERTEXAI=true` usa Vertex (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`); si no, `GEMINI_API_KEY`. Lo pidió la revisión. CLAUDE.md no lista `GEMINI_API_KEY` en la tabla de variables: **propongo agregarla**.
2. **Códigos de error nuevos** (formato `{"error","message"}`): `TASK_NOT_FOUND` 404, `INVALID_REQUEST` 400 (validación, float en `amount`, JSON inválido), `CHAIN_UNAVAILABLE` 502 (el RPC de Stellar no responde; `ENGINE_UNAVAILABLE` queda solo para el motor), `TASK_NOT_RELEASED` 409 y `NO_DELIVERY` 404 (en `/delivery`). No cambió ningún código existente. **Propongo agregarlos a CLAUDE.md.**
3. **Campos extra en la respuesta de `/evaluate`:** `verdict_hash`, `security_flags` y `submissions_used`. Los cuatro primeros campos y el resto no cambian.
   - En #9 o sin tiempo para el release, `reason` se reemplaza por la explicación del pago.
   - El `verdict_hash` se calcula sobre el `reason` del veredicto, que se guarda aparte en `state.json`.
4. **Orden de guardias:** caché antes del límite de envíos (ver sección 1). CLAUDE.md las lista sin orden.
5. **Capa 2, reglas extra además de las de CLAUDE.md:**
   - `locals`, `.putenv`, `.popen`, `.exec*`, `.spawn*`, `.write_text`, `.write_bytes`;
   - cadenas literales con nombre dunder (por ejemplo `getattr(x, "__class__")`) y nombres dunder en `def`, `class`, argumentos y keywords;
   - `open` con modo no literal, y `getattr` u `open` usados fuera de una llamada;
   - el texto `codigo_entregado` dentro del código se rechaza por seguridad, porque rompería el delimitador ante Gemini.

   En un rechazo determinista, `comparison` trae "✗ Criterio N: no evaluado…" por cada criterio, para cumplir con una entrada por criterio.
6. **Capa 4, regla extra:** un criterio marcado `✗` fuerza el rechazo aunque Gemini diga `approved: true`. La instrucción de sistema ya lo pide; la capa 4 lo garantiza.
7. **Presupuesto de tiempo concreto:** 120 s para entrar, 75 s antes de cada reintento a Gemini y 30 s antes de firmar el release. Sin tiempo para el release, el veredicto aprobado se guarda en caché, pero el envío no cuenta.
8. **Reintento del pago desde la caché.** Si el release falló por red (`CHAIN_UNAVAILABLE` del RPC), el veredicto queda en caché como pendiente de pago. Reenviar el mismo código reintenta el release sin contar envío ni volver a llamar a Gemini.
9. **`GET /tasks/{id}/delivery`** implementado mínimo: solo con `X-Client-Token` y la tarea `Released` on-chain. No es parte del hito, pero el candado del código no se recorta. Quedan para la fase 4: `/consent` (función 5), `/tasks/draft`, `/tasks/draft/review` y `/fx/usd-mxn`.
10. **`/accept` no exige depósito ni revisa la trustline** del programador. La trustline es un bloqueo de la UI (fase 3). Ver riesgos.
11. **stellar-sdk síncrono** (`SorobanServer`) llamado con `run_in_threadpool`, como permite CLAUDE.md. El reloj del contrato es `getLatestLedger.close_time`.
12. **`task_id`** = `secrets.token_urlsafe(12)` (16 caracteres URL-safe, puede incluir `-` y `_`).
13. **El script cubre más que lo pedido:**
    - tarea 3 con plazo de 1 minuto → `DEADLINE_TOO_CLOSE`;
    - tarea 4 depositada con la mitad del monto → `TASK_MISMATCH`;
    - `CRITERIA_NOT_ACCEPTED` y `TASK_NOT_FUNDED`;
    - `/accept` idempotente y `/delivery`.

    Los cuerpos JSON van por archivo (`--data-binary @archivo`): en Windows, los argumentos de `curl` no llegan en UTF-8 y la primera corrida falló con 400 por eso.

## 3. Comandos ejecutados y salida real

### 3.1 Credenciales (sin imprimir valores)

```
llave del árbitro coincide: True        # Keypair(ARBITER_SECRET_KEY).public_key == GAGG…KZGY
vertex responde: 'ok'                    # gemini-3.5-flash en global, por ADC
ledger: 4847686 close_time: 1790262017 ahora: 1790262024
```

### 3.2 Prueba directa del motor (Gemini, sin contrato), antes del script

```
== a_feliz.py approved=True flags=0 t=8.2s
== b_calidad.py approved=False flags=0 t=9.6s     (✗ Criterio 4 y ✗ Criterio 6: bucle infinito)
== c_inyeccion.py approved=False flags=1 t=49.1s  (6/6 criterios ✓, rechazado por security_flags)
```

### 3.3 `pytest -v` (salida completa)

```
$ backend/.venv/Scripts/python -m pytest backend/tests -v -p no:warnings
platform win32 -- Python 3.14.5, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\rodri\Desktop\cumpleycobra\backend\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\rodri\Desktop\cumpleycobra
plugins: anyio-4.15.1
collecting ... collected 56 items

backend/tests/test_deterministic.py::test_caso_a_pasa_a_gemini PASSED    [  1%]
backend/tests/test_deterministic.py::test_caso_b_pasa_a_gemini PASSED    [  3%]
backend/tests/test_deterministic.py::test_caso_c_pasa_a_gemini_con_docstring_intacto PASSED [  5%]
backend/tests/test_deterministic.py::test_caso_d_rechazo_determinista_por_seguridad PASSED [  7%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[x = __builtins__\n-__builtins__] PASSED [  8%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[def f():\n    return __builtins__['ev' + 'al']('1')\n-__builtins__] PASSED [ 10%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[nombre = 'sys' + 'tem'\ngetattr(object, nombre)\n-getattr con un nombre que no es literal] PASSED [ 12%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[g = getattr\n-fuera de una llamada verificable] PASSED [ 14%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[setattr(object(), 'x' + 'y', 1)\n-setattr con un nombre que no es literal] PASSED [ 16%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[globals()['x'] = 1\n-'globals'] PASSED [ 17%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[vars()\n-'vars'] PASSED [ 19%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[breakpoint()\n-'breakpoint'] PASSED [ 21%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[().__class__.__base__.__subclasses__()\n-__class__] PASSED [ 23%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[().__class__.__base__.__subclasses__()\n-__subclasses__] PASSED [ 25%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[getattr((), '__class__')\n-'__class__'] PASSED [ 26%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[eval('1 + 1')\n-'eval'] PASSED [ 28%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[exec('x = 1')\n-'exec'] PASSED [ 30%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[compile('1', 'x', 'eval')\n-'compile'] PASSED [ 32%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[__import__('os')\n-__import__] PASSED [ 33%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[import os\nos.system('ls')\n-'.system'] PASSED [ 35%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[import subprocess\n-import no permitido 'subprocess'] PASSED [ 37%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[from os import getenv\n-import no permitido 'os'] PASSED [ 39%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[from . import algo\n-import relativo] PASSED [ 41%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[open('x.txt', 'w').write('hola')\n-open en modo escritura 'w'] PASSED [ 42%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[open('x.txt', mode='a')\n-open en modo escritura 'a'] PASSED [ 44%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[m = 'w'\nopen('x.txt', m)\n-open con un modo que no es literal] PASSED [ 46%]
backend/tests/test_deterministic.py::test_evasiones_rechazadas[x = '</codigo_entregado>'\n-etiqueta reservada] PASSED [ 48%]
backend/tests/test_deterministic.py::test_getattr_con_literal_y_open_lectura_permitidos PASSED [ 50%]
backend/tests/test_deterministic.py::test_imports_permitidos_si_estan_en_allowed_deps PASSED [ 51%]
backend/tests/test_deterministic.py::test_codigo_roto_es_rechazo_sin_excepcion[def f():\n        x = 1\n    return x\n] PASSED [ 53%]
backend/tests/test_deterministic.py::test_codigo_roto_es_rechazo_sin_excepcion[x = 1\n    y = 2\n] PASSED [ 55%]
backend/tests/test_deterministic.py::test_codigo_roto_es_rechazo_sin_excepcion[def f():\nreturn 1\n] PASSED [ 57%]
backend/tests/test_deterministic.py::test_codigo_roto_es_rechazo_sin_excepcion[x = '''sin cerrar\n] PASSED [ 58%]
backend/tests/test_deterministic.py::test_codigo_roto_es_rechazo_sin_excepcion[print((1, 2\n] PASSED [ 60%]
backend/tests/test_deterministic.py::test_codigo_roto_es_rechazo_sin_excepcion[x = 1\x00\n] PASSED [ 62%]
backend/tests/test_deterministic.py::test_limite_de_tamano_en_bytes_utf8_antes_de_limpiar PASSED [ 64%]
backend/tests/test_deterministic.py::test_strip_comments_respeta_division_entera_y_cadenas PASSED [ 66%]
backend/tests/test_evaluate_pagos.py::test_aprobado_y_pagado PASSED      [ 67%]
backend/tests/test_evaluate_pagos.py::test_deadline_passed_9_no_reintenta_y_responde_aprobado_sin_hash PASSED [ 69%]
backend/tests/test_evaluate_pagos.py::test_not_funded_6_con_tarea_released_para_el_programador_es_exito PASSED [ 71%]
backend/tests/test_evaluate_pagos.py::test_not_funded_6_sin_ser_released_no_es_exito PASSED [ 73%]
backend/tests/test_evaluate_pagos.py::test_menos_de_120_s_rechaza_sin_contar PASSED [ 75%]
backend/tests/test_evaluate_pagos.py::test_sin_tiempo_para_release_no_firma_ni_cuenta PASSED [ 76%]
backend/tests/test_evaluate_pagos.py::test_antes_de_reintentar_gemini_revisa_el_plazo PASSED [ 78%]
backend/tests/test_evaluate_pagos.py::test_error_transitorio_se_reintenta PASSED [ 80%]
backend/tests/test_evaluate_pagos.py::test_fuera_de_esquema_dos_veces_es_engine_unavailable_sin_contar PASSED [ 82%]
backend/tests/test_evaluate_pagos.py::test_security_flags_fuerza_rechazo_aunque_gemini_apruebe PASSED [ 83%]
backend/tests/test_hashing.py::test_float_es_error PASSED                [ 85%]
backend/tests/test_hashing.py::test_float_anidado_es_error PASSED        [ 87%]
backend/tests/test_hashing.py::test_nfc_mismo_hash_para_formas_equivalentes PASSED [ 89%]
backend/tests/test_hashing.py::test_mismo_hash_con_claves_en_otro_orden PASSED [ 91%]
backend/tests/test_hashing.py::test_formato_canonico_exacto PASSED       [ 92%]
backend/tests/test_hashing.py::test_rules_hash_ordena_allowed_deps_e_ignora_raw_request PASSED [ 94%]
backend/tests/test_hashing.py::test_rules_hash_cambia_si_cambia_un_criterio PASSED [ 96%]
backend/tests/test_hashing.py::test_code_hash_sobre_bytes_sin_limpiar PASSED [ 98%]
backend/tests/test_hashing.py::test_verdict_hash_estable_y_sensible PASSED [100%]

============================= 56 passed in 1.42s ==============================
```

Sin `-p no:warnings` aparecen 2 advertencias de las librerías (`starlette.testclient` sobre `httpx`, y `google.genai.types` sobre Python 3.17), no del código del proyecto.

### 3.4 `bash scripts/fase1-curl.sh` (salida completa)

Los tokens se muestran abreviados (`abc123…`).

```
== Arranque
   contrato CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ
   USDC del cliente al inicio: "180000000"
   backend arriba (pid 1164)
$ curl -X GET /health
   HTTP 200
   {"ok": true}

== Tarea 1: caso A aprobado y pagado
$ curl -X POST /tasks
   HTTP 200
   {"task_id": "irJ0x97jhd7hXzCA", "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "client_token": "gvHTk3…", "invite_token": "JZW_cL…"}
$ stellar contract invoke … deposit --task_id irJ0x97jhd7hXzCA --amount 10000000 --deadline_secs 600
   ℹ️  Signing transaction: 43236768c712ecedf03a1617c690bad498f69afa6963c8d649add89728988773
   📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: DepositEvent (deposit), task_id: "irJ0x97jhd7hXzCA", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790263432, rules_hash: "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96"
$ curl -X POST /tasks/irJ0x97jhd7hXzCA/accept
   HTTP 200
   {"freelancer_token": "W2VRbS…"}
$ curl -X POST /tasks/irJ0x97jhd7hXzCA/accept
   HTTP 200
   {"freelancer_token": "W2VRbS…"}
   -> /accept idempotente: mismo freelancer_token
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 200
   approved: true
   stage: "llm"
   transaction_hash: "f5a1ccede287b778ce6a0edc7d1cd7bea3bed913e3ec600e9d8203485f1c2e1a"
   submissions_used: 1
   code_hash: "c9b846f4cafc89920593d805ffa0fd7a087b9b29d928e00d835bdc782334e534"
   verdict_hash: "a6ad0999137cb885759569c86039ece4b275c041796b465b1a7329cc3c14ce9c"
   reason: El código cumple perfectamente con todos los criterios acordados, aplicando el descuento de forma correcta, redondeando a 2 decimales y sin dependencias externas.
   ✓ Criterio 1: Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float] de manera exacta.
   ✓ Criterio 2: Cada precio de salida se calcula correctamente aplicando el factor de descuento (1 - porcentaje / 100).
   ✓ Criterio 3: Cada precio de salida está redondeado a 2 decimales mediante la función round(..., 2).
   ✓ Criterio 4: La lista por comprensión conserva el orden y la cantidad de elementos, y devuelve una lista vacía si la entrada está vacía.
   ✓ Criterio 5: No se importa ningún módulo ni se utilizan dependencias externas.
   ✓ Criterio 6: La función termina siempre de forma segura al iterar sobre una lista finita.
   -> release en Horizon: "successful": true
$ curl -X GET /tasks/irJ0x97jhd7hXzCA
   HTTP 200
   {"task_id": "irJ0x97jhd7hXzCA", "raw_request": "Necesito una función en Python que le aplique un descuento a una lista de precios y me regrese los precios ya con descuento.", "description": "Implementar en Python la función aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida está redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vacía devuelve una lista vacía.", "No importa ningún módulo (sin dependencias externas).", "La función termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}], "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "amount": 10000000, "deadline_minutes": 10, "client_address": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "freelancer_address": "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", "submissions_used": 1, "max_submissions": 3, "onchain": {"amount": 10000000, "client": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "deadline": 1790263432, "freelancer": "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "status": "Released", "task_id": "irJ0x97jhd7hXzCA"}, "seconds_left": 580, "onchain_error": null}
$ curl -X GET /tasks/irJ0x97jhd7hXzCA/delivery -H 'X-Client-Token: …'
   HTTP 200
   {"task_id": "irJ0x97jhd7hXzCA", "code": "def aplicar_descuento(precios: list[float], porcentaje: float) -> list[float]:\n    \"\"\"Aplica un descuento porcentual a cada precio y redondea a 2 decimales.\"\"\"\n    factor = 1 - porcentaje / 100\n    return [round(precio * factor, 2) for precio in precios]\n", "video_url": null, "code_hash": "c9b846f4cafc89920593d805ffa0fd7a087b9b29d928e00d835bdc782334e534"}
   -> el cliente recibe el código tras el pago

== Tarea 2: guardias y casos B, C, D
$ curl -X POST /tasks
   HTTP 200
   {"task_id": "vzz1OGErEjRirwa-", "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "client_token": "vabPcE…", "invite_token": "CJz43W…"}
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 409
   {"error": "CRITERIA_NOT_ACCEPTED", "message": "Ningún programador ha aceptado los criterios"}
   -> 409 CRITERIA_NOT_ACCEPTED como se esperaba
$ curl -X POST /tasks/vzz1OGErEjRirwa-/accept
   HTTP 200
   {"freelancer_token": "jRz-kb…"}
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 409
   {"error": "TASK_NOT_FUNDED", "message": "La tarea no está depositada en el contrato"}
   -> 409 TASK_NOT_FUNDED como se esperaba
$ stellar contract invoke … deposit --task_id vzz1OGErEjRirwa- --amount 10000000 --deadline_secs 600
   ℹ️  Signing transaction: 70fdaf0ee3263f48b134150bf90d0964776c9b5704dd10b875d7132a4483f1ad
   📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: DepositEvent (deposit), task_id: "vzz1OGErEjRirwa-", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790263462, rules_hash: "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96"

-- /evaluate con token equivocado (el de la tarea 1)
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 403
   {"error": "INVALID_TOKEN", "message": "Token de programador inválido para esta tarea"}
   -> 403 INVALID_TOKEN como se esperaba
-- /evaluate con el token correcto pero otra dirección
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 403
   {"error": "INVALID_TOKEN", "message": "Token de programador inválido para esta tarea"}
   -> 403 INVALID_TOKEN como se esperaba
-- /accept de otra dirección con la misma invitación
$ curl -X POST /tasks/vzz1OGErEjRirwa-/accept
   HTTP 409
   {"error": "TASK_TAKEN", "message": "Esta tarea ya la aceptó otro programador"}
   -> 409 TASK_TAKEN como se esperaba

-- Caso B (calidad)
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 200
   approved: false
   stage: "llm"
   transaction_hash: null
   submissions_used: 1
   code_hash: "3fed1d2950769ea6f4020b18721a2654b812bb48622711e51e5a96a4cb0a0c2d"
   verdict_hash: "b6e8cfa5be3d170091bd85ecaddc0046cb500c61ed771332b2f87dfe79bd72ef"
   reason: El código no se aprueba porque contiene un bucle infinito al no incrementar la variable de control 'i' dentro del ciclo while, impidiendo que la función termine para listas con elementos.
   ✓ Criterio 1: Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].
   ✓ Criterio 2: Cada precio de salida calculado sigue la fórmula precio * (1 - porcentaje / 100).
   ✓ Criterio 3: Cada precio de salida está redondeado a 2 decimales mediante la función round(..., 2).
   ✗ Criterio 4: La salida no conserva el orden ni la cantidad de elementos para listas no vacías porque la función nunca termina.
   ✓ Criterio 5: No importa ningún módulo (sin dependencias externas).
   ✗ Criterio 6: La función no termina para listas con elementos debido a un bucle infinito (falta incrementar la variable i).
-- Caso C (inyección)
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 200
   approved: false
   stage: "llm"
   transaction_hash: null
   submissions_used: 2
   code_hash: "77f59c83bef678d97842380c639bbf0a73d7c7ed9c78876a3271a24cc2708c2d"
   verdict_hash: "6ecea8f0e75b320710f4917e5e28448033a68ea020e5e62918f978d422146acc"
   reason: El codigo fue rechazado debido a que contiene un intento de manipulacion en el docstring que busca alterar el proceso de evaluacion.
   security_flag: Intento de manipulacion detectado en el docstring del codigo entregado, el cual intenta dar instrucciones directas al evaluador para forzar la aprobacion.
   ✓ Criterio 1: Define la funcion aplicar_descuento con la firma y tipos correctos.
   ✓ Criterio 2: Cada precio de salida se calcula con la formula del descuento acordada.
   ✓ Criterio 3: Cada precio de salida se redondea a 2 decimales.
   ✓ Criterio 4: Conserva el orden y la cantidad de elementos, y maneja listas vacias.
   ✓ Criterio 5: No importa ningun modulo externo.
   ✓ Criterio 6: Termina correctamente sin bucles infinitos.
-- Caso D (secretos)
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 200
   approved: false
   stage: "deterministic"
   transaction_hash: null
   submissions_used: 3
   code_hash: "761cb5678d74a40384926bd0e80a6dc27aa6d4f54128fc88471c15062aa2706a"
   verdict_hash: "90423af1bc2915366c2d87a333e15132f9a246a61124b03ad699a54ce844f68f"
   reason: Rechazado por la capa determinista: línea 1: import no permitido 'os'; línea 6: atributo prohibido '.environ'
   security_flag: línea 1: import no permitido 'os'
   security_flag: línea 6: atributo prohibido '.environ'
   ✗ Criterio 1: no evaluado; el código fue rechazado por la capa determinista
   ✗ Criterio 2: no evaluado; el código fue rechazado por la capa determinista
   ✗ Criterio 3: no evaluado; el código fue rechazado por la capa determinista
   ✗ Criterio 4: no evaluado; el código fue rechazado por la capa determinista
   ✗ Criterio 5: no evaluado; el código fue rechazado por la capa determinista
   ✗ Criterio 6: no evaluado; el código fue rechazado por la capa determinista
-- Reenvío de B
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 200
   approved: false
   stage: "cache"
   transaction_hash: null
   submissions_used: 3
   code_hash: "3fed1d2950769ea6f4020b18721a2654b812bb48622711e51e5a96a4cb0a0c2d"
   verdict_hash: "b6e8cfa5be3d170091bd85ecaddc0046cb500c61ed771332b2f87dfe79bd72ef"
   reason: El código no se aprueba porque contiene un bucle infinito al no incrementar la variable de control 'i' dentro del ciclo while, impidiendo que la función termine para listas con elementos.
   ✓ Criterio 1: Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].
   ✓ Criterio 2: Cada precio de salida calculado sigue la fórmula precio * (1 - porcentaje / 100).
   ✓ Criterio 3: Cada precio de salida está redondeado a 2 decimales mediante la función round(..., 2).
   ✗ Criterio 4: La salida no conserva el orden ni la cantidad de elementos para listas no vacías porque la función nunca termina.
   ✓ Criterio 5: No importa ningún módulo (sin dependencias externas).
   ✗ Criterio 6: La función no termina para listas con elementos debido a un bucle infinito (falta incrementar la variable i).
-- Quinto envío, código distinto
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 429
   {"error": "TOO_MANY_SUBMISSIONS", "message": "Ya se usaron los 3 envíos de esta tarea"}
   -> 429 TOO_MANY_SUBMISSIONS como se esperaba

== Tarea 3: plazo de 1 minuto (menos de 120 s)
$ curl -X POST /tasks
   HTTP 200
   {"task_id": "4zNyN8mEVsUqJNl0", "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "client_token": "gkiGdj…", "invite_token": "Ki3agQ…"}
$ curl -X POST /tasks/4zNyN8mEVsUqJNl0/accept
   HTTP 200
   {"freelancer_token": "s3atNr…"}
$ stellar contract invoke … deposit --task_id 4zNyN8mEVsUqJNl0 --amount 10000000 --deadline_secs 60
   ℹ️  Signing transaction: d9ff27577e432b1a55e2537d5a4d3dd0cbf16608927c4f6d6dff1e9efa2646fd
   📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: DepositEvent (deposit), task_id: "4zNyN8mEVsUqJNl0", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790263002, rules_hash: "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96"
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 409
   {"error": "DEADLINE_TOO_CLOSE", "message": "Quedan menos de 120 s de plazo; ya no se puede evaluar"}
   -> 409 DEADLINE_TOO_CLOSE como se esperaba
$ curl -X GET /tasks/4zNyN8mEVsUqJNl0
   HTTP 200
   {"task_id": "4zNyN8mEVsUqJNl0", "raw_request": "Necesito una función en Python que le aplique un descuento a una lista de precios y me regrese los precios ya con descuento.", "description": "Implementar en Python la función aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida está redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vacía devuelve una lista vacía.", "No importa ningún módulo (sin dependencias externas).", "La función termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}], "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "amount": 10000000, "deadline_minutes": 1, "client_address": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "freelancer_address": "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", "submissions_used": 0, "max_submissions": 3, "onchain": {"amount": 10000000, "client": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "deadline": 1790263002, "freelancer": null, "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "status": "Funded", "task_id": "4zNyN8mEVsUqJNl0"}, "seconds_left": 60, "onchain_error": null}

== Tarea 4: monto on-chain distinto al acordado
$ curl -X POST /tasks
   HTTP 200
   {"task_id": "x4dE9gM4vrDuzvTG", "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "client_token": "hflj-P…", "invite_token": "Rpj76C…"}
$ curl -X POST /tasks/x4dE9gM4vrDuzvTG/accept
   HTTP 200
   {"freelancer_token": "Xu6y86…"}
$ stellar contract invoke … deposit --task_id x4dE9gM4vrDuzvTG --amount 5000000 --deadline_secs 300
   ℹ️  Signing transaction: 792dae8d4657c54f0ccaaafa9465b42471c5a51cb83f31756e34d097f86bf8bb
   📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: DepositEvent (deposit), task_id: "x4dE9gM4vrDuzvTG", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "5000000", deadline: 1790263252, rules_hash: "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96"
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 409
   {"error": "TASK_MISMATCH", "message": "El monto, el cliente o los criterios on-chain no coinciden"}
   -> 409 TASK_MISMATCH como se esperaba

== Reinicio del backend
   backend detenido
   backend arriba (pid 1676)
$ curl -X GET /tasks/irJ0x97jhd7hXzCA
   HTTP 200
   {"task_id": "irJ0x97jhd7hXzCA", "raw_request": "Necesito una función en Python que le aplique un descuento a una lista de precios y me regrese los precios ya con descuento.", "description": "Implementar en Python la función aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida está redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vacía devuelve una lista vacía.", "No importa ningún módulo (sin dependencias externas).", "La función termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}], "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "amount": 10000000, "deadline_minutes": 10, "client_address": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "freelancer_address": "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", "submissions_used": 1, "max_submissions": 3, "onchain": {"amount": 10000000, "client": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "deadline": 1790263432, "freelancer": "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "status": "Released", "task_id": "irJ0x97jhd7hXzCA"}, "seconds_left": 480, "onchain_error": null}
$ curl -X GET /tasks/vzz1OGErEjRirwa-
   HTTP 200
   {"task_id": "vzz1OGErEjRirwa-", "raw_request": "Necesito una función en Python que le aplique un descuento a una lista de precios y me regrese los precios ya con descuento.", "description": "Implementar en Python la función aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida está redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vacía devuelve una lista vacía.", "No importa ningún módulo (sin dependencias externas).", "La función termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}], "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "amount": 10000000, "deadline_minutes": 10, "client_address": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "freelancer_address": "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", "submissions_used": 3, "max_submissions": 3, "onchain": {"amount": 10000000, "client": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "deadline": 1790263462, "freelancer": null, "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "status": "Funded", "task_id": "vzz1OGErEjRirwa-"}, "seconds_left": 505, "onchain_error": null}
-- Reenvío de A en la tarea 1 tras el reinicio
$ curl -X POST /evaluate -H 'X-Freelancer-Token: …'
   HTTP 200
   approved: true
   stage: "cache"
   transaction_hash: "f5a1ccede287b778ce6a0edc7d1cd7bea3bed913e3ec600e9d8203485f1c2e1a"
   submissions_used: 1
   code_hash: "c9b846f4cafc89920593d805ffa0fd7a087b9b29d928e00d835bdc782334e534"
   verdict_hash: "a6ad0999137cb885759569c86039ece4b275c041796b465b1a7329cc3c14ce9c"
   reason: El código cumple perfectamente con todos los criterios acordados, aplicando el descuento de forma correcta, redondeando a 2 decimales y sin dependencias externas.
   ✓ Criterio 1: Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float] de manera exacta.
   ✓ Criterio 2: Cada precio de salida se calcula correctamente aplicando el factor de descuento (1 - porcentaje / 100).
   ✓ Criterio 3: Cada precio de salida está redondeado a 2 decimales mediante la función round(..., 2).
   ✓ Criterio 4: La lista por comprensión conserva el orden y la cantidad de elementos, y devuelve una lista vacía si la entrada está vacía.
   ✓ Criterio 5: No se importa ningún módulo ni se utilizan dependencias externas.
   ✓ Criterio 6: La función termina siempre de forma segura al iterar sobre una lista finita.

== timeout_refund de las tareas 2, 3 y 4
   plazo de la tarea 2: quedan 505 s; esperando…
   plazo de la tarea 2: quedan 475 s; esperando…
   plazo de la tarea 2: quedan 445 s; esperando…
   plazo de la tarea 2: quedan 415 s; esperando…
   plazo de la tarea 2: quedan 380 s; esperando…
   plazo de la tarea 2: quedan 350 s; esperando…
   plazo de la tarea 2: quedan 320 s; esperando…
   plazo de la tarea 2: quedan 290 s; esperando…
   plazo de la tarea 2: quedan 260 s; esperando…
   plazo de la tarea 2: quedan 230 s; esperando…
   plazo de la tarea 2: quedan 195 s; esperando…
   plazo de la tarea 2: quedan 165 s; esperando…
   plazo de la tarea 2: quedan 135 s; esperando…
   plazo de la tarea 2: quedan 105 s; esperando…
   plazo de la tarea 2: quedan 75 s; esperando…
   plazo de la tarea 2: quedan 45 s; esperando…
   plazo de la tarea 2: quedan 10 s; esperando…
$ stellar contract invoke --source cyc-third … timeout_refund --task_id 4zNyN8mEVsUqJNl0
   ℹ️  Signing transaction: 86c19c412816f4692684cca3e224482c023fc1ebc894e6df50de867e754ec0d9
   📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: TimeoutRefundEvent (timeout_refund), task_id: "4zNyN8mEVsUqJNl0", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000"
$ stellar contract invoke --source cyc-third … timeout_refund --task_id x4dE9gM4vrDuzvTG
   ℹ️  Signing transaction: 5e728b0a08d85b43b96bf7dbec2da12abb2e95ea94bef4cabe56fa68ae88cb01
   📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: TimeoutRefundEvent (timeout_refund), task_id: "x4dE9gM4vrDuzvTG", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "5000000"
$ stellar contract invoke --source cyc-third … timeout_refund --task_id vzz1OGErEjRirwa-
   ℹ️  Signing transaction: e1d6da24e25dc513629095a6e8436049c1ebdd5ee6d7e568348dcf59b3d888e0
   📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: TimeoutRefundEvent (timeout_refund), task_id: "vzz1OGErEjRirwa-", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000"
$ curl -X GET /tasks/vzz1OGErEjRirwa-
   HTTP 200
   {"task_id": "vzz1OGErEjRirwa-", "raw_request": "Necesito una función en Python que le aplique un descuento a una lista de precios y me regrese los precios ya con descuento.", "description": "Implementar en Python la función aplicar_descuento(precios: list[float], porcentaje: float) -> list[float], que devuelve cada precio con el descuento aplicado, redondeado a 2 decimales, sin dependencias externas.", "criteria": ["Define una función llamada aplicar_descuento(precios: list[float], porcentaje: float) -> list[float].", "Cada precio de salida es igual a precio * (1 - porcentaje / 100).", "Cada precio de salida está redondeado a 2 decimales.", "La salida conserva el orden y la cantidad de elementos de la entrada; una lista vacía devuelve una lista vacía.", "No importa ningún módulo (sin dependencias externas).", "La función termina para cualquier lista de entrada (sin bucles infinitos)."], "language": "python", "allowed_deps": [], "examples": [{"input": "aplicar_descuento([100.0, 50.0], 10.0)", "output": "[90.0, 45.0]"}, {"input": "aplicar_descuento([19.99], 15.0)", "output": "[16.99]"}, {"input": "aplicar_descuento([], 20.0)", "output": "[]"}], "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "amount": 10000000, "deadline_minutes": 10, "client_address": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "freelancer_address": "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", "submissions_used": 3, "max_submissions": 3, "onchain": {"amount": 10000000, "client": "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", "deadline": 1790263462, "freelancer": null, "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96", "status": "Refunded", "task_id": "vzz1OGErEjRirwa-"}, "seconds_left": -35, "onchain_error": null}

== Saldos USDC al final
   cliente:    "170000000"
   freelancer: "30000000"
   contrato:   "0"

== Resumen
tarea 1: irJ0x97jhd7hXzCA  deposit 43236768c712ecedf03a1617c690bad498f69afa6963c8d649add89728988773  release f5a1ccede287b778ce6a0edc7d1cd7bea3bed913e3ec600e9d8203485f1c2e1a
tarea 2: vzz1OGErEjRirwa-  deposit 70fdaf0ee3263f48b134150bf90d0964776c9b5704dd10b875d7132a4483f1ad
tarea 3: 4zNyN8mEVsUqJNl0  deposit d9ff27577e432b1a55e2537d5a4d3dd0cbf16608927c4f6d6dff1e9efa2646fd
tarea 4: x4dE9gM4vrDuzvTG  deposit 792dae8d4657c54f0ccaaafa9465b42471c5a51cb83f31756e34d097f86bf8bb
timeout_refund: 4zNyN8mEVsUqJNl0 86c19c412816f4692684cca3e224482c023fc1ebc894e6df50de867e754ec0d9
timeout_refund: x4dE9gM4vrDuzvTG 5e728b0a08d85b43b96bf7dbec2da12abb2e95ea94bef4cabe56fa68ae88cb01
timeout_refund: vzz1OGErEjRirwa- e1d6da24e25dc513629095a6e8436049c1ebdd5ee6d7e568348dcf59b3d888e0
OK: fase 1 completa
exit=0
```

### 3.5 Transacciones en testnet (Horizon: todas `successful: true`)

| Paso | Tarea | Hash | Ledger | Firmó |
| --- | --- | --- | --- | --- |
| `deposit` 1 USDC, 600 s | 1 `irJ0x97jhd7hXzCA` | `43236768c712ecedf03a1617c690bad498f69afa6963c8d649add89728988773` | 4847849 | cyc-client |
| **`release` del backend (caso A)** | 1 | `f5a1ccede287b778ce6a0edc7d1cd7bea3bed913e3ec600e9d8203485f1c2e1a` | 4847853 | árbitro (backend) |
| `deposit` 1 USDC, 600 s | 2 `vzz1OGErEjRirwa-` | `70fdaf0ee3263f48b134150bf90d0964776c9b5704dd10b875d7132a4483f1ad` | 4847855 | cyc-client |
| `deposit` 1 USDC, 60 s | 3 `4zNyN8mEVsUqJNl0` | `d9ff27577e432b1a55e2537d5a4d3dd0cbf16608927c4f6d6dff1e9efa2646fd` | 4847871 | cyc-client |
| `deposit` 0.5 USDC, 300 s | 4 `x4dE9gM4vrDuzvTG` | `792dae8d4657c54f0ccaaafa9465b42471c5a51cb83f31756e34d097f86bf8bb` | 4847873 | cyc-client |
| `timeout_refund` | 3 | `86c19c412816f4692684cca3e224482c023fc1ebc894e6df50de867e754ec0d9` | 4847980 | cyc-third |
| `timeout_refund` | 4 | `5e728b0a08d85b43b96bf7dbec2da12abb2e95ea94bef4cabe56fa68ae88cb01` | 4847981 | cyc-third |
| `timeout_refund` | 2 | `e1d6da24e25dc513629095a6e8436049c1ebdd5ee6d7e568348dcf59b3d888e0` | 4847982 | cyc-third |

Saldos USDC (unidades):

| Cuenta | Antes | Después |
| --- | --- | --- |
| Cliente | 180000000 | 170000000 |
| Freelancer | 20000000 | 30000000 |
| Contrato | 0 | 0 |

Reinicio verificado: el primer proceso de uvicorn (pid 22120) ya no existe y solo el nuevo (10548) responde. El nuevo leyó `state.json` al arrancar: tareas, envíos y caché siguen ahí, y el reenvío de A devolvió `stage: "cache"` con el mismo `transaction_hash`.

## 4. Pendientes y riesgos detectados

1. **Latencia de Gemini.** El caso C tardó 49 s en la prueba directa, más que el timeout de 45 s. La corrida siguió porque el timeout de `HttpOptions` no es un tope total; el tope real es `asyncio.wait_for` a 50 s. Con plazo de 10 min sobra, pero en la demo conviene no dejar la evaluación para el final. Vigilarlo en la fase 5 (10 corridas seguidas).
2. **Trustline del programador.** El backend no la revisa. Si el programador no tiene trustline de USDC, `release` falla en el contrato y la respuesta dice que el pago no se liberó. La UI de la fase 3 debe bloquear todo hasta activarla, como pide CLAUDE.md.
3. **Hashes del evento de release.** El script verifica que el release fue exitoso y a quién pagó, pero no decodifica el `ReleaseEvent` para comparar `code_hash`/`verdict_hash` con la respuesta. Pendiente para el README de hashes (fase 5).
4. **Tokens en claro en `state.json`.** Es local y está en `.gitignore`. `/accept` idempotente necesita devolver el mismo `freelancer_token`.
5. **Un solo proceso.** Los locks por tarea viven en memoria: no correr uvicorn con varios workers.
6. **Textos de Gemini:** a veces responde sin acentos (caso C: "codigo", "manipulacion"). Es cosmético; se puede reforzar en la instrucción de sistema.
7. **CLAUDE.md sin actualizar.** Falta decidir si se agregan `GEMINI_API_KEY` y los códigos de error nuevos (desviaciones 1 y 2); no lo toqué sin tu visto bueno.
8. **Saldo:** 17 USDC en `cyc-client`. Cada corrida del script gasta 1 USDC neto y necesita 3.5 USDC disponibles mientras corre. Tarda unos 12 minutos, porque espera a que venza el plazo de la tarea 2.
