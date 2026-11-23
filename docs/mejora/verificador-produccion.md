# Verificador por ejecución: camino a producción

Rama `mejora/verificador-prod`, sobre `main` (`00dbd3f`, tag `mejora-3`). Empezó el 22 de noviembre de 2026.

**Actualización del 22 de noviembre de 2026 (noche):** a pedido de Rodrigo, el verificador quedó **encendido en producción para todos**, como beta, para que el público de la cumbre lo pueda usar. Ver «Encendido en producción» al final. La lista de aceptación de abajo sigue pendiente: es lo que falta para quitarle la etiqueta beta.

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

## Cómo se enciende en producción (aplicado el 22 de noviembre, ver al final)

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

22 de noviembre de 2026, en la rama `mejora/verificador-prod`, con Docker Desktop 29.7.2 (sin gVisor: `runsc` solo existe en la VM).

```
$ python -m pytest -q backend/tests verifier/tests
486 passed, 10 skipped, 2 warnings in 317.69s (0:05:17)
```

Los 10 saltados son los de Postgres (sin `CYC_TEST_DATABASE_URL`), los mismos que al cerrar la fase 3. Las pruebas nuevas son:
- `backend/tests/test_verificador_prod.py` (19): costo de la suite, suites trabadas, reintento, salud, lista de clientes y tope de llamadas al modelo;
- `backend/tests/test_stellar_release.py` (4): reintento ante `txBAD_SEQ`;
- 2 en `backend/tests/test_drafting.py`: borrador y revisión web.

```
$ cd frontend && npx tsc --noEmit && npm run lint && npm test
(sin errores de tipos ni de lint)
ℹ pass 27
ℹ fail 0
```

```
$ ./verifier/deploy/deploy.ps1 -Vm cyc-verificador-prod -SecretoToken cyc-verifier-queue-token-prod -ApiUrl https://ejemplo.run.app
(solo imprime los comandos: firewall, VM Spot sin cuenta de servicio y copia del código; «No se aplicó nada»)
```

No se probó en staging ni en la VM: staging comparte el árbitro con producción y no se usa hasta después de la cumbre. Es el primer punto de la lista de aceptación.

## Encendido en producción (22 de noviembre de 2026, noche)

A pedido de Rodrigo («súbelo a la demo… que si entran ahí lo puedan usar, y quitar el mensaje de que se usa LLM estático»). Orden seguido: primero staging, después producción.

| Paso | Resultado |
| --- | --- |
| Imagen | `api:aab6541` (Cloud Build, 1 min 10 s) |
| Staging | Revisión `cumpleycobra-api-staging-00006-v8q` y código nuevo en la VM `cyc-verificador`. Tarea `Q2BXmA5FD6q03bg6`: suite lista en 68.6 s; caso B rechazado por los tests (bucle infinito); caso A aprobado y pagado en 20.8 s, tx `cd98014f9db95bbc574659ee755a3a61233b789369cf1d9f4ea00b08ef873367`, `Released` |
| Token de producción | Secreto `cyc-verifier-queue-token-prod`, generado sin imprimirse; `secretAccessor` para `cyc-api` |
| Evidencia | Bucket `cyc-evidencia-prod-1017372721585`: privado (acceso uniforme y `public_access_prevention`), borrado a los 90 días, `objectCreator` y `objectViewer` para `cyc-api` |
| VM | `cyc-verificador-prod` (e2-standard-2 Spot, sin cuenta de servicio), creada con `deploy.ps1`; reutilizó las reglas de firewall y el rol. gVisor `release-20261116.0`, imágenes del runner, del web runner y del proxy construidas. El rol de encendido se otorgó solo sobre esta VM. Metadato `verifier-idle-secs=3600` (rige desde el siguiente arranque) |
| API de producción | Revisión `cumpleycobra-api-00005-rs5`, imagen `api:aab6541`, con `VERIFIER_ENABLED=true`, `VERIFIER_QUEUE_TOKEN` (secreto `-prod`), `VERIFIER_VM_*` y `EVIDENCE_BUCKET`. Sin `VERIFIER_ALLOWED_CLIENTS`: abierto a todos. Límites del modo `demo`: 10 suites activas, 2 por minuto por IP, 50 suites y 200 verificaciones al día. Sigue con 1 instancia mínima. Lo anterior responde igual (`/demo`, `/fx/usd-mxn`, la tarea de ensayo `7IU46sQJ469img4l` en `Released`) |
| Recorrido real en producción | Tarea `LmCJh9GYgKmxf3fI`: suite lista en 62.7 s; caso A aprobado y pagado en 20.9 s, tx `06d01104c02c1faeb545637d49044b753ab77beeb280e201b380bf1d442802bf`, `Released` |
| Frontend | `NEXT_PUBLIC_VERIFIER_ENABLED=true` en Vercel (producción) y `main` (`6fce55d`) desplegado. En el sitio publicado, `VERIFIER_ENABLED` compila a `true`; la portada dice «Nuevo · beta» y el pie «Verificación por ejecución en un contenedor aislado» |

Cómo volver atrás:
- API: `gcloud run services update-traffic cumpleycobra-api --region=us-central1 --to-revisions=cumpleycobra-api-00004-nhk=100` (la revisión anterior, sin verificador).
- Frontend: `vercel promote https://cumpleycobra-g7z213a7d-rodyx-dev.vercel.app` (el despliegue anterior), o quitar `NEXT_PUBLIC_VERIFIER_ENABLED` y redesplegar.
- VM: `gcloud compute instances stop cyc-verificador-prod --zone=us-central1-a`.
- Para cerrarlo sin apagarlo: `VERIFIER_ALLOWED_CLIENTS` con las cuentas de prueba.

Pendiente: la lista de aceptación (pruebas con personas externas, sandbox de Chromium, árbitro propio de staging y tu revisión del código), el monitor sobre `/health/verificador` y el texto de la portada cuando deje de ser beta. Después de la cumbre: devolver el mínimo de instancias a 0.

### Revisión de pantallas en producción con una sesión real de Pollar (22 de noviembre, noche)

Recorrido de Rodrigo y Claude en https://cumpleycobra.vercel.app con la wallet `GA7MXQ…BEVJ` (cliente y programador a la vez):
- Tarea `Fzw_5tOvZG-FmM7o`: suite lista en alrededor de un minuto; depósito con Pollar `985cd992…`.
- Caso C rechazado por señales de inyección, sin pago.
- Caso A aprobado y pagado en 18.4 s, tx `c806382e0c353c5269174eecfb01f7032f4dab92b9981694c2234b3963e57345`. La vista del cliente dice «Pagada», con los dos veredictos y «Ver código».

Hallazgos, corregidos y publicados el mismo día (`c3e707e`, `d89aa06`), y comprobados en el sitio:

| Hallazgo | Arreglo |
| --- | --- |
| La interfaz sugerida tomaba prosa por código: «precios (números)» → función `precios` | Solo se sugiere una firma real (nombre pegado al paréntesis y, además, guion bajo, tipos o retorno); si no hay, los campos quedan en blanco |
| El programador no veía el módulo ni la firma antes de aceptar | La tarjeta de criterios muestra «Lo que tu entrega debe exponer» (archivo y firma) y las páginas del perfil web |
| En celular, el plan de la suite empujaba la invitación y el depósito muy abajo | Antes del depósito, la tarjeta con la invitación y «Depositar» va arriba del plan |
| Un rechazo por inyección decía «No cumple lo acordado» con 4 de 4 criterios cumplidos | «Rechazado por un aviso de seguridad» y «4 de 4 criterios, pero hay un aviso de seguridad» |
