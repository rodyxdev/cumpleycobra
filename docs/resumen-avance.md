# Cumple&Cobra: resumen del avance (20 al 22 de noviembre de 2026)

Documento para retomar el proyecto en otra conversación con Claude sin el historial. Lo escribió Claude Code el 22 de noviembre de 2026, al cerrar la fase 3 y preparar la cumbre. La fuente de verdad técnica sigue siendo `CLAUDE.md` en la raíz del repositorio, y cada fase tiene su reporte en `docs/mejora/fase-N.md`. Aquí está el panorama, las decisiones, los números y lo que falta.

---

## 1. El producto en breve

**Cumple&Cobra** es un acuerdo verificable para trabajo de código. Frase del producto: «Si cumple lo acordado, cobras. Sin discusiones».

**Cómo funciona:**
1. El cliente escribe su pedido en lenguaje normal y la IA lo convierte en criterios medibles, que el cliente edita.
2. El cliente invita a su programador con un enlace; el programador acepta los criterios antes de trabajar.
3. El cliente deposita USDC en un contrato Soroban (Stellar testnet), firmado con la wallet de Pollar.
4. El programador entrega y el backend evalúa contra los criterios acordados.
5. Si cumple, el backend (el árbitro) firma `release` y el programador cobra en segundos. El código llega al cliente solo después del pago.

**Contexto:**
- Nació en el hackathon GOYA HACK (septiembre de 2026). Esta versión (v1) es la base; de v2 (otro repositorio) solo se traen piezas.
- Una sola persona construye: Rodrigo.

**Lo que no cambia nunca:** Stellar, el contrato Soroban desplegado, Pollar y el flujo del dinero (`deposit`, `release`, `client_release`, `timeout_refund`).

**Vocabulario:** se dice «Motor de Análisis Estático de Código basado en LLM» y «acuerdo verificable». Nunca «simulación», «marketplace» ni «sin confianza». Toda la interfaz va en español y los montos se muestran primero en pesos.

---

## 2. Cómo se trabaja: plan de mejora por fases

El plan vigente es `docs/mejora/plan.md`, escrito el 20 de noviembre. El orden de fases es 0 → 1 → 3 → 2 → 4: el verificador va antes que las cuentas reales.

**Reglas de cada fase:**
- Vive en su rama `mejora/fase-N`, que sale del tag anterior.
- Se cierra con todo en verde, un reporte `docs/mejora/fase-N.md`, un merge `--no-ff` a `main`, un tag anotado `mejora-N` y notas de cómo volver atrás.
- Una fase a medias nunca llega a `main`.
- Lo nuevo va detrás de variables de entorno apagadas por defecto, y las migraciones solo suman.

**Desde el 21 de noviembre la cumbre ya no marca el ritmo:** se avanza fase tras fase, sin fecha límite.

**Acuerdos con Rodrigo que siguen vigentes:**
- Antes de cualquier cambio en producción (Cloud Run, Vercel, Cloud SQL) se le pregunta, y nunca durante una demo.
- No usar `api.rodyxdev.com`, que es de otro proyecto suyo; la API se queda en su URL de `run.app`.
- Nunca imprimir secretos. `.env` y `state.json` no van a git.
- No leer archivos fuera del repositorio sin preguntar (excepción: el repositorio de v2).
- Commits pequeños y frecuentes, sin líneas de atribución.
- El frontend se queda en Vercel Hobby. Los créditos de Google duran hasta agosto–noviembre de 2027.

---

## 3. Línea de tiempo

| Fecha | Qué pasó |
| --- | --- |
| 20 nov | Plan de mejora escrito. Railway se había caído (fin del plan gratuito). Fase 0: puente a Cloud Run y rediseño con la identidad del logo |
| 21 nov | Tag `mejora-0`. Fase 1: Postgres en Cloud SQL, staging, modo demo del frontend y prueba de restauración del respaldo. Tag `mejora-1`. Empieza la fase 3 |
| 21–22 nov | Fase 3 completa: verificador que ejecuta el código, VM con gVisor, corpus, perfil web, encendido y apagado automático de la VM |
| 22 nov | Revisión de pantallas con sesión real de Pollar: se encuentra una caída de producción (testnet subió de protocolo) y se arregla. Tag `mejora-3`. Preparación de la cumbre |
| 23 nov | Cumbre |

