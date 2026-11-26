# Instaward de Stellar: seguimiento de avances

Fuente de lo prometido: el SOW enviado el 8 de noviembre de 2026. Ni los entregables ni los sub-ítems se cambian aquí: solo se registra su estado. Cuando llegue el formato oficial, esta tabla se adapta a él sin perder el registro.

- **Alcance:** testnet.
- **Fuera de alcance:** mainnet y dinero real, funciones nuevas del contrato, auditoría formal, proceso legal, fiscal o KYC de usuarios, app móvil, marketing y otros lenguajes.
- **Inicio sugerido del sprint:** 30 de noviembre de 2026 (flexible). El revisor confirmó que se puede avanzar antes.

**Reglas del registro:**
- **hecho:** solo con evidencia verificable (commit, URL pública o transacción de testnet).
- **parcial:** existe una parte, y la columna «Notas» dice qué falta.
- **pendiente:** no hay nada todavía.
- Cada avance nuevo se sube por separado, con el prefijo `instaward(avance-N): …`, y se anota aquí.

Revisado contra el repositorio el 23 de noviembre de 2026, sobre `main` en `6c62e1b`.

## Entregable 1: motor de verificación por ejecución, desplegado

| # | Avance prometido | Estado | Fecha | Commits | Evidencia | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| 1.1 | Pruebas ocultas | hecho | 21–22 nov | `9d6e9ff` (suite, cola, juez y regla), tag `mejora-3` (`00dbd3f`) | Producción, tarea `Fzw_5tOvZG-FmM7o`: caso A pagado, tx `c806382e0c353c5269174eecfb01f7032f4dab92b9981694c2234b3963e57345`. Staging, tarea `Q2BXmA5FD6q03bg6`: caso B rechazado por los tests ocultos | La suite se valida contra una entrega vacía y contra una implementación de referencia antes de aceptarla |
| 1.2 | Chequeos de API de caja negra | parcial | 21 nov | `21188e6` (caja negra con `cc_channel`) | Los tests llaman a la entrega sin ver su código: funciones y clases | Falta lo HTTP: `asgi_app` existe en `verifier/contract.py`, pero `POST /tasks` responde «Por ahora la verificación por ejecución solo acepta funciones y clases» |
| 1.3 | Chequeos en navegador real con capturas (web) | hecho | 22 nov | `5289bb1` (perfil web y corpus web) | Staging, tarea `ayQbmUldqXKfejlK`, pagada con tx `698dada572c3b3cd2cd42802ac0ae07edfad0d118252c0133e99e9dc7796b0d8`; capturas a 1440 y 390 px | En producción todavía no se ha corrido una tarea web |
| 1.4 | Runner aislado en un servicio separado | hecho | 21–22 nov | `21188e6`, `a356270`, `6fce55d` | VM `cyc-verificador-prod`, sin credenciales, con gVisor (`runsc release-20261116.0`); `GET /health/verificador` en la API de producción | Detalle en `docs/mejora/verificador-produccion.md` |
| 1.5 | Modelo de IA configurable (Gemini, Muse Spark u otro) | hecho | 21 nov | `9d6e9ff` (`backend/llm.py`) | `LLM_SUITE_PROVIDER` y `LLM_JUEZ_PROVIDER` aceptan `gemini` o `muse` | Medido solo con Gemini 3.5 Flash. Muse está soportado, pero sin medir |
| 1.6 | Todo cambio de modelo pasa un corpus de 60 casos con 0 falsas aprobaciones | parcial | 21–22 nov | `159d80a` (corpus de 60 y `scripts/correr_corpus.py`), `5289bb1` (corpus web) | `docs/mejora/fase-3.md`: 213 verificaciones de script y 39 web, 0 falsas aprobaciones (Gemini) | El corpus y el resultado existen. Falta: (a) una puerta automática que impida cambiar de modelo sin pasarlo; (b) correrlo con Muse |
| 1.E1 | Evidencia: repo y tag de release | parcial | 22 nov | tag `mejora-3` (`00dbd3f`) | https://github.com/rodyxdev/cumpleycobra | Falta un tag de release que incluya lo desplegado en producción (`6fce55d` en adelante) |
| 1.E2 | Evidencia: URL pública donde una entrega se aprueba y otra se rechaza tras ejecutarse | hecho | 22 nov | `6fce55d`, `d89aa06`, `c61d08f` | https://cumpleycobra.vercel.app/probar. Tarea `Fzw_5tOvZG-FmM7o`: caso C rechazado por inyección y caso A aprobado y pagado (tx `c806382e…` de 1.1) | Beta abierta a todos desde el 22 de noviembre |
| 1.E3 | Evidencia: resultados de pytest y del corpus | hecho | 22 nov | `00dbd3f`, `6b679aa` | `docs/mejora/fase-3.md` (463 en verde al cerrar la fase) y `docs/mejora/verificador-produccion.md` (486 en verde con Docker); tablas del corpus en `fase-3.md` | — |
| 1.E4 | Evidencia: capturas y video corto de ambos veredictos | parcial | 22 nov | rama `cumbre/preparacion` (sin fusionar) | `docs/cumbre/*.png` en esa rama: plan de chequeos, veredicto web pagado y galería | Falta el video de un rechazo y una aprobación ejecutando. El video `recorrido-demo.mp4` es del motor estático |

