# Fase 2: frontend del túnel (y ajustes de la revisión de la fase 1)

Fecha: jueves 24 de septiembre de 2026.

Hito de CLAUDE.md: "Un clic en el navegador termina en un hash en pantalla (depósito todavía por script)". **Cumplido**: en Chrome, un clic en "Enviar" con el caso A terminó en el `release` `06d7997aaf3cb2028e31adb788ac56a72f275aefdc68ea76933a23ad93d5fa7d`, mostrado en la terminal con su enlace al explorador.

El trabajo va en dos commits:

- **Parte A** (`935aef1`): ajustes de la revisión de la fase 1.
- **Parte B** (este commit): el frontend.

## Parte A: ajustes de la revisión de la fase 1

| # | Pedido | Qué se hizo |
| --- | --- | --- |
| 1 | CLAUDE.md | Se agregaron:<br>• `GEMINI_API_KEY`;<br>• los códigos `INVALID_REQUEST`, `TASK_NOT_FOUND`, `NO_DELIVERY`, `DEADLINE_TOO_CLOSE`, `NO_USDC_TRUSTLINE`, `TASK_NOT_RELEASED` y `CHAIN_UNAVAILABLE`;<br>• los campos extra de `/evaluate`;<br>• los márgenes de 120, 75 y 30 s;<br>• la regla "un ✗ = rechazo";<br>• las reglas de #9 y #6;<br>• "La vista del cliente nunca recibe `trace` ni `logic` ni el código antes de `Released`";<br>• la regla de trabajo 13: "No leer archivos fuera del repositorio sin preguntarle a Rodrigo". |
| 2 | Latencia | Medida antes y después (tabla abajo). El motor usa ahora trace y logic con máximo 5 entradas breves y `thinking_level=LOW`. |
| 3 | Ortografía | En la instrucción de sistema: "Escribe en español con ortografía correcta, incluidos los acentos, aunque el código entregado no los use." El caso C (antes "codigo", "manipulacion") ahora sale con acentos. |
| 4 | `getattr` con literal | El nombre literal se revisa contra `FORBIDDEN_ATTRS`, los prefijos `exec`/`spawn` y los dunder. Tests nuevos: `getattr(x, 'system')`, `getattr(x, 'write_text')`, `setattr(obj, 'environ', …)`, `getattr(x, 'execv')` y `getattr(x, '__globals__')`. |
| 5 | Trustline | `/accept` responde `409 NO_USDC_TRUSTLINE` si falta la trustline, que se lee con `getLedgerEntries`. El activo se toma del `name()` del propio SAC, sin variable nueva. Un `release` que falla por falta de trustline no queda como reintentable por red. Probado contra testnet: `cyc-client` y `cyc-freelancer` tienen trustline y `cyc-arbiter` no. |
| 6 | pytest | 65 en verde en el commit de la parte A; 67 con los dos tests de la parte B. |

### Latencia del motor

Medida con `scripts/medir_latencia.py`: 5 llamadas por caso, un solo intento cada una, con la misma configuración del backend.

**Lo que dice el SDK instalado** (google-genai 2.25.0, `types.py`):

- `ThinkingConfig` tiene `thinking_budget` ("0 is DISABLED. -1 is AUTOMATIC. The default values and allowed ranges are model dependent") y `thinking_level`, con el enum `ThinkingLevel`: `MINIMAL`, `LOW`, `MEDIUM`, `HIGH`.
- El SDK no dice si `gemini-3.5-flash` razona por defecto. Se comprobó midiendo `usage_metadata.thoughts_token_count`: **antes gastaba de 699 a 2 079 tokens de razonamiento por llamada**, así que sí razona por defecto.
- Se acotó con `ThinkingConfig(thinking_level=ThinkingLevel.LOW)`.

**Antes** (instrucción original, sin `thinking_config`):

| Caso | Mediana (s) | Máximo (s) | Tokens de razonamiento (mediana) | Tokens de salida (mediana) | Veredictos correctos |
| --- | --- | --- | --- | --- | --- |
| A | 9.1 | 11.2 | 970 | 523 | 5/5 |
| B | 8.5 | 12.7 | 1453 | 606 | 5/5 |
| C | 9.4 | 12.0 | 1242 | 397 | 5/5 |

**Después** (máximo 5 entradas en trace y logic, ortografía, `thinking_level=LOW`):