**Tamaño:** de `mejora-1` a `mejora-3` hay 40 commits y 103 archivos cambiados (+11,487 / −57 líneas).

---

## 4. Estado actual (noche del 22 de noviembre)

| Pieza | Estado |
| --- | --- |
| Rama `main` | `00dbd3f`: merge de la fase 3. Antes está el hotfix `3ef4df3` |
| Tags | `mejora-0`, `mejora-1`, `mejora-3`. La fase 2 no ha empezado |
| Frontend de producción | Vercel, `https://cumpleycobra.vercel.app`, despliega `main`. Verificador oculto (`NEXT_PUBLIC_VERIFIER_ENABLED` apagado) |
| API de producción | Cloud Run `cumpleycobra-api` (us-central1), revisión `00004-nhk`, **1 instancia mínima para la cumbre** (hay que volver a 0 después). Modo `demo`, Postgres, 10 peticiones por minuto por IP y 500 al día. `VERIFIER_ENABLED` apagado. Imagen igual a la revisión `00003-cez` |
| Base de datos | Cloud SQL `cyc-pg`: base `cyc_prod` (producción) y `cyc` (staging) |
| API de staging | `cumpleycobra-api-staging`, revisión `00005-9wh`, con el verificador encendido, `EVIDENCE_BUCKET` y las variables de la VM. **Comparte la llave del árbitro con producción: no usarla durante la cumbre** |
| VM del verificador | `cyc-verificador` (us-central1-a), e2-standard-2 Spot, sin cuenta de servicio. Se apaga sola tras 15 min sin trabajo y la API la enciende cuando hay trabajo |
| Bucket de evidencia | `cyc-evidencia-staging-…`: privado, borra a los 90 días; solo `cyc-api` escribe y lee |
| Rama abierta | `cumbre/preparacion`: checklist de la cumbre, capturas y video guía. **Sin fusionar a `main`**, para no redesplegar Vercel antes de la cumbre |

---

## 5. Fase 0: versión para la cumbre (`mejora-0`)

- **Puente a Cloud Run:** el backend salió de Railway. Mismo contenedor (`backend/Dockerfile`), secretos en Secret Manager, Vertex con la cuenta de servicio (sin llaves JSON) y cabecera de IP del cliente configurable (`CLIENT_IP_HEADER`, `TRUSTED_PROXY_HOPS`).
- **Diseño:** identidad del logo (azul marino `#0C427C`, verde), portada nueva, tarjeta de veredicto y línea de estado de la tarea. Sin tocar la lógica.

## 6. Fase 1: base de producción (`mejora-1`)

- **Estado en Postgres:** `PostgresStore` con la misma interfaz que `state.json`. Un documento JSON por entidad, en una columna `json` y no `jsonb`, porque se necesita conservar el orden de las claves.
- **Candados entre instancias:** `pg_advisory_lock` más recarga de los documentos en su lugar. El release del árbitro usa un candado global y los retos SEP-10 viven en una tabla.
- **Modos y herramientas:** `APP_MODE` (`local`, `demo`, `live`); `docker compose` con Makefile; importar y exportar entre `state.json` y Postgres.
- **Hashes:** compatibles byte a byte con v2 (`test_hashing_v2.py`); ningún hash existente cambió.
- **Infraestructura:** Cloud SQL (`cyc-pg`) y staging. Producción pasó a Postgres el 21 de noviembre, y se probó restaurar un respaldo.
- **Frontend:** modo demo (aviso de testnet y faucet de Circle).

---

## 7. Fase 3: verificador que ejecuta el código (`mejora-3`)

Reporte completo, con salidas reales, errores y cómo volver atrás: `docs/mejora/fase-3.md`. Es la fase más grande.

### 7.1 Idea

Hasta la fase 1, el motor solo **leía** el código: análisis estático con `ast` y Gemini. La fase 3 agrega un verificador que lo **ejecuta** en un entorno aislado contra pruebas, y decide con una regla determinista. Todo va detrás de `VERIFIER_ENABLED`; el flujo de la fase 1 sigue igual.

### 7.2 Dónde corre cada cosa