## Entregable 2: base productiva

| # | Avance prometido | Estado | Fecha | Commits | Evidencia | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| 2.1 | Base de datos gestionada con respaldos automáticos | hecho | 20–21 nov | `99c1607` (Postgres), tag `mejora-1` (`660f860`) | Cloud SQL `cyc-pg` (Postgres 17): 7 respaldos automáticos y recuperación a un punto en el tiempo, según la configuración leída el 22 de noviembre | — |
| 2.2 | Chequeos de salud del backend y del runner | parcial | 21–22 nov | `b915b67` (`/health/verificador`) | `GET /health` y `GET /health/verificador` en https://cumpleycobra-api-1017372721585.us-central1.run.app | El runner se mide por la cola, no tiene endpoint propio. Falta el monitor externo (uptime check) |
| 2.3 | Logs | parcial | — | — | Cloud Run envía sus logs a Cloud Logging | La VM no tiene cuenta de servicio: sus logs se quedan en `journald` y no llegan a Cloud Logging. Falta decidir cómo exportarlos sin darle credenciales |
| 2.4 | Límites de recursos por ejecución | hecho | 21 nov | `21188e6` | `verifier/sandbox/runner.py` (`SandboxLimits`: CPU, memoria, procesos, tiempo y salida); gVisor, sin red, `--read-only`, como `nobody` | — |
| 2.5 | Documento público de arquitectura y seguridad, con los límites conocidos del aislamiento | parcial | 25 nov | este commit (`instaward(avance-2.5)`) | `docs/arquitectura-y-seguridad.md` (arquitectura, flujo, aislamiento, regla final, límites conocidos y reporte de seguridad) | Falta confirmar el contacto de seguridad (sección 6) y hacer push a `main` en GitHub para publicarlo |
| 2.E1 | Evidencia: URL de salud del backend y del runner | parcial | 22 nov | `b915b67` | Las mismas URL de 2.2 | Mismo faltante que 2.2 |
| 2.E2 | Evidencia: commit de la migración a la base de datos | hecho | 20–21 nov | `99c1607` (`001_inicial`), `9d6e9ff` (`002_verificador`) | `backend/storage/migrations/` | — |
| 2.E3 | Evidencia: captura de una restauración exitosa | parcial | 21 nov | `660f860` | `docs/mejora/fase-1.md`: `RESTORE_VOLUME` en estado `DONE` y los mismos conteos que el original | Hay registro de texto, pero no una captura |
| 2.E4 | Evidencia: documento publicado | parcial | 25 nov | este commit (`instaward(avance-2.5)`) | `docs/arquitectura-y-seguridad.md` en commit local de `main` | Falta hacer push a GitHub para publicarlo en URL pública y confirmar el contacto de seguridad |

## Entregable 3 (opcional): validación real y reporte público

| # | Avance prometido | Estado | Fecha | Commits | Evidencia | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| 3.1 | 3 tareas reales de punta a punta en testnet con USDC, con al menos 2 participantes distintos a Rodrigo | pendiente | — | — | — | Las tareas de `/probar` en la cumbre no cuentan mientras no se confirme quién las usó |
| 3.2 | Reporte con tasa de aprobación, falsas aprobaciones, costo y latencia por verificación, feedback y enlaces a transacciones | pendiente | — | — | — | — |
| 3.3 | Modelo de costos: costo fijo mensual, costo por verificación y comisión propuesta | pendiente | — | — | — | Hay un borrador de costos validados en `docs/mejora/plan.md` de la rama `cumbre/preparacion` (`a741fbc`, sin fusionar); no es el reporte |
| 3.E1 | Evidencia: reporte público (PDF o web) | pendiente | — | — | — | — |
| 3.E2 | Evidencia: hashes en stellar.expert verificables con el script del repo | pendiente | — | — | — | El script `scripts/verificar_pago.py` ya existe; falta aplicarlo a las tareas del reporte |
| 3.E3 | Evidencia: resumen del feedback | pendiente | — | — | — | — |
| 3.E4 | Evidencia: video demo | pendiente | — | — | — | — |
