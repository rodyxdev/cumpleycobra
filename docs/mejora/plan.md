# Plan de mejora: v1 como base, piezas de v2

Fecha: 20 de noviembre de 2026. Sustituye al documento «plan de mejora por fases» donde lo contradiga.

## Reglas de este plan

- Se trabaja en este repositorio (v1). De v2 (`cumpleycobra-v2`) solo se copian piezas, cada una con sus tests.
- **No se toca:** Stellar, el contrato Soroban desplegado, Pollar y el flujo del dinero (`deposit`, `release`, `client_release`, `timeout_refund`).
- v1 no es la verdad absoluta. Lo que se hizo con prisa y se cambia está en «Lo que cambia de v1».
- **Fuera:** los videos de v2 (grabación de Playwright). El perfil web solo toma capturas.
- **Se queda:** el enlace de Drive al video demo del programador. Es una prueba de confianza del freelancer hacia el cliente.
- Sin presupuesto de horas: se avanza todo lo que se pueda, en el orden de las fases.
- Cada fase cierra con un tag (`mejora-0`, `mejora-1`…) y un reporte en `docs/mejora/`. Así no se mezcla con `docs/fases/`, que es la bitácora del hackathon.
- El trabajo nuevo queda detrás de *feature flags* apagados por defecto, y las migraciones solo agregan.

## Fase 0: cumbre del 23 de noviembre (3 días)

Con 3 días no da para meter el motor de ejecución de v2 en v1 sin arriesgar la demo. Mi recomendación:

- **La demo es v1.** Está desplegada, en español y con Pollar y testnet reales.
- **Solo cambia el diseño** de tres pantallas: portada, veredicto y estado de la tarea.
- **La ejecución real de v2 se muestra como «lo que sigue»**, con una captura de su reporte y no en vivo.
- **El backend sale de Railway ahora.** Se acabó el plan gratuito y `/health` responde 404 desde el 20 de noviembre, así que la demo en línea no funciona. Para la cumbre va a Cloud Run con el mismo contenedor y con `state.json` en un volumen de Cloud Storage. Postgres llega en la fase 1, sin la prisa de la cumbre.

### Puente a Cloud Run (antes de la cumbre)

- **Imagen:** la misma `backend/Dockerfile`, subida a Artifact Registry.
- **Instancias:** `--max-instances=1`, porque los candados viven en memoria. `--min-instances=1` durante la cumbre para evitar el arranque en frío; después vuelve a 0.
- **Estado:** `STATE_FILE` en un volumen de Cloud Storage (gcsfuse) montado en `/data`.
  - En gcsfuse, `os.replace` no es atómico, pero con una sola instancia y un archivo pequeño alcanza para el puente.
  - El estado de Railway probablemente se perdió. Son datos de testnet: el dinero y los pagos siguen en el contrato.
- **Secretos:** `ARBITER_SECRET_KEY`, `SEP10_SIGNING_SECRET` y `SESSION_SECRET` en Secret Manager.
- **Vertex:** la cuenta de servicio del servicio con `roles/aiplatform.user`. Sin llaves JSON y sin `GOOGLE_CREDENTIALS_B64`.
- **IP del cliente:** `limites.py` lee `X-Real-IP`, que Cloud Run no envía. Sin cambios, todos los visitantes compartirían un solo límite por minuto.
  - Se hace configurable (`CLIENT_IP_HEADER` y número de proxies de confianza en `X-Forwarded-For`).
  - Después del despliegue se comprueba con una petición que trae un `X-Forwarded-For` falso.
- **URL:** la de `run.app` por ahora. `api.rodyxdev.com` con Cloudflare va en la fase 1.
- **Frontend y Pollar:** cambiar `NEXT_PUBLIC_API_URL` en Vercel y volver a desplegar; `FRONTEND_ORIGIN` y los dominios SEP-10 quedan apuntando al dominio nuevo.

| Día | Trabajo | Listo cuando |
| --- | --- | --- |
| 20–21 | Puente a Cloud Run: el recorrido completo funciona en línea | `/health` en verde, un pago real en testnet desde Vercel |
| 20–21 | Mockup de portada, veredicto y estado de la tarea con la identidad del logo; tú lo apruebas | Mockup aprobado |
| 21 | Tokens de diseño en `globals.css`, encabezado con el logo, portada nueva, tarjeta de veredicto y línea de estado. Sin tocar `src/lib`, hooks, textos de botones ni `data-testid` | `next build` y lint en verde; revisado en celular |
| 22 | Congelar, tag `mejora-0`, 3 recorridos completos seguidos, video de respaldo (grabación de pantalla tuya) y ensayo | 3 de 3 sin fallo |

