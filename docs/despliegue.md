# Despliegue: frontend en Vercel y backend en Railway

Frontend (Next.js, carpeta `frontend/`) en **Vercel**, y backend (FastAPI) en **Railway**. El backend corre como **un solo proceso** con un **volumen persistente** en `/data`. El camino recomendado para Gemini en producción es **Vertex AI con una cuenta de servicio**, cargada desde `GOOGLE_CREDENTIALS_B64`. AI Studio con API key queda como alternativa. Todo sigue en la testnet de Stellar.

Los secretos nunca pasan por el chat ni por el repositorio. Se pegan directo en los paneles de Vercel y Railway desde tu `backend/.env` y `frontend/.env.local`.

## 0. Orden: primero los dos dominios, después las variables

El backend necesita el dominio del frontend (CORS y SEP-10), y el frontend necesita el del backend (`NEXT_PUBLIC_API_URL`). Por eso:

1. Crea el servicio de Railway y genera su dominio (paso 1). Anota `https://<backend>.up.railway.app`.
2. Crea el proyecto de Vercel (paso 2). Anota `https://<frontend>.vercel.app`.
3. Carga las variables de los dos (pasos 1.4 y 2.3) y vuelve a desplegar ambos.
4. Agrega el dominio de Vercel en Pollar (paso 3).
5. Verifica (paso 5).

## 1. Railway (backend)

1. **Nuevo proyecto → Deploy from GitHub repo →** `rodyxdev/cumpleycobra`. Rama: `despliegue` para la prueba; `main` después de fusionar. La raíz del servicio es la **raíz del repositorio**, no `backend/`: la imagen se construye desde ahí.
2. **La configuración ya está en el repositorio (`railway.json`):**
   - construcción con `backend/Dockerfile`;
   - `numReplicas: 1` y `overlapSeconds: 0` (nunca dos procesos a la vez);
   - `requiredMountPath: /data`: el despliegue no arranca sin el volumen;
   - health check en `/health` (timeout de 60 s);
   - reinicio si falla.

   No cambies réplicas ni actives escalado horizontal.
3. **Volumen:** crea un volumen para el servicio y móntalo en **`/data`**. Ahí vive `state.json` (`STATE_FILE=/data/state.json` ya viene en la imagen). Sin volumen, cada despliegue borraría tareas, tokens y veredictos.
4. **Variables** (Service → Variables). Copia los valores de tu `backend/.env`, salvo los indicados:

| Variable | Valor |
| --- | --- |
| `GOOGLE_GENAI_USE_VERTEXAI` | `true` para Vertex AI (recomendado) |
| `GOOGLE_CREDENTIALS_B64` | JSON completo de una cuenta de servicio codificado en base64, en una sola línea (paso 4). Solo rol **Vertex AI User** (`roles/aiplatform.user`). |
| `GOOGLE_CLOUD_PROJECT` | ID del proyecto de Google Cloud donde se usa Vertex AI |
| `GOOGLE_CLOUD_LOCATION` | `global`, o la ubicación compatible con el modelo configurado |
| `GEMINI_API_KEY` | Solo para la alternativa AI Studio, con `GOOGLE_GENAI_USE_VERTEXAI=false` y sin `GOOGLE_CREDENTIALS_B64` |
| `GEMINI_MODEL` | El mismo que en local (`gemini-3.5-flash`), disponible en el proveedor y ubicación elegidos |
| `ARBITER_SECRET_KEY` | La del árbitro con que se inicializó el contrato (tu `backend/.env`) |
| `CONTRACT_ID`, `USDC_SAC_ID`, `STELLAR_RPC_URL`, `NETWORK_PASSPHRASE` | Los mismos de `.env.example` / `backend/.env` |
| `FRONTEND_ORIGIN` | `https://<frontend>.vercel.app`, sin barra final. Admite varios separados por comas (por ejemplo, una vista previa de Vercel). |
| `SEP10_SIGNING_SECRET` | Una llave **nueva y sin fondos**, **nunca** la del árbitro. Recomendado: una distinta de la local (cómo generarla, en CLAUDE.md). |
| `SESSION_SECRET` | Un secreto largo y aleatorio, distinto del local |
| `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_DAILY` | Límite de peticiones al motor (punto 4). Recomendado para la entrega: `10` y `500`. |

   **Opcionales**, porque ya tienen buen valor por defecto:
   - `STATE_FILE`: la imagen ya trae `/data/state.json`.
   - `SEP10_HOME_DOMAIN`: si falta, el host del primer `FRONTEND_ORIGIN`.
   - `SEP10_WEB_AUTH_DOMAIN`: si falta, `RAILWAY_PUBLIC_DOMAIN`, que Railway inyecta solo.
   - `HORIZON_URL`: testnet por defecto.

   **No** van en Railway las variables `NEXT_PUBLIC_*`. Las `GOOGLE_CLOUD_*` sí son necesarias al usar Vertex AI.
