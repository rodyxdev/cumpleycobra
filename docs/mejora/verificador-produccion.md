# Verificador por ejecución: camino a producción

Rama `mejora/verificador-prod`, sobre `main` (`00dbd3f`, tag `mejora-3`). Empezó el 22 de noviembre de 2026.

**Nada de esto está desplegado.** Producción sigue igual: `VERIFIER_ENABLED` apagado en Cloud Run y `NEXT_PUBLIC_VERIFIER_ENABLED` apagado en Vercel. Todo lo nuevo está detrás de esas variables, o solo actúa con el verificador encendido.

Rodrigo decide cuándo llega a producción, con la lista de aceptación de abajo. Antes de cualquier cambio en producción se le pregunta (regla 14 de `CLAUDE.md`).

## Qué se hizo

| Hueco | Arreglo | Archivos |
| --- | --- | --- |
| **La suite cuesta modelo y VM antes del depósito.** Cualquiera podía crear 30 tareas por minuto, cada una con hasta 8 llamadas al modelo, y nada contaba en la cuota diaria. | `admit_suite` antes de crear la tarea (también al reintentar). Si falla, la tarea no se crea. <br>1. `MAX_PENDING_SUITES`: cupo de suites activas, `503 VERIFIER_BUSY`. <br>2. `RATE_LIMIT_SUITES_PER_MINUTE`: ventana por IP. <br>3. `RATE_LIMIT_DAILY_SUITE`: cuota diaria, que se consume al final para que un rechazo no gaste cuota. <br>Cada verificación consume `RATE_LIMIT_DAILY_VERIFICACION`, después de las guardias y antes de guardar el ZIP. `demo` y `live` fijan 10, 2, 50 y 200. | `backend/ejecucion/rutas.py`, `backend/limites.py`, `backend/config.py`, `backend/main.py` |
| **Staging y producción firman con la misma llave del árbitro.** El candado del release es por base de datos (`cyc` y `cyc_prod`), así que dos pagos simultáneos podían chocar por número de secuencia. | `release` detecta `txBAD_SEQ` en la respuesta de `sendTransaction` y arma la transacción de nuevo con la cuenta recargada, hasta 3 veces. Una transacción rechazada así nunca se aplica, y el hash guardado al final es el de la que sí se envió. | `backend/stellar_client.py` |
| **Cuota de Vertex (429) con varias tareas a la vez.** | Tope de llamadas simultáneas al modelo por proceso: `LLM_MAX_CONCURRENT`, 4 por defecto. La espera del turno no cuenta para el tope de tiempo de cada intento. | `backend/llm.py` |
| **Una suite podía quedarse «preparando» para siempre.** Si la VM Spot se detiene tres veces, el trabajo vence por plazo sin pasar por `/fail` y nadie actualizaba la suite. Así se trabó `o7g2IZemWSoE132E` en staging. | `reconcile_suite`: al consultar la tarea o su suite, una suite sin trabajo activo (fuera de un periodo de gracia de 30 s) se reencola, o se rechaza al agotar 3 trabajos. Además, la cola expira los plazos vencidos al listar los trabajos de una tarea. | `backend/ejecucion/rutas.py`, `backend/ejecucion/cola.py` |
| **Una suite rechazada obligaba a crear otra tarea.** Si el cliente ya había depositado, el dinero quedaba atado hasta el plazo. | `POST /tasks/{id}/suite/reintentar` con `X-Client-Token`, máximo 2 veces. No cambia el `rules_hash`, así que sirve también después del depósito. En la pantalla del cliente aparece el botón «Intentar de nuevo». La falla de un trabajo de la suite anterior ya no toca la nueva. | `backend/ejecucion/rutas.py`, `frontend/src/components/suite-plan-card.tsx`, `frontend/src/app/cliente/page.tsx` |
| **Sin monitoreo de la cola.** | `GET /health/verificador`: conteos agregados y edad del trabajo más viejo. Responde `503` si lleva más de `VERIFIER_STUCK_SECS` (15 min) en cola, y enciende la VM si hay trabajo esperando. Sirve para un uptime check de Cloud Monitoring. | `backend/ejecucion/rutas.py` |
| **El pedido asistido redactaba criterios para leer código, aunque la tarea fuera web.** | `profile: "web"` opcional en `/tasks/draft` y `/tasks/draft/review`: instrucciones y esquema (`WebDraft`, `language: "web"`) para criterios que se ven o se usan en el navegador. Sin `profile`, todo queda igual que antes. | `backend/drafting.py`, `frontend/src/components/assisted-task-form.tsx` |
| **Probar en producción sin abrirlo al público.** | `VERIFIER_ALLOWED_CLIENTS`: solo esas cuentas G… crean tareas por ejecución (`403 VERIFIER_NOT_AVAILABLE` para las demás). `GET /verifier/acceso` le dice al frontend si debe mostrar la opción. | `backend/ejecucion/__init__.py`, `backend/main.py`, `frontend/src/components/assisted-task-form.tsx` |
| **Producción necesita su propia VM.** El trabajador atiende una sola API (`VERIFIER_API_URL`). | `deploy.ps1` crea una segunda VM (`-Vm cyc-verificador-prod -SecretoToken …-prod`) y reutiliza las reglas de firewall y el rol si ya existen. Se probó solo en modo de mostrar los comandos. | `verifier/deploy/deploy.ps1` |