### Identidad visual

Sale del logo y reemplaza la paleta de septiembre (azul `#2A5FC7`), que no es la del logo.

| Token | Valor | Uso |
| --- | --- | --- |
| Marino (marca) | `#0C427C` | Títulos, botón principal, encabezado |
| Verde (cumple) | `#109850` | Aprobado, pagado, el ✓ del veredicto |
| Tinta | `#0F1B2D` | Texto |
| Papel | `#F7F8FA` | Fondo |
| Ámbar | `#E8963A` | Alertas, siempre con texto oscuro |
| Rojo | `#C2362B` | Rechazo |

- Títulos con una geométrica redondeada parecida a la del logo (Plus Jakarta Sans o Sora; se decide en el mockup).
- Texto en DM Sans, que ya está instalada. Hashes y direcciones en JetBrains Mono.
- Contraste AA, modo claro primero.
- Lo que hoy lo hace ver simple: no hay jerarquía ni color de marca, y la evidencia (criterios ✓/✗, hash, transacción) es texto plano. El veredicto pasa a ser la pieza central, con el sello ✓ del logo, el monto en grande y el enlace a stellar.expert como un recibo.

## Lo que cambia de v1

| Hoy en v1 | Problema | Cambio | Fase |
| --- | --- | --- | --- |
| `state.json` en un volumen de Railway | No escala, un solo proceso, sin respaldos reales | Postgres detrás de la misma interfaz que `StateStore` | 1 |
| Candados por tarea, candado del `release` y retos SEP-10 en memoria | Obligan a un solo proceso y una sola réplica (`Dockerfile`, `--workers 1`) | Candados con `pg_advisory_xact_lock` y retos en una tabla con caducidad. La API queda sin estado y puede escalar | 1 |
| Sesión y tokens en `localStorage` | Un script en la página puede leerlos (lo admite el README) | Cookie `HttpOnly`, `Secure` y `SameSite`, más protección CSRF en las rutas que escriben | 2 |
| Entrega de un solo archivo Python de hasta 10 KB, pegado | No sirve para trabajo real | Ingesta por ZIP y por repositorio público con SHA fijo (`ingest/` de v2). La GitHub App queda para después | 3 |
| «El servidor nunca ejecuta el código» | El motor solo opina; el SOW pide verificar ejecutando | Verificador aislado que ejecuta (abajo). El análisis estático queda como una capa más | 3 |
| Corpus de 20 casos de un solo requisito | El plan decía 60, y no ejecuta | 60 casos ejecutables: los 20 de v1, los ejemplos de v2 (`ventas`, `landing` y los maliciosos) y unos 25 nuevos | 3 |
| El CLAUDE.md dice «sin base de datos, sin Docker» | Contradice este plan | Se reescribe al empezar la fase 1 | 1 |

## Hashes

- `hashing.py` (v1) y `canonical.py` (v2) generan los mismos bytes para datos válidos: NFC, claves ordenadas por punto de código, sin `float` y los mismos escapes.
  - v2 además rechaza enteros fuera de ±(2^53 − 1), surrogates sueltos y claves que coinciden tras NFC.
- **Decisión:**
  - Se queda `hashing.py`, porque las tareas existentes dependen de él, y se le agregan esos tres rechazos.
  - Un test compara las dos implementaciones con los mismos vectores, para demostrar que no cambia ningún hash existente.
- **Esquema de veredicto `version: 2`** para las verificaciones por ejecución: `task_id`, `rules_hash`, `suite_hash`, `workspace_hash`, `approved`, `stage`, resultado por criterio y `video_url` (el enlace de Drive se queda, como en v1).
  - El contrato no cambia: `release` ya recibe `code_hash` y `verdict_hash` como 32 bytes, y en esquema v2 `code_hash` lleva el `workspace_hash`.
- Los identificadores de tarea siguen siendo texto (contrato de v1). El `accept` on-chain y los identificadores de 32 bytes de v2 no se migran.

## Arquitectura objetivo