| Pieza | Dónde | Por qué |
| --- | --- | --- |
| Generar la suite (pruebas), juzgar con el modelo, decidir y pagar | API (Cloud Run) | La API tiene las credenciales del modelo y la llave del árbitro |
| Ejecutar la entrega | VM `cyc-verificador` | Sin cuenta de servicio ni credenciales. Habla con la API por HTTPS, solo con un token de cola (`VERIFIER_QUEUE_TOKEN`) que no sirve para nada más |
| Cola de trabajos | Postgres (`verifier_jobs`, `verifier_sources`; migración `002_verificador.sql`) | `FOR UPDATE SKIP LOCKED`, `lease_id` y un plazo de 180 s por trabajo |

### 7.3 Dos perfiles de tarea

**Perfil script (funciones de Python).** El acuerdo incluye una `interface` (módulo, función y firma), que entra al `rules_hash` versión 2.
- El modelo (rol `suite`) clasifica cada criterio:
  - `test`: escribe pruebas pytest ocultas que llaman a la entrega en caja negra, por un canal (`cc_channel`), desde otro contenedor;
  - `lectura`: lo juzga el modelo leyendo el código.
- **Validación de la suite antes de aceptarla:** ninguna prueba puede pasar contra una entrega vacía ni contra un stub, y todas deben pasar contra una **implementación de referencia** que escribe el modelo. La referencia se agregó porque el corpus mostró pruebas con valores esperados mal calculados (empates de redondeo en floats).
- El programador ve el plan de cada prueba, nunca su código.

**Perfil web (sitio HTML/CSS/JS, estático o proyecto npm con build).** El acuerdo incluye `web: {"pages": [...]}` (1 a 5 rutas) y `language: "web"`.
- El modelo clasifica cada criterio:
  - `navegador`: de 1 a 4 chequeos de un catálogo fijo (`text_present`, `title_contains`, `element_visible`, `link_navigates`, `form_submits`, `no_horizontal_overflow`) que corre Playwright de forma determinista;
  - `visual`: lo juzga el modelo con capturas, y debe citar una captura que exista;
  - `lectura`: lo juzga el modelo leyendo el código.
- Los chequeos son **públicos**, porque repiten el criterio. Se validan contra un sitio vacío y contra un sitio de referencia.
- Playwright revisa cada página a 1440 px y 390 px, toma capturas JPEG y detecta texto oculto (contraste, tamaño 0, fuera de pantalla).
- Las capturas van a Cloud Storage y se ven con una **URL firmada de 15 minutos**: un HMAC propio, `GET /evidencia/...`. Su hash entra al `verdict_hash` versión 2.

### 7.4 Juez y regla final

- **El juez** corre en la API, nunca en la VM.
  - El código de la entrega va dentro de un bloque con un nonce aleatorio, como dato no confiable.
  - Cada cita del juez se verifica literalmente contra el material (`EvidenceChecker`); una cita inventada no cuenta.
- **La regla** es determinista (`backend/ejecucion/regla.py`):
  - una prueba o un chequeo que falla rechaza, y el juez nunca convierte un fallo en aprobación;
  - las señales de inyección, trampa o manipulación impiden aprobar automáticamente;
  - un juez sin evidencia verificable manda a revisión manual, sin pago;
  - en el perfil script, además se aplica la capa de seguridad de la fase 1.
- **Veredicto versión 2:** `verdict_hash` incluye `rules_hash`, `suite_hash`, `workspace_hash` y el estado por criterio. En el evento de `release`, `code_hash` es el `workspace_hash`.

### 7.5 Aislamiento (seguridad)

- **Contenedores:** toda entrega corre bajo **gVisor (`runsc`)**, sin red, `--read-only`, sin capacidades, como `nobody` y con límites de CPU, memoria y procesos.
- **Build de dependencias:** sale por una red interna cuya única salida es un **proxy squid con lista blanca** (PyPI y npm). En Python solo se instalan wheels; en npm, solo paquetes de `registry.npmjs.org` con `integrity`.
- **Metadatos de Google:** reglas `DOCKER-USER` los bloquean para los contenedores. Se aplican **antes de que arranque Docker** en cada encendido (`cyc-red.service`): se encontró que tras un reinicio el trabajador podía ejecutar entregas antes de que existieran las reglas.
- **VM:** sin cuenta de servicio, con un firewall que solo deja salir al puerto 443 y SSH solo por IAP.
- **Prueba de escape** (en la VM, bajo gVisor):
  - desde el código entregado: metadatos, internet, puerta de enlace y escritura en el host, todo bloqueado; el kernel que ve la entrega es `4.19.0-gvisor`;
  - desde el JavaScript de un sitio entregado: metadatos, internet y host de Docker, todo bloqueado;
  - Chromium corre bajo gVisor (era la duda abierta del plan).

