# Cumple&Cobra: avance del 22 de noviembre de 2026 (noche)

Continúa a `docs/resumen-avance.md`, que vive en la rama `cumbre/preparacion` (`04adf60`), sin fusionar a `main`. Esto cubre lo que pasó después: la validación de costos, el verificador listo para producción, su publicación como beta para la cumbre del 23 de noviembre y la revisión de pantallas con una sesión real.

La fuente de verdad técnica sigue siendo `CLAUDE.md`. El detalle de esta parte, con comandos, salidas y cómo volver atrás, está en `docs/mejora/verificador-produccion.md`.

**Cambio de rumbo importante:** antes se había acordado no subir el verificador a producción hasta estar «al 100%». Rodrigo lo pidió explícitamente para la cumbre: que el público pueda usarlo y que la página no diga que solo hay análisis estático. Quedó **encendido para todos, como beta**. La lista de aceptación sigue pendiente (ver «Pendiente»).

## 1. Costos validados

Se revisaron las cifras que dio otro chat contra lo medido en el repositorio y la configuración real en Google Cloud. Quedó guardado en `docs/mejora/plan.md` («Validado el 22 de noviembre»), en la rama `cumbre/preparacion` (`a741fbc`).

- **El error principal:** los costos de IA citados (US$0.038 script y US$0.014 web) son de Muse Spark (Meta, v2). v1 usa Gemini 3.5 Flash por Vertex, a $1.50 / $9.00 por millón de tokens. Ese precio viene de agregadores, no de la página oficial de Google.
- **Medido con Gemini:**

  | Concepto | Costo |
  | --- | --- |
  | Verificación de script (juez) | ≈1.7 a 2 ¢ |
  | Verificación web | ≈1.4 ¢ |
  | Suite por acuerdo | ≈3 a 6 ¢ |
  | Envío al motor estático | ≈0.7 ¢ |
  | Proyecto completo | ≈US$0.12 a 0.20 ($2.50 a $5 pesos) |

- **Infraestructura real:**
  - Cloud Run: 1 vCPU y 512 MiB, con facturación por petición;
  - Cloud SQL: db-f1-micro, zonal, 10 GB SSD;
  - VM: e2-standard-2 Spot.

  Total ≈US$15 al mes, o ≈35 a 40 con Vercel Pro, que es obligatorio en cuanto se cobre comisión. No los US$100 que estimó el otro chat.
- **Evidencia medida:** ≈48 KB por verificación web, no 1 MB.
- **Punto de equilibrio con 5% de comisión y ≈$760 pesos fijos al mes:** ~8 proyectos de $2,000, ~3 de $5,000 o ~2 de $10,000.
- **Hallazgos:**
  - el proyecto de Google Cloud se comparte con otros servicios (`chatbot`, `mostrador-*`), así que la factura los mezcla;
  - falta saber cuánto cobra Pollar en mainnet.

## 2. Honestidad de la presentación

La lámina de la cumbre dice «Verificamos ejecutando el código», pero la página decía «Motor de Análisis Estático de Código basado en LLM». Se recomendó presentar la ejecución como algo que ya funciona en pruebas y no prometer fechas («próximos 30 días»).

Con la publicación del punto 4, ahora es cierto en presente, con la etiqueta beta. También se preparó la respuesta a la pregunta «¿confían en la IA a ciegas?»: no. Primero hay reglas deterministas, después las pruebas mandan, el juez no puede convertir un fallo en aprobación y todo queda auditable on-chain.

## 3. Verificador listo para producción (rama `mejora/verificador-prod`, ya fusionada)

| Hueco | Arreglo |
| --- | --- |
| La suite (hasta 8 llamadas al modelo y tiempo de VM) se preparaba antes del depósito, con solo 30 por minuto por IP y sin cuota diaria | `admit_suite`: cupo de suites activas (`MAX_PENDING_SUITES`, `503 VERIFIER_BUSY`), ventana por IP (`RATE_LIMIT_SUITES_PER_MINUTE`) y cuota diaria (`RATE_LIMIT_DAILY_SUITE`). Cada verificación consume `RATE_LIMIT_DAILY_VERIFICACION`. En `demo` y `live`, por defecto: 10, 2, 50 y 200 |
| Staging y producción firman con la misma llave del árbitro, y el candado del release es por base de datos | `release` reintenta ante `txBAD_SEQ` con la cuenta recargada, hasta 3 veces |
| 429 de Vertex con varias tareas a la vez | `LLM_MAX_CONCURRENT`: 4 llamadas simultáneas por proceso |
| Una suite se quedaba «preparando» para siempre si la VM Spot se detenía, porque el plazo vencía sin pasar por `/fail` | `reconcile_suite`: la reencola o la rechaza. La cola expira plazos vencidos al listar |
| Una suite rechazada obligaba a crear otra tarea, con el dinero atado si ya se había depositado | `POST /tasks/{id}/suite/reintentar` (`X-Client-Token`, máximo 2) y botón «Intentar de nuevo». No cambia el `rules_hash` |
| Sin monitoreo de la cola | `GET /health/verificador`: 503 si un trabajo lleva más de 15 min en cola |
| El pedido asistido redactaba criterios para leer código aunque la tarea fuera web | `profile: "web"` opcional en `/tasks/draft` y `/tasks/draft/review` (esquema `WebDraft`) |
| Probar en producción sin abrirlo | `VERIFIER_ALLOWED_CLIENTS` y `GET /verifier/acceso`. Hoy está vacío: abierto a todos |
| Producción necesitaba su propia VM | `deploy.ps1` crea una segunda VM y reutiliza el firewall y el rol si ya existen |

