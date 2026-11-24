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
| 23 nov | 01 · Despegue | este commit | README: qué lanzamos el 27 de noviembre (lo pide la misión) |