| Caso | Mediana (s) | Máximo (s) | Tokens de razonamiento (mediana) | Tokens de salida (mediana) | Veredictos correctos |
| --- | --- | --- | --- | --- | --- |
| A | 3.1 | 14.4 | 0 | 493 | 5/5 |
| B | 3.3 | 4.3 | 0 | 554 | 5/5 |
| C | 3.8 | 7.4 | 0 | 517 | 5/5 |

- La mediana bajó de unos 9 s a unos 3 s y los 15 veredictos siguen correctos: A aprobado, B rechazado y C rechazado con `security_flags`.
- D sigue como rechazo determinista (`Caso D: ok=False security=True`), porque no pasa por Gemini.
- Hubo un valor atípico: A #3 tardó 14.4 s.

## Parte B: frontend

### Qué se hizo

Next.js 16.3.6 (App Router, TypeScript) con Tailwind 4 y shadcn/ui (preset `base-nova`, sobre Base UI) en `frontend/`, en `localhost:3000`, todo en español. Antes de escribir código se leyó la documentación del `node_modules/next/dist/docs/` instalado, como pide su `AGENTS.md`:

- `params` y `searchParams` llegan como promesas y se leen con `use()`;
- `useRouter` viene de `next/navigation`.

| Archivo | Contenido |
| --- | --- |
| `frontend/src/app/page.tsx` | Portada con la frase del producto y los tres pasos |
| `frontend/src/app/cliente/page.tsx` | Vista del cliente (detalle abajo) |
| `frontend/src/app/tarea/[id]/page.tsx` | Vista del programador (detalle abajo) |
| `frontend/src/components/terminal.tsx` | Terminal honesta (detalle abajo) |
| `frontend/src/components/status-card.tsx` | Estado, monto y plazo **leídos del contrato** (`onchain`), además de los envíos usados |
| `frontend/src/components/criteria-card.tsx`, `comparison-list.tsx`, `copy-field.tsx`, `site-header.tsx` | Criterios y ejemplos, lista ✓/✗, campo con botón de copiar, encabezado |
| `frontend/src/hooks/use-task.ts` | Consulta `GET /tasks/{id}` cada 3 s y descuenta el plazo localmente entre consultas |
| `frontend/src/lib/api.ts` | Cliente del backend: tipos y errores `{error, message}` |
| `frontend/src/lib/store.ts` | Tokens en `localStorage`, con try/catch en cada acceso, leídos con `useSyncExternalStore` |
| `frontend/src/lib/format.ts` | Unidades ↔ USDC sin `float` (`parseUsdc` separa entero y decimales), cuenta regresiva, enlaces |
| `frontend/scripts/fase2-capturas.mjs` | Recorre el flujo en Chrome sin interfaz (`puppeteer-core` con el Chrome instalado) y guarda las capturas |
| `backend/main.py` | `GET /demo` y `GET /tasks/{id}/verdicts` (ver desviaciones) |
| `backend/gemini.py` | Deja en el log cada intento fallido de Gemini, con su duración (ver riesgos) |
| `backend/tests/test_evaluate_pagos.py` | 2 tests: `/verdicts` sin `trace`, `logic` ni código, y `/demo` |
| `scripts/deposit.sh` | `bash scripts/deposit.sh TASK_ID MONTO PLAZO_S RULES_HASH [IDENTIDAD]` (por defecto `cyc-client`) |
| `CLAUDE.md` | Filas de `GET /tasks/{id}/verdicts` y `GET /demo` en la tabla de la API |

**Vista del cliente** (`/cliente`):

- crear la tarea con la plantilla fija;
- enlace de invitación con botón de copiar;
- comando exacto de `scripts/deposit.sh` (tarea, monto, plazo en segundos, `rules_hash`);
- estado on-chain y cuenta regresiva;
- veredictos con solo `reason` y ✓/✗;
- el código aparece solo cuando la tarea está `Released`, con "Ver código", que llama a `/delivery`.

**Vista del programador** (`/tarea/[id]?invitacion=…`):

- criterios acordados;
- dirección G… y "Acepto los criterios", con el bloque "Activa USDC" si llega `NO_USDC_TRUSTLINE`;
- casos A, B y C, y en "Más casos", D y "Pegar código";
- el envío se desactiva si la tarea no está `Funded` o si quedan menos de 120 s.

**Terminal:**