### 7.6 Encendido y apagado de la VM

- **Apagado:** el trabajador deja de pedir trabajo tras 15 min sin trabajos y apaga la máquina; nunca corta un trabajo a medias. Apagada, la VM solo cobra el disco (unos 1.2 USD al mes); prendida, unos 0.03 USD por hora.
- **Encendido:** la API enciende la VM al encolar un trabajo o al consultar uno que sigue en cola, como mucho una vez cada 30 s. Usa un rol personalizado con solo `compute.instances.get` y `compute.instances.start`, sobre esa instancia.
- **Espera:** el primer trabajo tras un apagado tarda 1 o 2 minutos más.

### 7.7 Adaptador de modelos

`backend/llm.py`:
- Gemini (Vertex) o Muse (compatible con OpenAI), elegido por rol con `LLM_SUITE_PROVIDER` y `LLM_JUEZ_PROVIDER`.
- Soporta imágenes para el juez visual.
- Reintentos: ante cuota (429/503), espera de 4 a 40 s con variación; ante otros errores transitorios, 1 y 3 s; un reintento si la respuesta sale del esquema.

**Elegido: Gemini 3.5 Flash en los dos roles.** Muse no se midió porque su llave solo está en el `.env` de v2.

### 7.8 Corpus y números

| Medición | Resultado |
| --- | --- |
| Perfil script: 60 entregas en 5 acuerdos (18 correctas), 3 corridas | 180 verificaciones, **0 falsas aprobaciones**, 4 falsos rechazos por dos causas, ambas corregidas. Después de corregir, 33 de 33 bien |
| Perfil script, total | 213 verificaciones, 0 falsas aprobaciones |
| Perfil web: 13 entregas en 2 acuerdos (3 correctas), 3 corridas tras los arreglos | 39 verificaciones, **0 falsas aprobaciones, 0 falsos rechazos** |
| Costo | Unos 2 centavos de dólar por entrega (script), 1.4 por entrega web y 3 por suite web |
| Tiempo | Mediana de 19.5 s por entrega (script) y 14.2 s (web), con la VM encendida |
| Tests al cerrar | 463 del backend y del verificador, y 27 del frontend, en verde; tipos y lint limpios |

Ejemplos de entregas que no deben aprobarse:
- **Script:** errores sutiles, memorizar los ejemplos públicos, inyección al evaluador, `os._exit`, `conftest` manipulador, leer secretos.
- **Web:** formulario por GET, título equivocado, desborde a 390 px, encabezado chico, fuente externa, texto oculto para el evaluador, enlace roto.

**Lo que el corpus corrigió:**
- **Validación de la suite:** la implementación de referencia y la regla contra empates de redondeo en floats.
- **Canal de excepciones:** `StatisticsError` debe seguir siendo un `ValueError` al cruzar el canal.
- **Cuota del modelo:** esperas ante 429/503, y el tope de tiempo por petición a Gemini.
- **Perfil web:**
  - normalizar las rutas de página (el modelo escribía `index.html`, `/*` o `...`);
  - tratar `/x/index.html` igual que `/x`;
  - el mínimo de la cita de captura, que estaba en 10 caracteres y dejaba fuera el texto copiado.

### 7.9 Pagos reales en testnet con el verificador (staging + VM)

- **Script:** caso B rechazado y caso A pagado; release `02f17648…`.
- **Web:** tarea `ayQbmUldqXKfejlK`; el formulario por GET se rechazó y la entrega correcta se pagó (release `698dada5…`). Las capturas quedaron en el bucket y se vieron por URL firmada.
- **Encendido automático:** con la VM apagada, una tarea creada a las 06:59:07 encendió la VM a las 06:59:16; la suite quedó lista en 106 s y el caso A se pagó (`4b946bff…`).

### 7.10 Desviaciones del plan

