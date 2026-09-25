# Fase 5: estabilización, demo y README

Fecha: 24 y 25 de septiembre de 2026. Un punto por commit, en el orden del encargo.

## 1. `latest_rejected` en `GET /tasks/{id}`

`GET /tasks/{id}` no pide token. Respuesta real de la tarea de la fase 4b (sin `raw_request`, `description`, `criteria` ni `examples`, que son la versión acordada y pública para el programador invitado):

```text
$ curl -s localhost:8000/tasks/3Pi1ubNJqZadIooQ
```

```json
{
 "task_id": "3Pi1ubNJqZadIooQ",
 "language": "python",
 "allowed_deps": [],
 "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96",
 "amount": 5703368,
 "deadline_minutes": 5,
 "client_address": "GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL",
 "freelancer_address": "GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ",
 "submissions_used": 1,
 "max_submissions": 3,
 "onchain": {
  "amount": 5703368,
  "client": "GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL",
  "deadline": 1790305827,
  "freelancer": null,
  "rules_hash": "391136734bc9e21ecfb9626ec4aa3eb5474d4c0995412043def8fd69c4f79c96",
  "status": "Refunded",
  "task_id": "3Pi1ubNJqZadIooQ"
 },
 "seconds_left": -3510,
 "onchain_error": null,
 "latest_code_hash": "3fed1d2950769ea6f4020b18721a2654b812bb48622711e51e5a96a4cb0a0c2d",
 "consented_code_hash": "3fed1d2950769ea6f4020b18721a2654b812bb48622711e51e5a96a4cb0a0c2d",
 "latest_rejected": true
}
```

`latest_rejected` ya es un booleano junto al `code_hash`: la vista pública no incluye `reason`, `comparison`, `trace`, `logic`, `analysis` ni el código. No hubo cambios de código. El veredicto completo solo sale por `POST /evaluate` (al programador) y `GET /tasks/{id}/verdicts` (con `X-Client-Token`).

## 2. Campo del video: la causa no es un remontaje

**Síntoma (fase 4b):** en una corrida del script de capturas, el enlace tecleado en «Enlace de Google Drive al video demo» quedó vacío justo después de elegir el caso. En la misma sesión, el monto «10» del cliente se quedó en «20».

**Hipótesis revisadas en el código:**

- `useTask` consulta cada 3 s y nunca vuelve `task` a `null`: no desmonta el panel.
- `UsdcGate` sustituye a sus hijos si `wallet.address` es `null` o si `status` es `null`; tras la primera lectura, `status` no vuelve a `null`.
- «Usar la plantilla de la demo» no toca `amount`. El estado del monto vive en `AssistedTaskForm` y solo se reiniciaría si se remontara el formulario completo.

**Reproducción** con un observador (`MutationObserver`) instalado antes de cargar la página. Anota cada aparición de «Conecta tu wallet», «Revisando tu cuenta en la red» y «Cargando la tarea», y cada `<input>` nuevo:

| Secuencia | Pestaña | Resultado |
| --- | --- | --- |
| Tarea ya aceptada: pegar enlace, elegir caso A y luego C, esperar 25 s (refrescos de saldo cada 8 s y de tarea cada 3 s) | Nueva, abierta por el script | 3 de 3 conservan el enlace; un solo montaje del `<input>` |
| Aceptar una tarea nueva y pegar el enlace enseguida; muestras cada 0.5 s durante 15 s | Nueva | 5 de 5 conservan el enlace (`vvvv…`); «Conecta tu wallet» nunca aparece |
| `/cliente` → plantilla → teclear «10» en el monto | Ya abierta desde la fase 3 | 5 de 5 se quedan en «20» |
| La secuencia exacta de la corrida 4b (plantilla → invitación → aceptar → caso B → enlace) | Ya abierta | 3 de 3 se quedan vacíos |

En todas las corridas fallidas, el observador registró **un solo montaje** (`<input id=monto> montado valor=«20»`, nunca `NUEVO (remontaje)`): el campo nunca recibió el texto. En las pestañas ya abiertas:

```text
pestaña 0: {"visible":"hidden","hasFocus":true,"active":"monto"} valor tras teclear 5: 20
…
pestaña nueva: {"visible":"visible","hasFocus":true} valor tras teclear 5: 205
```

**Causa:** las pestañas que ya estaban abiertas en las ventanas de Chrome de los perfiles tenían `document.visibilityState = "hidden"` aun después de `bringToFront()`. Chrome descarta las teclas enviadas por CDP (`Input.dispatchKeyEvent`) a una pestaña oculta, aunque el campo tenga el foco. Es un artefacto de la automatización, no de la UI: una persona siempre teclea en una pestaña visible. No hay remontaje, así que no hizo falta elevar el estado ni guardarlo en `localStorage`.

**Cambio:** `frontend/scripts/fase4b-capturas.mjs` abre ahora su propia pestaña, se detiene con un error claro si la pestaña está oculta antes de teclear y conserva la comprobación del valor antes de enviar. Las 8 tareas de estas pruebas (`vCFQ8tf4nxR-efN-`, `GAktRMM5EsJWF8YT`, `hktCca_xj_vvKExS`, `V5ZR6cdj1LocbBzn`, `lYw9JaULh-Y4JBxs`, `AnPKtplSdM84S75n`, `Kdtyj19IanUix8Wj`, `EKWx_XxX0mnT447V` y `3_3jP0K8UVUmSwI3`) nunca se depositaron: solo existen en `state.json`.