```
Vercel (Next.js, v1)  ──HTTPS──>  Cloudflare (api.rodyxdev.com, WAF, límites)
                                        │
                                  Cloud Run: API FastAPI (v1)
                                  · árbitro: firma release (llave en Secret Manager)
                                  · llama al modelo (juez) y decide el veredicto
                                  · encola trabajos en Postgres
                                        │
                     ┌──────────────────┼───────────────────┐
               Cloud SQL Postgres   Cloud Storage       Verificador: VM Spot
               (tareas, trabajos,   (capturas,          · SIN cuenta de servicio
                candados, retos)     90 días)           · saca trabajos por HTTPS con un token
                                                          que solo sirve para eso
                                                        · Docker + gVisor para el código ajeno
                                                        · devuelve evidencia; nunca decide ni firma
```

**Por qué el juez corre en la API y no en la VM.** Así la VM no guarda ninguna credencial: ni la del modelo, ni la de Google Cloud, ni la del árbitro. Si el código ajeno escapara del contenedor, en la VM solo encontraría el token de la cola, que sirve para pedir trabajos y entregar resultados. No sirve para pagar ni para leer otras tareas. Las capturas se suben con una URL firmada que vale para un solo trabajo y vence en 15 minutos.

### Seguridad del verificador, por capas