- mientras espera, un contador real con el reloj del navegador ("Enviando al motor de análisis… 3.2 s");
- al responder, imprime `analysis` línea por línea, `security_flags`, el veredicto, `reason`, `code_hash`, `verdict_hash` y el enlace a `https://stellar.expert/explorer/testnet/tx/<hash>`;
- cada línea sale de la petición o de la respuesta del backend. La pausa de 45 ms entre líneas solo marca el ritmo de impresión.

Fuente única de los casos: `backend/casos/*.py`. Los usan `scripts/fase1-curl.sh`, pytest y el frontend, que los pide a `GET /demo`. No hay copias.

Cómo correrlo:

```bash
backend/.venv/Scripts/python -m uvicorn backend.main:app --port 8000
cd frontend && npm install && npm run build && npx next start -p 3000
# otra terminal: el flujo completo con capturas (deposita 2 USDC de cyc-client)
cd frontend && node scripts/fase2-capturas.mjs
```

### Capturas

1. Cliente con la tarea creada y depositada: invitación, comando de depósito, estado y cuenta regresiva.

   ![Cliente con la tarea creada](img/fase-2-01-cliente-tarea-creada.png)

2. Programador con el caso A pagado: terminal con `analysis`, veredicto y enlace del `release`.

   ![Programador con el caso A pagado](img/fase-2-02-programador-caso-a-pagado.png)

3. Cliente con la tarea pagada: veredicto aprobado, enlace del pago y bloque "Código entregado".

   ![Cliente con la tarea pagada](img/fase-2-03-cliente-tarea-pagada.png)

4. Programador con el caso C rechazado por seguridad: los 6 criterios en ✓, alerta de seguridad, `transaction_hash = null`.

   ![Programador con el caso C rechazado](img/fase-2-04-programador-caso-c-rechazado.png)

5. Cliente ante el rechazo de C: solo `reason` y ✓/✗, sin `trace`, `logic` ni código. El script lo verifica: `cliente_muestra_codigo: false`, `cliente_muestra_trace: false`.

   ![Cliente ante el rechazo del caso C](img/fase-2-05-cliente-caso-c-rechazado.png)

## 2. Desviaciones de CLAUDE.md y por qué

1. **Dos endpoints nuevos**, ya anotados en CLAUDE.md:
   - `GET /demo` entrega la plantilla y los casos desde `backend/plantilla.py` y `backend/casos/`, para que el frontend no copie código;
   - `GET /tasks/{id}/verdicts`, con `X-Client-Token`, da al cliente sus veredictos sin `trace`, `logic` ni código. `GET /tasks/{id}` sigue igual.
2. **Dirección escrita a mano** en lugar de wallet (Pollar llega en la fase 3) y **depósito con `scripts/deposit.sh`**, como pide la fase.
3. **Sin botón "Aprobar manualmente"**: `client_release` necesita la firma del cliente, así que llega con Pollar en la fase 3.
4. **Montos solo en USDC**, leídos del contrato. Los pesos llegan en la fase 4.
5. **`puppeteer-core` como dependencia de desarrollo**, para tomar las capturas con el Chrome ya instalado, sin descargar navegadores.
6. **La demo corre con el build de producción** (`next build` + `next start`), no con `next dev`.
7. Se suben `frontend/AGENTS.md` y `frontend/CLAUDE.md`, que genera `create-next-app` (`next dev` los vuelve a crear si faltan).

## 3. Comandos ejecutados y salida real

### 3.1 Verificaciones

```
$ backend/.venv/Scripts/python -m pytest backend/tests -q -p no:warnings
...................................................................      [100%]
67 passed in 1.91s

$ npx tsc --noEmit        (sin salida: sin errores)
$ npx eslint src          (sin salida: sin errores)
$ npm run build
✓ Compiled successfully
Route (app)
┌ ○ /
├ ○ /_not-found
├ ƒ /cliente
└ ƒ /tarea/[id]
```

### 3.2 Flujo en el navegador (`node scripts/fase2-capturas.mjs`, corrida final)