| Desviación | Por qué |
| --- | --- |
| URL firmada con HMAC propio en vez de la de Cloud Storage | No exige el permiso `signBlob` y funciona igual en local |
| Chequeos web públicos, no ocultos | Repiten el criterio; ocultarlos no protege nada |
| Sin mockups del cliente en el perfil web | Se puede agregar después; el juez visual compara contra el texto del criterio |
| Muse sin comparar | Gemini cumplió el criterio y la llave de Muse solo está en v2 |
| Implementación o sitio de referencia para validar la suite | El corpus mostró pruebas mal calculadas |

---

## 8. Hotfix en producción (22 de noviembre)

**Qué pasó:** al revisar pantallas con una sesión real de Pollar apareció «No se pudo leer tu cuenta: LedgerHeader.scpValue.ext.v: unknown enum value 3». Testnet subió al protocolo 30 y `@stellar/stellar-sdk` 17.1.0 ya no podía leer el encabezado del ledger. El cliente no pasaba de la revisión de USDC, **también en la demo en línea**.

**Arreglo:**
1. Se reprodujo fuera del navegador; con la 17.4.0 se arregla.
2. Rama `hotfix/stellar-sdk-17.4` desde `main`, solo con `package.json` y `package-lock.json`. Pasaron tests, tipos, lint y el build de producción.
3. Con el permiso de Rodrigo se fusionó a `main` (`3ef4df3`) y Vercel desplegó.
4. Se comprobó con su sesión en producción: lee el saldo y deja crear la tarea.

**Lección:** testnet cambia sin aviso y no hay monitoreo. La caída se encontró por casualidad.

En la misma revisión se corrigieron tres textos del perfil web: decía «Python» o «suite oculta» en tareas web, y una suite rechazada no decía por qué.

---

## 9. Preparación de la cumbre (23 de noviembre)

Todo está en la rama `cumbre/preparacion`, en `docs/cumbre.md` y `docs/cumbre/`.

- **Comprobado el 22:**
  - la API, el tipo de cambio (Frankfurter en vivo) y la gas wallet de Pollar (9,998 XLM);
  - saldos: cliente `GBGK4N…D4FL` con 18 USDC, programador `GA7MXQ…BEVJ` con unos 46 y la wallet de respaldo por terminal `cyc-client` con 5;
  - el video demo en Drive es público.
- **API siempre caliente:** 1 instancia mínima, porque en frío tardaba 15.6 s y caliente 0.15 s. Hay que devolverla a 0 después.
- **Tres ensayos seguidos en producción sin fallo:**
  - pedido asistido 2.4–4.0 s, revisar criterios 2.3–3.0 s, depósito con Pollar 4.0–5.5 s;
  - caso C rechazado por inyección en 2.5–3.1 s y caso A aprobado y pagado en 3.9–5.7 s.
  - El cliente corrió en el navegador con la sesión de Rodrigo; el programador, por la API con la wallet de prueba.
- **Video guía:** `docs/cumbre/recorrido-demo.mp4` (2:04), con 18 pantallas de un recorrido real en producción y subtítulos (tarea `JgIReynD_NgX1DMR`, pago `0b27a204…`).
- **Capturas para «lo que sigue»:** plan de chequeos, veredicto web pagado, galería de capturas y una captura original del verificador.
- **Decisión:** el verificador **no se muestra en vivo** en la cumbre (staging comparte la llave del árbitro y la VM tarda en encender). Va en láminas como «lo que sigue».
- **Pendiente de Rodrigo:**
  - un ensayo con dos ventanas y dos sesiones de Pollar, como en el escenario;
  - grabar el video de respaldo en vivo;
  - iniciar sesión en las dos ventanas justo antes de subir.

Recorrido del escenario (unos 5 minutos):
1. Pedido asistido con «Que sea rápido» marcado como vago.
2. Crear la tarea con 20 MXN y 10 minutos.
3. Depositar con Pollar.
4. El programador acepta.
5. El caso C se rechaza por inyección.
6. El caso A se aprueba y se paga, y se abre la transacción en el explorador.
7. El cliente ve «Pagada» y recibe el código.

---

## 10. Riesgos y deuda conocida (honesta)