1. **Contenedor:** se reutiliza la configuración de v2 (`--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, usuario `nobody`, límites de CPU, memoria y PIDs, tmpfs acotados). Lo nuevo es el runtime **gVisor (`runsc`)** para todo contenedor con código ajeno, que agrega un kernel en espacio de usuario contra escapes. Es gratis; falta verificar que Playwright funciona bajo gVisor.
2. **Red del paso de build:** hoy en v2 tiene salida libre a internet (`bridge`). Pasa a una red interna de Docker sin ruta a internet; la única salida es un proxy en la misma VM con lista blanca: `pypi.org`, `files.pythonhosted.org` y `registry.npmjs.org`.
   - Es más barato y más simple que Artifact Registry, que pide autenticación (justo la credencial que no queremos en la VM).
3. **Metadatos:** VM sin cuenta de servicio (`--no-service-account --no-scopes`), con una regla `DOCKER-USER` que descarta tráfico a `169.254.169.254` como respaldo.
4. **Firewall de la VPC:** no entra nada desde internet y no hay SSH público (IAP si hace falta). Solo hay salida a 443.
5. **Higiene:** cada trabajo usa volúmenes nuevos que se borran al terminar, y la VM se recrea seguido (las Spot se interrumpen solas).
6. **Prueba de escape (evidencia del SOW):** una entrega maliciosa intenta leer metadatos, salir a internet, alcanzar la API y escribir en el host. Todo debe fallar y queda registrado.

**Por qué no Cloud Run para el verificador.** La caja negra de v2 necesita dos contenedores en una red interna (código ajeno y tests confiables), y Playwright corre separado de la página que revisa. Cloud Run no permite levantar Docker adentro. Reescribirlo para Cloud Run o Cloudflare Sandboxes costaría más horas que la VM.

### Escalar

- API sin estado (fase 1) → Cloud Run escala por sí solo.
- Cola en Postgres con `FOR UPDATE SKIP LOCKED`, sin Pub/Sub mientras el volumen sea bajo.
- Una e2-standard-2 corre unas 2 verificaciones en paralelo de 20 a 30 s: unas 200 por hora. Para crecer se pasa a un grupo de VMs Spot que escala según el tamaño de la cola, sin cambiar código.
- La VM se apaga si no hay trabajos por 15 minutos y la API la enciende al encolar. Cuesta un arranque en frío de 60 a 90 s; en modo `demo` se deja encendida en horario de uso.

### Llave del árbitro

Quien tenga la llave del árbitro puede liberar cualquier depósito.

- **Ahora:** en Secret Manager; solo la cuenta de servicio de la API puede leerla.
- **Mainnet (fase 5):** firmar con Cloud KMS (Ed25519), para que la llave nunca salga de KMS. Requiere desplegar el contrato de nuevo con ese árbitro. El código del contrato es el mismo; solo cambia el ID.

## Modelos

Lo medido en ambos proyectos (tokens reales). Los precios vienen de agregadores, no de las páginas oficiales:

| Modelo | Precio por M (entrada / salida) | Verificación script (≈11.4k / 5.3k tokens) | Verificación web (≈5.2k / 1.9k) | Notas |
| --- | --- | --- | --- | --- |
| Muse Spark 1.3 (Meta, v2) | $1.25 / $4.25 | **$0.038 medido** | **$0.014 medido** | Razona mucho: 70–90 % de la salida. 3–6 s mínimo por llamada. Los créditos se acaban, y el plan «contributor» entrena con tus datos |
| Gemini 3.5 Flash (v1 hoy) | $1.50 / $9.00 | ≈$0.065 (estimado con los mismos tokens) | ≈$0.025 | 20/20 en el corpus de v1. Lo cubren tus créditos de Google |
| Gemini 3.5 Flash-Lite | $0.30 / $2.50 | ≈$0.017 | ≈$0.006 | El más barato; falta medir si mantiene 0 falsas aprobaciones |
| muse-wonder-1.0 | Sin precio publicado | — | — | Aparece en `/v1/models` de Meta; no se probó |

**Conclusiones:**

- Cualquier opción cuesta centavos por verificación: 1,000 al mes son entre 15 y 65 USD de modelo. El costo no decide; deciden la exactitud (0 falsas aprobaciones) y la latencia.
- Los créditos de Meta son gratuitos y su uso no preocupa (decisión del 20 de noviembre).
- **Recomendación:**
  - **Muse Spark para las piezas que vienen de v2** (suite oculta, juez de código y juez visual): sus prompts ya están medidos con ese modelo.
  - **Gemini por Vertex para las de v1** (pedido asistido, revisión de criterios, análisis estático).
  - Un solo adaptador (`llm.py` de v2 más `gemini.py` de v1), con el proveedor elegido por variable de entorno para cada rol. Si se acaban los créditos de Meta, se cambia una variable.
  - El corpus de 60 casos decide: se corre con cada modelo en cada rol, y se usa uno solo si da 0 falsas aprobaciones en 3 corridas.
- La creación de tarea con suite oculta (6 llamadas, unos 55 s y $0.13 con Muse) se vuelve un trabajo en cola, no una petición que bloquea.

## Costo mensual estimado (volumen bajo, antes de créditos)

| Pieza | Elección | USD al mes |
| --- | --- | --- |
| Frontend | Vercel Hobby | 0. El plan Hobby no permite uso comercial: al cobrar comisiones hay que pasar a Pro ($20) |
| DNS, CDN, WAF | Cloudflare gratis | 0 |
| API | Cloud Run por petición, mínimo 0 instancias | ≈0 dentro de la capa gratis |
| Base de datos | Cloud SQL db-f1-micro, 10 GB y respaldos | ≈11–14 |
| Verificador | e2-standard-2 Spot (≈$0.029/h) más 30 GB de disco | ≈6–10 encendida solo con trabajos; ≈24 si queda prendida siempre |
| Evidencia | Cloud Storage con retención de 90 días (≈1 MB por verificación web, sin video) | <1 |
| Secretos | Secret Manager | <1 |
| Modelo | Gemini (ver tabla) | 1.5–6.5 por cada 100 verificaciones |
| **Total** | | **≈20–45 más uso del modelo**, cubierto por créditos mientras duren |

Si se acaban los créditos, lo primero que se cambia es la base de datos: Neon gratis en lugar de Cloud SQL. Son unos $12 menos y basta con cambiar la URL.

## Fases después de la cumbre

| Fase | Qué incluye |
| --- | --- |
| 1. Base de producción | Reescribir CLAUDE.md; `APP_MODE` (`local`, `demo`, `live`) y flags; `PostgresStore` con la misma interfaz, migraciones y script de importación desde `state.json`; candados y retos en Postgres (se quita el volumen de Cloud Storage y `max-instances=1`); `docker compose` y `Makefile`; Cloud SQL, alertas de presupuesto y una restauración de respaldo probada; `api.rodyxdev.com`; test cruzado de hashes; modo demo para celular y estados vacíos |
| 3. Verificador | `verifier/` con `sandbox/`, `blackbox/`, `verification/`, `web/` e `ingest/` de v2 (sin video de Playwright ni GitHub App); cola en Postgres; juez en la API; adaptador de modelo; VM sin credenciales con gVisor y proxy; capturas en Cloud Storage; corpus de 60 casos; elección del modelo; prueba de escape; progreso en vivo en la UI. Detrás de `VERIFIER_ENABLED` |
| 2. Cuentas reales | Cookies `HttpOnly`; roles y vistas por rol de v2 (`views.py`, por lista blanca) sobre las sesiones SEP-10 de v1; una tarea real de punta a punta |
| 4. Piloto | 3 tareas (2 de personas externas) y el informe público |

## Pendientes tuyos

- Confirmar los precios en las consolas oficiales (Vertex AI y Meta) antes del informe público.
- Revisar cuándo vencen los créditos de Google.