5. **Dominio:** Settings → Networking → *Generate Domain*. Railway le pasa el puerto en `PORT` y la imagen lo usa.
6. **Estado inicial:** el volumen empieza vacío, así que la versión pública arranca sin las tareas de los ensayos locales. No subas tu `state.json` local: tiene los tokens de esas tareas.

### Por qué un solo proceso

`backend/Dockerfile` arranca `uvicorn … --workers 1`. En memoria de ese proceso viven:

- el `asyncio.Lock` de cada tarea (envíos y escrituras);
- el `threading.Lock` del `release` (todas las firmas del árbitro comparten su número de secuencia);
- los retos SEP-10 pendientes, las cachés de estados on-chain y el límite de peticiones.

`state.json` se escribe sin coordinación entre procesos. Con dos workers o dos réplicas, dos procesos podrían:

- contar envíos o firmar dos `release` con la misma secuencia;
- aceptar dos veces el mismo reto;
- pisarse al escribir `state.json`.

**Costo:** cada nuevo despliegue apaga el proceso anterior antes de arrancar el nuevo (unos segundos sin servicio). Es a propósito: nunca hay dos procesos sobre el mismo volumen.

## 2. Vercel (frontend)

1. **Add New → Project → Import** `rodyxdev/cumpleycobra`.
2. **Root Directory: `frontend`.** Framework: Next.js (se detecta solo); los comandos quedan por defecto (`npm install`, `next build`).
3. **Variables** (Project → Settings → Environment Variables, para *Production* y, si vas a probar vistas previas, también *Preview*):

| Variable | Valor |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://<backend>.up.railway.app`, sin barra final. **Obligatoria:** sin ella, el frontend de producción no llama a nada, y el error lo dice. |
| `NEXT_PUBLIC_POLLAR_API_KEY` | La clave publicable de testnet (`pub_testnet_…`) de tu `frontend/.env.local` |
| `NEXT_PUBLIC_CONTRACT_ID` | `CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ` |
| `NEXT_PUBLIC_WALLET` | `pollar` |
| `NEXT_PUBLIC_STELLAR_RPC_URL` | `https://soroban-testnet.stellar.org` (opcional; es el valor por defecto) |
| `NEXT_PUBLIC_USDC_ASSET` | `USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` (opcional; es el valor por defecto) |

4. Las `NEXT_PUBLIC_*` se incrustan **al construir**: si cambias una, vuelve a desplegar (Deployments → Redeploy).
5. El enlace de invitación usa `window.location.origin`, así que en producción sale con el dominio de Vercel sin configurar nada.

## 3. Pollar (dashboard.pollar.xyz)