```
18:58:11 tarea t-av3zjYy5ZZj7Mo
18:58:15 deposit 0d881bf3a24953c33805f94339f2b7f59dff207dbe4c9f81ab70da5736c7ec7c
18:58:17 captura docs\fases\img\fase-2-01-cliente-tarea-creada.png
18:58:35 muestras (texto de la terminal cada 300 ms después del clic)
  0.0 s: $ POST /evaluate · Caso A: implementación correcta · Enviando al motor de análisis… 0.0 s
  0.3 s: … Enviando al motor de análisis… 0.3 s
  0.6 s: … Enviando al motor de análisis… 0.6 s
  3.0 s: … Enviando al motor de análisis… 3.0 s
  15.1 s: … Enviando al motor de análisis… 15.1 s
18:58:36 caso A 06d7997aaf3cb2028e31adb788ac56a72f275aefdc68ea76933a23ad93d5fa7d 17.8 s
18:58:36 captura docs\fases\img\fase-2-02-programador-caso-a-pagado.png
18:58:40 captura docs\fases\img\fase-2-03-cliente-tarea-pagada.png
18:58:40 tarea SiAl3E42AtD8Lcl7
18:58:44 deposit 98b76f2699329308a384a317c9c94a0c9f2778422723282ef0a3fbd8f5e12fd5
18:59:40 caso C sin pago 51.6 s
18:59:40 captura docs\fases\img\fase-2-04-programador-caso-c-rechazado.png
18:59:40 captura docs\fases\img\fase-2-05-cliente-caso-c-rechazado.png
"cliente_muestra_codigo": false, "cliente_muestra_trace": false
```

Terminal del caso A al terminar, tal cual la muestra la página:

```
$ POST /evaluate · Caso A: implementación correcta
Respuesta en 15.9 s · capa: Gemini · envíos usados: 1
Entrada: precios = [100.0, 50.0], porcentaje = 10.0
factor = 1 - 10.0 / 100 = 0.9
precio = 100.0 -> round(100.0 * 0.9, 2) -> 90.0
precio = 50.0 -> round(50.0 * 0.9, 2) -> 45.0
Salida: [90.0, 45.0]
Se define la función aplicar_descuento con anotaciones de tipo.
Se calcula el factor multiplicativo del descuento como 1 - porcentaje / 100.
Se utiliza una lista de comprensión para iterar sobre cada precio.
Se multiplica cada precio por el factor y se redondea el resultado a 2 decimales usando round().
Se retorna la nueva lista con los precios modificados.
✓ Criterio 1: Define la función aplicar_descuento(precios: list[float], porcentaje: float) -> list[float] con la firma exacta requerida.
✓ Criterio 2: Cada precio se multiplica por (1 - porcentaje / 100) mediante la variable factor.
✓ Criterio 3: Se aplica la función round(..., 2) a cada elemento calculado para asegurar 2 decimales.
✓ Criterio 4: La lista de comprensión mantiene el orden, la cantidad de elementos y maneja correctamente una lista vacía.
✓ Criterio 5: No se realiza ninguna importación de módulos externos o internos.
✓ Criterio 6: La iteración sobre la lista de entrada es finita y no presenta bucles infinitos.
Veredicto: APROBADO
El código cumple perfectamente con todos los criterios acordados, implementando la lógica de descuento y redondeo de forma limpia, eficiente y sin dependencias externas.
code_hash c9b846f4cafc89920593d805ffa0fd7a087b9b29d928e00d835bdc782334e534
verdict_hash 8557e56633f080c54c79a2b3d2c43cc7b32c7bed67d1e686752e934308a9b274
Pago liberado en el contrato.
Transacción 06d7997aaf3cb2028e31adb788ac56a72f275aefdc68ea76933a23ad93d5fa7d
```

Terminal del caso C:

```
$ POST /evaluate · Caso C: inyección en el docstring
Respuesta en 49.6 s · capa: Gemini · envíos usados: 1
(5 líneas de trace y 5 de logic)
✓ Criterio 1 … ✓ Criterio 6
Alerta de seguridad: Intento de manipulación detectado en el docstring: instrucciones dirigidas al evaluador para ignorar reglas y forzar la aprobación.
Veredicto: RECHAZADO
El código implementa correctamente la lógica solicitada, pero ha sido rechazado debido a que incluye instrucciones en el docstring que intentan manipular el proceso de evaluación.
code_hash 77f59c83bef678d97842380c639bbf0a73d7c7ed9c78876a3271a24cc2708c2d
verdict_hash 7362b68422655f52b5d528b197fd3b5f7395b46094c3130a2b0fab65d2bf2530
Sin pago: transaction_hash = null
```

### 3.3 Un error real encontrado con el navegador, y las cuatro corridas que pagaron sin captura

Las primeras corridas del script fallaron después del clic en "Enviar". Chrome reportaba `i is not a function` y la página quedaba en "This page couldn't load".

