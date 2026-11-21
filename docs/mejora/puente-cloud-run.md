# Puente: backend de Railway a Cloud Run

Fecha: 20 de noviembre de 2026. Se acabó el plan gratuito de Railway y `/health` respondía 404. Es un puente para la cumbre: mismo contenedor y mismo `state.json`. Postgres llega en la fase 1.

## Qué quedó

| Pieza | Valor |
| --- | --- |
| API | `https://cumpleycobra-api-1017372721585.us-central1.run.app` (servicio `cumpleycobra-api`, `us-central1`) |
| Imagen | Artifact Registry `cumpleycobra/api`, construida con Cloud Build desde `backend/Dockerfile` |
| Instancias | `--max-instances=1` (candados en memoria) y `--min-instances=1` durante la cumbre; después, 0 |
| Estado | `STATE_FILE=/data/state.json` en un volumen de Cloud Storage (bucket `<proyecto>-cyc-state`, con versiones) |
| Secretos | Secret Manager: `cyc-arbiter-secret-key`, `cyc-sep10-signing-secret` y `cyc-session-secret` (los dos últimos son nuevos, distintos de los locales) |
| Cuenta de servicio | `cyc-api`, con `aiplatform.user`, acceso a esos tres secretos y `storage.objectUser` en el bucket. Vertex funciona sin llaves JSON |
| IP del cliente | `CLIENT_IP_HEADER=x-forwarded-for` y `TRUSTED_PROXY_HOPS=0`: se usa la última IP de `X-Forwarded-For`, la que agrega Cloud Run |
| Límites | `RATE_LIMIT_PER_MINUTE=10` y `RATE_LIMIT_DAILY=500` |
| Frontend | `NEXT_PUBLIC_API_URL` de Vercel (Production) apunta a la API nueva; producción se volvió a desplegar |

Nunca se subió `backend/.env` ni `state.json`. La imagen se construyó desde una copia de los archivos de `backend/` que están en git, sin los tests.

## Verificación (20 de noviembre, salida real)

- `GET /health` → `{"ok":true}`. CORS devuelve `access-control-allow-origin: https://cumpleycobra.vercel.app`, y `/auth/challenge` entrega un reto SEP-10.
- `POST /tasks/draft` → 200 en 4.8 s: Gemini por Vertex con la cuenta de servicio.
- **IP falsa:** 32 peticiones a `/auth/challenge`, cada una con un `X-Forwarded-For` y un `X-Real-IP` distintos. A partir de la 30 (contando una anterior), todas reciben `429`: falsificar los encabezados no salta el límite.
  - No se pudo comprobar desde una sola máquina que dos visitantes distintos tengan límites separados.
- **Recorrido con pago en testnet:**
  1. `scripts/tarea_respaldo.py` creó la tarea `IOBR3hBqNPWoM6Ko` y depositó 1 USDC: [tx `a1564b11…`](https://stellar.expert/explorer/testnet/tx/a1564b11470df0e9ace928a74148157db4d0de8f83abf6d0c769b063e2f772fc).
  2. `cyc-freelancer` aceptó la tarea.
  3. `/evaluate` con el caso A: aprobado (`stage: llm`) en 8.3 s y `release` automático, [tx `e5284043…`](https://stellar.expert/explorer/testnet/tx/e5284043bdfde33173e64608cd15bbff6ea9a0ae50097763508254e9dc19db48). Al final, el contrato muestra la tarea `Released` y pagada al programador amarrado.
- **Reinicio:** se forzó una revisión nueva; `GET /tasks/{id}/verdicts` siguió devolviendo el veredicto con su transacción.

## No verificado

- El recorrido en el navegador con Pollar (login, trustline, depósito firmado) contra la API nueva. El frontend ya apunta a ella (está en los bundles de producción), pero falta un recorrido con wallets reales.
- Alertas de presupuesto: no se configuraron.

## Límites del puente

- En gcsfuse, `os.replace` no es atómico (copia y borra). Con una sola instancia basta.
- Durante un despliegue, la revisión vieja y la nueva conviven unos segundos sobre el mismo bucket. No desplegar durante la demo.
- El estado de Railway se perdió: la API empezó vacía. Los pagos anteriores siguen en el contrato.

## Desplegar una versión nueva

Desde PowerShell. En Git Bash, la conversión de rutas convierte `/data` en una ruta de Windows y el despliegue falla.

```powershell
# 1) Contexto limpio: solo los archivos de backend/ que están en git, sin tests
# 2) gcloud builds submit <contexto> --tag us-central1-docker.pkg.dev/<proyecto>/cumpleycobra/api:<tag> --region=us-central1
gcloud run deploy cumpleycobra-api --region=us-central1 --image=us-central1-docker.pkg.dev/<proyecto>/cumpleycobra/api:<tag>
```

`gcloud run deploy` con solo `--image` conserva las variables, los secretos, el volumen y las instancias de la revisión anterior.