1. **Build → Domains:** agrega `https://<frontend>.vercel.app`, sin barra final, y deja `http://localhost:3000` para seguir probando local. Sin esto, la API de Pollar responde `403 ORIGIN_NOT_ALLOWED` desde Vercel.
2. **Autenticación:** el login por correo (OTP) no necesita redirecciones. Si activas Google, agrega `https://<frontend>.vercel.app` a sus URIs de redirección (sin ellas: `APPLICATION_HAS_NO_REDIRECT_URIS`).
3. Sin cambios respecto a lo local:
   - Treasury → Tokens & Trustlines (USDC);
   - Treasury → Auth Policy (el contrato);
   - Treasury → Sponsorship activo.

   Revisa que la gas wallet de Pollar tenga XLM (ver `docs/demo.md`): un juez con wallet nueva activa USDC con 0 XLM gracias al patrocinio.
4. La API key publicable es la misma de testnet.

## 4. Credenciales de Gemini

### Vertex AI: recomendado para producción

1. En Google Cloud, elige el proyecto con facturación y Vertex AI habilitados. En **IAM y administración → Cuentas de servicio → Crear cuenta de servicio**, crea una cuenta dedicada y asígnale únicamente **Vertex AI User** (`roles/aiplatform.user`) sobre ese proyecto. No necesita Owner ni Editor. [Rol para usar Gemini en Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart).
2. Abre esa cuenta → **Claves → Agregar clave → Crear clave nueva → JSON**. Descarga el archivo en una carpeta privada fuera del repositorio. La persona que crea la clave necesita permisos de administración de claves; esos permisos no se asignan a la cuenta del backend. [Crear una clave JSON en la consola de IAM](https://docs.cloud.google.com/iam/docs/keys-create-delete).
3. Codifica el archivo completo en base64 y pega el resultado directamente en **Railway → Variables → `GOOGLE_CREDENTIALS_B64`**. Por ejemplo, en PowerShell este comando lo copia al portapapeles sin imprimirlo en la consola (sustituye solo la ruta):

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\ruta-privada\cuenta-servicio.json')) | Set-Clipboard
   ```

   No pegues el JSON ni su base64 en chats, logs o archivos del repositorio. Base64 no cifra el contenido. Después de pegarlo en Railway, limpia el portapapeles.
4. Configura `GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` y `GEMINI_MODEL`. No hace falta `GEMINI_API_KEY` para este camino. El proyecto usado para las peticiones sigue siendo el indicado por `GOOGLE_CLOUD_PROJECT`.

**Cómo lo carga el backend:** `lifespan` llama a `gemini.make_client` al arrancar. Se decodifica base64 como UTF-8 y JSON, se comprueban `type=service_account` y los campos no vacíos `project_id`, `private_key`, `client_email` y `token_uri`, y google-auth valida el formato de la llave. Luego se construyen `service_account.Credentials.from_service_account_info(..., scopes=["https://www.googleapis.com/auth/cloud-platform"])` y `genai.Client(vertexai=True, credentials=..., project=..., location=...)`.

Las credenciales permanecen **en memoria**: no se crea ningún archivo en `/tmp`, `/data` ni otra ruta, y no se modifica `GOOGLE_APPLICATION_CREDENTIALS`. `/data` sigue reservado al estado de tareas. Si la variable existe pero está vacía, no es base64/JSON válido o no contiene una cuenta de servicio válida, el arranque falla con `ConfigError: GOOGLE_CREDENTIALS_B64 inválida...`. El error no incluye valores del secreto ni encadena excepciones internas del parser o del SDK. Validar su formato no comprueba permisos remotos ni que la clave siga activa: eso se verifica al llamar a Vertex.

**Desarrollo local sin cambios:** si `GOOGLE_CREDENTIALS_B64` no existe, se mantiene el constructor anterior y ADC local, por ejemplo con `gcloud auth application-default login`. No definas la variable como una cadena vacía para usar ADC: elimínala o déjala comentada en `.env`. El ejemplo específico del backend está en `backend/.env.example`.

### AI Studio: alternativa si la organización bloquea las llaves

Si una política de tu organización impide crear claves de cuentas de servicio, usa la alternativa existente de AI Studio:

1. En [Google AI Studio](https://aistudio.google.com), crea una API key y pégala en Railway como `GEMINI_API_KEY`. Nunca en Vercel.
2. Configura `GOOGLE_GENAI_USE_VERTEXAI=false` y **elimina** `GOOGLE_CREDENTIALS_B64`. En este modo no se requieren `GOOGLE_CLOUD_PROJECT` ni `GOOGLE_CLOUD_LOCATION`. El backend conserva `genai.Client(api_key=...)`. Si dejas credenciales explícitas de cuenta de servicio con Vertex desactivado, el arranque informa de la configuración incompatible sin mostrar el secreto.
3. Elige un modelo disponible para tu clave en `GEMINI_MODEL`. La prueba de punta a punta confirma que responde; el test existente de AI Studio se conserva.

**Cuota:** los límites dependen del proyecto, modelo y proveedor elegidos. `RATE_LIMIT_PER_MINUTE` y `RATE_LIMIT_DAILY` limitan las peticiones al motor por IP/minuto y por día globalmente.

## 5. Verificación después de desplegar

```bash
curl -s https://<backend>.up.railway.app/health            # {"ok":true}
curl -s https://<backend>.up.railway.app/fx/usd-mxn         # "source":"Frankfurter"
curl -s "https://<backend>.up.railway.app/auth/challenge?address=GA7MXQO3OL6IMISROP3JJM3NBGOEDHPPK7B5Q2ASNIBNVAPVCE6FBEVJ"
#   home_domain = <frontend>.vercel.app, web_auth_domain = <backend>.up.railway.app
curl -s -o /dev/null -w "%{http_code}\n" -X OPTIONS https://<backend>.up.railway.app/tasks \
  -H "Origin: https://<frontend>.vercel.app" -H "Access-Control-Request-Method: POST"   # 200
```

En el navegador, en `https://<frontend>.vercel.app/cliente`:

1. Inicia sesión con Pollar, arma el pedido asistido y crea una tarea.
2. Deposita, y ve el depósito en el explorador.
3. Luego se hace la prueba de punta a punta con las dos wallets y una wallet Pollar nueva (segunda sesión del encargo).

Los scripts de ensayo aceptan la URL pública:

```bash
cd frontend
CYC_APP_URL=https://<frontend>.vercel.app CYC_API_URL=https://<backend>.up.railway.app node scripts/fase5-ensayo.mjs
```

## Variables por servicio (resumen de nombres)

| Servicio | Variables |
| --- | --- |
| Railway | `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CREDENTIALS_B64`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` (Vertex); `GEMINI_API_KEY` (alternativa AI Studio); `GEMINI_MODEL`, `ARBITER_SECRET_KEY`, `CONTRACT_ID`, `USDC_SAC_ID`, `STELLAR_RPC_URL`, `NETWORK_PASSPHRASE`, `FRONTEND_ORIGIN`, `SEP10_SIGNING_SECRET`, `SESSION_SECRET`, `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_DAILY`. Opcionales: `STATE_FILE`, `SEP10_HOME_DOMAIN`, `SEP10_WEB_AUTH_DOMAIN`, `HORIZON_URL`. |
| Vercel | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_POLLAR_API_KEY`, `NEXT_PUBLIC_CONTRACT_ID`, `NEXT_PUBLIC_WALLET`. Opcionales: `NEXT_PUBLIC_STELLAR_RPC_URL`, `NEXT_PUBLIC_USDC_ASSET`. |
| Pollar | Dominio `https://<frontend>.vercel.app` (y URIs de redirección si usas Google). |
| Google Cloud / AI Studio | Cuenta de servicio con solo Vertex AI User; alternativamente una API key de AI Studio. Los secretos van solo en Railway. |

## Respaldo si Railway falla: Render o Fly

Mismos requisitos: un solo proceso, volumen en `/data`, health check en `/health` y las mismas variables.

- **Render:** Web Service con Docker (Dockerfile path `backend/Dockerfile`, contexto en la raíz). Disco persistente montado en `/data`, 1 instancia, Health Check Path `/health`. Render inyecta `PORT`. Pon `SEP10_WEB_AUTH_DOMAIN` con el dominio `.onrender.com`, porque `RAILWAY_PUBLIC_DOMAIN` no existe ahí.
- **Fly.io:** `fly launch` con el Dockerfile. Un volumen `fly volumes create data`, montado en `/data` en `fly.toml`, y **una sola máquina** (`fly scale count 1`). Pon `SEP10_WEB_AUTH_DOMAIN` con el dominio `.fly.dev`.

## 6. Tareas para jueces (solo después de la prueba de punta a punta)

`scripts/tareas_jueces.py` crea N tareas depositadas por `cyc-client`, de 1 USDC y 7 días cada una. Escribe sus enlaces de invitación e instrucciones para el juez en `docs/probar-en-linea.md`:

1. entrar al enlace;
2. iniciar sesión con Pollar;
3. activar USDC;
4. aceptar los criterios;
5. enviar C y luego A;
6. ver el pago.

Primero, `--comprobar` revisa el backend y el saldo sin crear nada:

```bash
CYC_APP_URL=https://<frontend>.vercel.app CYC_API_URL=https://<backend>.up.railway.app \
  backend/.venv/Scripts/python scripts/tareas_jueces.py --n 5 --comprobar
CYC_APP_URL=https://<frontend>.vercel.app CYC_API_URL=https://<backend>.up.railway.app \
  backend/.venv/Scripts/python scripts/tareas_jueces.py --n 5
```

Protecciones del script:

- Se niega a generar enlaces con `localhost` o sin `https`.
- Revisa que `cyc-client` tenga USDC suficiente antes de depositar.
- Confirma en el contrato que cada tarea quedó `Funded`.
- Los `client_token` quedan solo en `scripts/.logs/tareas-jueces.json` (ignorado por git).

Cada enlace lo toma la primera wallet que acepta. Las tareas que nadie use se reembolsan a `cyc-client` con `timeout_refund` al vencer el plazo.

## Soporte local de GOOGLE_CREDENTIALS_B64 (27 de septiembre de 2026)

Cambio limitado a `backend/gemini.py`, `backend/tests/test_vertex_credentials.py`, `backend/.env.example` y este documento, sobre la rama existente `despliegue`. Sin cambios en `main`, Railway, el frontend, las rutas del backend ni el motor de evaluación.

Se verificaron las APIs en el código instalado: `google-genai 2.25.0` (`google/genai/client.py`: parámetro `credentials`) y `google-auth 2.58.0` (`google/oauth2/service_account.py`: `from_service_account_info` y `scopes`). No se añadieron dependencias.

Los tests usan únicamente un JSON ficticio con dominio `example.invalid` y una cadena que explícitamente no es una llave. En el caso de formato válido se sustituye solo el lector criptográfico por un firmante falso; se construyen los objetos reales de google-auth y google-genai sin llamar a la red. Los casos inválidos ejercitan el arranque real de FastAPI. También se verifican ADC, AI Studio, stdout, stderr, logs y traceback, incluyendo una excepción del SDK que deliberadamente contiene datos ficticios y debe quedar oculta.

No se accedió a Railway ni a una cuenta de servicio real, y no se imprimió ni guardó en archivos ninguna credencial real. La autenticación contra Vertex desplegado queda fuera de esta comprobación local.

Validación local (desde la raíz):

```text
backend/.venv/Scripts/python -m pytest -q
261 passed, 2 warnings
```

Incluye 20 casos nuevos y todos los tests anteriores. Las dos advertencias existentes son deprecaciones de TestClient/httpx y google-genai (`_UnionGenericAlias`); no se cambiaron esas dependencias por estar fuera del alcance. `git diff --check` terminó sin errores.