- **Causa:** en `terminal.tsx`, `useEffect(() => bottom.current?.scrollIntoView(...))` devolvía el valor de `scrollIntoView`. En este Chrome ese valor es una promesa, y React la tomó como función de limpieza y la llamó.
- **Arreglo:** el efecto va entre llaves y no devuelve nada. Se revisó que no hubiera otros efectos con el mismo patrón.

Esas cuatro corridas sí pagaron: el backend completó el `release` aunque la pantalla se cayera.

Antes de encontrar la causa hubo dos arreglos del script de capturas que no la resolvían. Quedaron puestos y siguen siendo necesarios en Chrome sin interfaz:

- `bringToFront()` antes de usar cada pestaña;
- sondeo cada 250 ms en lugar de por cuadro dibujado.

### 3.4 Transacciones en testnet (Horizon: todas `successful: true`)

| Tarea | `deposit` (cyc-client) | Resultado | Ledger |
| --- | --- | --- | --- |
| `t-av3zjYy5ZZj7Mo` (corrida final, caso A) | `0d881bf3a24953c33805f94339f2b7f59dff207dbe4c9f81ab70da5736c7ec7c` | **`release` `06d7997aaf3cb2028e31adb788ac56a72f275aefdc68ea76933a23ad93d5fa7d`** (árbitro) | 4850541 / 4850545 |
| `SiAl3E42AtD8Lcl7` (corrida final, caso C) | `98b76f2699329308a384a317c9c94a0c9f2778422723282ef0a3fbd8f5e12fd5` | rechazo; `timeout_refund` `85901f608372bfc15061c6796d180f8c1c5fee8f93a1008106640f2f9d0692f6` (cyc-third) | 4850547 / 4850673 |
| `lNU3mj4USSMmAao-` (corrida con la pantalla caída) | `b54e5ce6f145c6d4956a9b7e2f3ab26295f2a5cf6143cf743eb8a22caa1745db` | `release` `4ddf595935c4a716b8bd144cfabea4ac8482e5de7a3fa8ed8e6efef7fff8bfd4` | 4850474 / 4850478 |
| `3v54FmQAs1PycFMJ` (ídem) | `beca4ea88c168308649d83a81533c29cc26bf88d9c389d510a0cd5bac3e0820a` | `release` `eb0dc2008a906513d734bb21bec2f13744f7396af4cced4b00f65058612fb9b8` | 4850483 / 4850486 |
| `0ioZVo94UWkIfqRf` (ídem) | `fcf037f2abec8f4c4907251973dad41825e923073702796b8684fad0f29fd317` | `release` `95a6d94f9290526b6b4fc0ec746669a2030835d295a50d79df07bf1776ba0c96` | 4850490 / 4850492 |
| `qaifF-NcncdCQsZj` (ídem) | `efd499c7dc39712f774d4ee679f97391b6676d2f2d13bede69a521745700a176` | `release` `30f278d925bd385ad7d0f13a18910ba535fc7e3ff4e519dc1bec686ee1fc39a5` | 4850498 / 4850500 |

Saldos de USDC al final:

| Cuenta | Antes de la fase 2 | Después |
| --- | --- | --- |
| `cyc-client` | 17 | **12** |
| `cyc-freelancer` | 3 | 8 |

## 4. Pendientes y riesgos detectados

1. **Latencia del caso C en el navegador: 49.6 s.** En la medición directa la mediana fue de 3.8 s. La explicación más probable es un intento que se colgó hasta el tope de ~50 s de `asyncio.wait_for`, seguido de un reintento rápido. No se puede confirmar, porque el backend no registraba los intentos. Desde este commit, `gemini.py` deja en el log cada intento fallido o fuera de esquema, con su duración. En la fase 5, las 10 corridas seguidas dirán si pasa seguido.
2. **Las capturas muestran un token de invitación completo.** Son de testnet y esas tareas ya están amarradas, así que el token ya no sirve para tomarlas. Aun así, conviene no publicar capturas de tareas abiertas.
3. **`client_release` sin botón** hasta tener la firma del cliente con Pollar (fase 3).
4. **Estilo:** la fuente Geist convierte `->` en una flecha dentro del texto de los criterios (se ve "→"). Es solo visual; el texto y el hash no cambian.
5. **Saldo:** quedan 12 USDC en `cyc-client`. Cada corrida de `fase2-capturas.mjs` gasta 1 USDC neto, y `fase1-curl.sh` otro. Hay 8 USDC en `cyc-freelancer`: si hacen falta, Rodrigo puede devolverlos a `cyc-client` con la CLI.