Pruebas con Docker: **486 en verde y 10 saltadas** (Postgres sin `CYC_TEST_DATABASE_URL`). Frontend: 28 pruebas, sin errores de tipos, de lint ni de build. Las pruebas nuevas están en `backend/tests/test_verificador_prod.py`, `backend/tests/test_stellar_release.py` y `backend/tests/test_drafting.py`.

## 4. Publicado en producción (22 de noviembre, noche)

| Pieza | Estado |
| --- | --- |
| Imagen | `api:aab6541` |
| Staging | Revisión `cumpleycobra-api-staging-00006-v8q` y código nuevo en la VM `cyc-verificador`. Recorrido real: caso B rechazado por los tests (bucle infinito) y caso A pagado, tx `cd98014f9db95bbc574659ee755a3a61233b789369cf1d9f4ea00b08ef873367` |
| VM de producción | `cyc-verificador-prod` (us-central1-a, e2-standard-2 Spot, sin cuenta de servicio, gVisor `release-20261116.0`). Se apaga sola sin trabajo (`verifier-idle-secs=3600` desde el siguiente arranque). La API puede encenderla con el rol `cycVerificadorArranque`, otorgado solo sobre esa VM |
| Token y evidencia | Secreto `cyc-verifier-queue-token-prod` (generado sin imprimirse) y bucket privado `cyc-evidencia-prod-1017372721585` (90 días) |
| API de producción | Revisión `cumpleycobra-api-00005-rs5` con `VERIFIER_ENABLED=true`, `VERIFIER_VM_*` y `EVIDENCE_BUCKET`, en modo `demo`, con 1 instancia mínima. Recorrido real: caso A pagado en 21 s, tx `06d01104c02c1faeb545637d49044b753ab77beeb280e201b380bf1d442802bf` |
| Frontend | `NEXT_PUBLIC_VERIFIER_ENABLED=true` en Vercel. Portada: «Lo que sigue» → **«Nuevo · beta»**; pie: «Verificación por ejecución en un contenedor aislado». El análisis estático se menciona como la otra opción (las tareas sin la casilla y los casos A–D de la demo lo usan) |

## 5. Revisión de pantallas con la sesión de Pollar de Rodrigo

Wallet `GA7MXQ…BEVJ`, que hizo de cliente y de programador. Tarea `Fzw_5tOvZG-FmM7o`:
- suite lista en alrededor de un minuto;
- depósito `985cd992…`;
- caso C rechazado por inyección, sin pago;
- caso A pagado en 18.4 s, tx `c806382e0c353c5269174eecfb01f7032f4dab92b9981694c2234b3963e57345`;
- el cliente ve «Pagada», los dos veredictos y «Ver código».

Cuatro hallazgos, corregidos, publicados (`c3e707e`, `d89aa06`) y comprobados en el sitio:
1. La interfaz sugerida tomaba prosa por código: «precios (números)» se volvía la función `precios`. Ahora solo sugiere firmas reales; si no hay, deja los campos en blanco.
2. El programador no veía el módulo ni la firma antes de aceptar. Ahora la tarjeta de criterios muestra «Lo que tu entrega debe exponer».
3. En celular, el plan de la suite empujaba la invitación y el depósito muy abajo. Ahora, antes del depósito, van arriba.
4. Un rechazo por inyección decía «No cumple lo acordado» con 4 de 4 criterios cumplidos. Ahora dice «Rechazado por un aviso de seguridad».

Quedó una tarea de prueba sin depositar en el navegador de Rodrigo, sin efecto.

## Dónde quedó todo

- `main`: el commit de este documento, sobre `3be5383`. Producción sirve ese código.
- Documentación: `docs/mejora/verificador-produccion.md` y `CLAUDE.md` (estado de decisiones, rutas y variables nuevas); `.env.example` y `backend/.env.example` (variables nuevas).
- Volver atrás:
  - API: `gcloud run services update-traffic cumpleycobra-api --region=us-central1 --to-revisions=cumpleycobra-api-00004-nhk=100`;
  - Frontend: `vercel promote https://cumpleycobra-g7z213a7d-rodyx-dev.vercel.app`;
  - VM: `gcloud compute instances stop cyc-verificador-prod --zone=us-central1-a`;
  - Cerrarlo sin apagarlo: `VERIFIER_ALLOWED_CLIENTS` con las cuentas de prueba.

## Pendiente

- **Para quitarle la etiqueta beta** (la lista de aceptación de `verificador-produccion.md`):
  - pruebas con personas externas que intenten colarle código malo;
  - probar `chromium_sandbox=True` bajo gVisor;
  - un árbitro propio para staging (otra instancia del mismo contrato en testnet; el de producción no cambia);
  - decidir por escrito el riesgo de cadena de suministro del build;
  - que Rodrigo revise el código del verificador.
- **Infraestructura:** uptime check sobre `/health/verificador` y alerta de presupuesto (cambios de producción: preguntar antes).
- **Después de la cumbre:**
  - devolver la API a `--min-instances=0`;
  - reembolsar con `timeout_refund` lo que quede depositado;
  - fusionar o actualizar `cumbre/preparacion`: su `docs/cumbre.md` todavía dice que el verificador no se muestra en vivo, y `docs/resumen-avance.md` ya quedó viejo.
- **Las reglas siguen igual:**
  - no usar `api.rodyxdev.com`;
  - nunca imprimir secretos;
  - preguntar antes de cada cambio en producción;
  - no tocar producción durante una demo.