Variables nuevas documentadas en `CLAUDE.md`, `.env.example` y `backend/.env.example`.

## Pruebas

Ver «Comandos y salida» al final.

## Lo que falta para el 100%

### Técnico (código o infraestructura)

1. **Staging con su propio árbitro.** El reintento ante `txBAD_SEQ` evita el choque, pero lo correcto es que staging no firme con la llave de producción. Habría que desplegar otra instancia del mismo contrato (mismo WASM) en testnet, con otro árbitro, solo para staging. El contrato de producción no cambia. Decide Rodrigo.
2. **Probar `chromium_sandbox=True` bajo gVisor** en la VM: hoy el JavaScript de un sitio entregado corre con el sandbox de Chromium apagado, contenido solo por gVisor.
3. **Cadena de suministro del build:** `npm ci` y `pip` ejecutan scripts de instalación de paquetes permitidos, sin red y bajo gVisor. Es un riesgo aceptado; falta decidirlo por escrito.
4. **Alertas:** crear el uptime check sobre `/health/verificador` y una alerta de presupuesto en Google Cloud. Es infraestructura y requiere permiso.

### Confianza (después de la cumbre)

5. **Pruebas con personas reales en staging**, intentando colarle código que no cumple. El corpus actual (252 verificaciones, 0 falsas aprobaciones) lo escribió el mismo Claude que construyó el verificador.
6. **Recorrido del código con Rodrigo:** `regla.py`, la cola, el aislamiento y el pago. Debe poder explicarlo en una defensa.
7. **Revisión externa del aislamiento:** alguien que no lo construyó intenta escapar del contenedor.

## Lista de aceptación (la aprueba Rodrigo)

- [ ] Todas las pruebas en verde, incluidas las de Docker y las de escape en la VM de producción.
- [ ] 0 falsas aprobaciones también con las entregas de personas externas.
- [ ] Un recorrido de punta a punta en staging con el código de esta rama (script y web), con pago en testnet.
- [ ] El monitor de `/health/verificador` avisa cuando la VM está apagada y hay trabajo.
- [ ] Rodrigo revisó el código del verificador y está de acuerdo.

## Cómo se enciende en producción (cuando se apruebe; NO aplicado)

Cada paso es un cambio de producción y necesita el permiso de Rodrigo.

1. **Token de la cola propio de producción**, generado y guardado sin imprimirlo:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(48), end='')" | gcloud secrets create cyc-verifier-queue-token-prod --data-file=-
   ```
2. **Bucket de evidencia de producción:** privado, con acceso uniforme, retención de 90 días, y `objectCreator` y `objectViewer` para `cyc-api`. Igual que `cyc-evidencia-staging-…`.
3. **VM de producción:**
   ```
   ./verifier/deploy/deploy.ps1 -Vm cyc-verificador-prod -SecretoToken cyc-verifier-queue-token-prod -ApiUrl <URL de la API de producción> -Aplicar
   ./verifier/deploy/deploy.ps1 -Vm cyc-verificador-prod -Arranque -CuentaApi cyc-api@<proyecto>.iam.gserviceaccount.com -Aplicar
   ```
4. **Cloud Run `cumpleycobra-api`**, en una revisión nueva:
   - `VERIFIER_ENABLED=true`;
   - `VERIFIER_QUEUE_TOKEN` desde el secreto `-prod`;
   - `VERIFIER_VM_NAME=cyc-verificador-prod`, `VERIFIER_VM_ZONE`, `VERIFIER_VM_PROJECT`;
   - `EVIDENCE_BUCKET`;
   - al principio, `VERIFIER_ALLOWED_CLIENTS` con las cuentas de prueba.
5. **Vercel:** `NEXT_PUBLIC_VERIFIER_ENABLED=true` y redesplegar `main`. La opción solo aparece para las cuentas permitidas.
6. **Monitor:** un uptime check sobre `/health/verificador`.
7. **Abrirlo al público:** quitar `VERIFIER_ALLOWED_CLIENTS`. Cuando el verificador quede abierto, cambiar el texto de la portada (`frontend/src/app/page.tsx`), que hoy lo anuncia como «Lo que sigue».

**Cómo volver atrás:** `VERIFIER_ENABLED` vacío en una revisión nueva de Cloud Run y `NEXT_PUBLIC_VERIFIER_ENABLED` vacío en Vercel. Las tareas por ejecución ya creadas conservan su depósito on-chain: el cliente puede usar `client_release` o, al vencer el plazo, `timeout_refund`.

## Comandos y salida