1. **El corpus lo escribió el mismo Claude que construyó el verificador.** Las 0 falsas aprobaciones prueban que atrapa los errores que se imaginaron, no los de un programador real tratando de colarse. Falta que personas externas lo pongan a prueba (fase 4, piloto).
2. **Nadie externo ha usado el verificador:** solo está en staging.
3. **Rodrigo revisó poco código.** Se fusionaron miles de líneas con poca lectura humana, y el CLAUDE.md pide que pueda explicar cada parte en la defensa. Conviene hacer sesiones de recorrido del código: el verificador, `regla.py`, la cola y el aislamiento.
4. **No hay monitoreo** de la demo ni de la API. La caída del protocolo de testnet se encontró por casualidad.
5. **Huecos anotados:**
   - El JavaScript de un sitio entregado corre en el Chromium del contenedor confiable sin el sandbox propio de Chromium. Lo acotan gVisor, que no haya red ni secretos, y que la decisión se tome en la API.
   - El pedido asistido redacta criterios pensados para leer código, aunque la tarea sea web.
   - No se puede reintentar una suite rechazada sin crear otra tarea.
   - Sin mockups en el perfil web.
   - La pantalla del programador del perfil web no se vio en vivo con una sesión propia.
   - La tarea `o7g2IZemWSoE132E` de staging quedó trabada (solo testnet).
6. **Staging y producción firman con la misma llave del árbitro** (el contrato tiene un solo árbitro). Si los dos pagan en el mismo segundo, uno podría fallar por el número de secuencia.
7. **Límites en memoria por instancia** (peticiones por IP y cuota diaria): con N instancias, la cuota diaria efectiva es N veces la configurada. En la cumbre, mucha gente en el mismo Wi-Fi comparte el límite de 10 por minuto.

---

## 11. Lo que sigue

Recomendación de Claude Code, que Rodrigo todavía no decide:

1. **Después de la cumbre:**
   - devolver la API a 0 instancias mínimas: `gcloud run services update cumpleycobra-api --region=us-central1 --min-instances=0`;
   - reembolsar con `timeout_refund` lo que haya quedado depositado;
   - fusionar `cumbre/preparacion` a `main`.
2. **Bajar el ritmo antes de la fase 2:**
   - sesiones de recorrido del código con Rodrigo;
   - un monitor que pruebe la demo cada hora (salud de la API y lectura de saldo en testnet) y avise si falla;
   - una o dos personas reales usando el verificador web en staging.
3. **Fase 2 del plan (cuentas reales):** cookies `HttpOnly`, roles y vistas por rol de v2 sobre las sesiones SEP-10 de v1, y una tarea real de punta a punta.
4. **Fase 4 (piloto):** 3 tareas (2 de personas externas) y un informe público.
5. **Encender el verificador en producción** es un cambio de producción y requiere el permiso de Rodrigo. Necesita:
   - un bucket de producción;
   - las variables `VERIFIER_*` en Cloud Run de producción;
   - `NEXT_PUBLIC_VERIFIER_ENABLED` en Vercel;
   - decidir si producción usa la misma VM.

---

## 12. Dónde está cada cosa

| Tema | Ruta |
| --- | --- |
| Contexto técnico completo (API, hashes, variables, reglas) | `CLAUDE.md` |
| Plan de mejora | `docs/mejora/plan.md` |
| Reportes de fase | `docs/mejora/fase-1.md`, `docs/mejora/fase-3.md`; el puente a Cloud Run en `docs/mejora/puente-cloud-run.md` |
| Checklist de la cumbre y del hackathon | `docs/cumbre.md`, `docs/demo.md` |
| Verificador, lado de la API | `backend/ejecucion/` (`suite.py`, `web.py`, `juez.py`, `juez_web.py`, `regla.py`, `rutas.py`, `cola.py`, `evidencia.py`, `arranque.py`, `perfil.py`) |
| Adaptador de modelos | `backend/llm.py` |
| Trabajador y aislamiento (VM) | `verifier/` (`worker.py`, `sandbox/`, `blackbox/`, `web/`, `ingest/`, `verification/`) |
| Despliegue de la VM | `verifier/deploy/` (`deploy.ps1`, `startup.sh`, `red.sh`, servicios de systemd, proxy) |
| Corpus y scripts | `scripts/corpus_verificador/`, `scripts/correr_corpus.py`, `scripts/verificador_testnet.py` (con `--web`) |
| Contrato | `contracts/cumpleycobra/` (no cambió en estas fases) |
