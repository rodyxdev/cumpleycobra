# Ship It: Builder Challenge (BAF x Stellar)

Del 23 al 27 de noviembre de 2026. Cuentan los commits a `main` por su calidad, no por su volumen: nada de commits vacíos ni de relleno. Cada día a las 00:00 (hora de la Ciudad de México) se abre una misión.

**Convenciones:**
- Los commits del reto llevan el prefijo `ship-it: …`.
- Los del Instaward llevan otro prefijo (`instaward(avance-N): …`) y se registran en `docs/instaward/seguimiento.md`.

**Despliegue:** cada push a `main` despliega el frontend en Vercel a producción, aunque el commit solo toque documentación. Cloud Run no se despliega solo: la API se publica a mano con `gcloud`.

| Fecha | Misión | Commit | Qué cambió |
| --- | --- | --- | --- |
| 23 nov | 01 · Despegue | [`a5167b1`](https://github.com/rodyxdev/cumpleycobra/commit/a5167b1) | Regla permanente de seguimiento (Instaward y Ship It) en `CLAUDE.md`, el seguimiento del SOW con evidencia y este registro |
| 23 nov | 01 · Despegue | [`631238e`](https://github.com/rodyxdev/cumpleycobra/commit/631238e) | «Iniciar sesión» en lugar de «Login with Pollar»; los textos de la interfaz ya no dicen «con Pollar» |
| 23 nov | 01 · Despegue | [`816c5f9`](https://github.com/rodyxdev/cumpleycobra/commit/816c5f9) | El programador ve «Esta tarea ya se pagó» (o «el depósito volvió al cliente») en lugar de «La tarea ya no está depositada» |
| 23 nov | 01 · Despegue | [`355ef0a`](https://github.com/rodyxdev/cumpleycobra/commit/355ef0a) | Vista de celular medida a 375 px: encabezado de 220 a 105 px, línea de estado de 387 a 258 px, botón de `/probar` en la primera pantalla y áreas de toque de 40 px o más |
| 23 nov | 01 · Despegue | [`b209867`](https://github.com/rodyxdev/cumpleycobra/commit/b209867) | README: qué lanzamos el 27 de noviembre (lo pide la misión) |
| 23 nov | 01 · Historia | — | Historia de Instagram con el avance: [`historia-dia-1.png`](historia-dia-1.png) |
| 24 nov | 02 · Toca Stellar | — | Pago real del contrato en producción tras verificar ejecutando: [tx `9038ddab…`](https://stellar.expert/explorer/testnet/tx/9038ddab89f2d8efd1d843998411b9bf6bb3be067fad7816baab4a7469f90c47) (`release`, 24 nov 07:17 UTC) |
| 24 nov | Suma más · Función nueva | [`b9d4ecc`](https://github.com/rodyxdev/cumpleycobra/commit/b9d4ecc) | Contrato v2 con pago por hitos: `deposit_milestones`, `release_milestone`, `client_release_milestone` y `timeout_refund_milestone`, con 14 tests nuevos (32 en total) |
| 24 nov | Suma más · Función nueva | este commit | v2 desplegado en testnet (`CAUBTDTW…R2K77K`) y un proyecto real de 3 hitos que usó las cuatro funciones: [depósito](https://stellar.expert/explorer/testnet/tx/937e9e5fa76c729c1ed8c5091365e94c55af6194e68900298be5785d28f50869), [pago del árbitro](https://stellar.expert/explorer/testnet/tx/7dba94e6ed54ac3506cf278d5ec7116ba6b53233e5dafee42196ee109a88d18b), [aprobación manual](https://stellar.expert/explorer/testnet/tx/f77f3d03909f5d7787314902d5a75daa191fa43330a0c79858b2601ef2a8acf6) y [reembolso por plazo](https://stellar.expert/explorer/testnet/tx/bf5c4aa051043d1e6a67841eb3b304342fde045b8b11eb7aaba969859bf94fd5) |
