# Cumbre del 23 de noviembre de 2026: demo en línea

La demo es la versión publicada: **https://cumpleycobra.vercel.app** (frontend en Vercel, API en Cloud Run, Postgres en Cloud SQL, testnet de Stellar). El recorrido es el mismo de [`demo.md`](demo.md) (checklist del hackathon, en local); aquí solo cambia lo que es distinto en línea.

**Congelado:** nada se despliega a producción (Vercel, Cloud Run, Cloud SQL) desde la tarde del 22 hasta que termine la cumbre. Tampoco se usa staging, que firma con la misma llave de árbitro.

## Comprobado el 22 de noviembre

| Pieza | Estado |
| --- | --- |
| Frontend `main` en Vercel | `00dbd3f` (fase 3 cerrada, verificador apagado). Librería de Stellar 17.4.0: la 17.1.0 dejó de leer testnet cuando subió al protocolo 30 |
| API de producción | `/health` 200. En frío tardó 15.6 s; caliente, 0.13 s. Modo `demo`, Postgres, 10 peticiones por minuto por IP y 500 al día |
| Tipo de cambio | Frankfurter en vivo (19.03 MXN por USD) |
| Gas wallet de Pollar | 9998 XLM |
| Saldos | Cliente `GBGK4N…D4FL`: 18.16 USDC. Programador `GA7MXQ…BEVJ`: 46.74 USDC. `cyc-client` (respaldo por terminal): 5 USDC |
| Video demo del programador en Drive | Público (200) |
| Sesión real de Pollar en producción | Lee el saldo y deja crear la tarea |

## Antes de subir (el día 23)

- [x] **API caliente:** mínimo de instancias en 1 desde el 22 de noviembre (revisión `cumpleycobra-api-00004-nhk`, la misma imagen `sha256:9386e40d…` que la `00003-cez`; `/health` en ≈0.15 s). El día 23, solo comprobar `/health` en menos de 1 s.
- [ ] **Dos ventanas de Chrome con perfiles separados**, cliente a la izquierda y programador a la derecha, las dos en `https://cumpleycobra.vercel.app/cliente`.
- [ ] **Iniciar sesión en Pollar en las dos**, justo antes de subir (las sesiones caducan). Ver la dirección en el botón de arriba a la derecha. Cerrar la ventanita de Pollar al terminar el login.
- [ ] **Wi-Fi del evento:** si muchas personas usan la demo desde la misma red, comparten el límite de 10 peticiones por minuto (es por IP). La demo del escenario hace 4 llamadas a la IA; no pedir al público que la use al mismo tiempo.
- [ ] **Video de respaldo** en un archivo local (no depende de la red). Ya hay una guía pantalla por pantalla: [`cumbre/recorrido-demo.mp4`](cumbre/recorrido-demo.mp4) (2:04, 18 pantallas de un recorrido real en producción el 22 de noviembre, tarea `JgIReynD_NgX1DMR`, pago `0b27a204…`), armada con capturas y subtítulos. Sirve de respaldo si falla todo; uno grabado en vivo se ve más natural.
- [x] **Láminas de «lo que sigue»:** capturas listas en `docs/cumbre/` (plan de chequeos, veredicto web pagado, galería y una captura original del verificador).

## Recorrido (unos 5 minutos)

Igual que los pasos 1 a 10 de [`demo.md`](demo.md), con la URL en línea:

1. Cliente: pedido precargado → **«Pídele a la IA que mejore tu pedido»**.
2. **«Agregar criterio»** «Que sea rápido» → **«Revisar criterios»** (sale marcado como vago) → quitarlo.
3. Monto **20** MXN, plazo **10** minutos → **«Crear tarea»** → **«Copiar»** la invitación.
4. **«Depositar … USDC con Pollar»** → «Depósito confirmado en la red».
5. Programador: pegar la invitación → **«Acepto los criterios»**.
6. **Caso C** → RECHAZADO con aviso de seguridad (inyección).
7. **Caso A** con el enlace de Drive → APROBADO y pagado → abrir la transacción en el explorador.
8. Cliente: «Pagada», veredictos de C y A, **«Ver código»**.

Frase de cierre: «Si cumple lo acordado, cobras. Sin discusiones.»

### Ensayos del 22 de noviembre en producción: 3 de 3 sin fallo

El cliente corrió en la demo en línea con la sesión de Pollar de `GA7MXQ…BEVJ`. El programador corrió contra la API de producción con la wallet de prueba `cyc-freelancer` (aceptar y enviar por la API; en el escenario es la segunda ventana). En los tres, «Que sea rápido» salió marcado como vago, C se rechazó con aviso de seguridad y A se aprobó y se pagó. Tiempos en segundos, del clic al resultado:

| Paso | 1 | 2 | 3 |
| --- | --- | --- | --- |
| Mejorar el pedido con IA | 3.0 | 4.0 | 2.4 |
| Revisar criterios | 2.3 | 3.0 | 3.0 |
| Crear la tarea | — | 1.0 | 1.0 |
| Depositar con Pollar hasta «Depósito confirmado» | 5.5 | 4.0 | 5.0 |
| Aceptar los criterios | 0.4 | 0.3 | 0.2 |
| Caso C → rechazado | 3.1 | 2.7 | 2.5 |
| Caso A → aprobado y pagado | 3.9 | 5.7 | 4.8 |

Tareas y transacciones (testnet):
1. `ynDU1GVhVC-ccFLk`: depósito `0636a8bd…`, pago `dacb9b05…`. En la vista del cliente: «Pagada», los dos veredictos, el video y «Ver código».
2. `QMCboGNznp0n49_G`: depósito `95dfa8ba…`, pago `fe5908ce…`.
3. `7IU46sQJ469img4l`: depósito `b6b0777b…`, pago `bbf8fa7a…`.

El ensayo con las dos ventanas y dos sesiones de Pollar, como en el escenario, lo hace Rodrigo, y de ahí sale el video de respaldo.

## Lo que sigue (láminas, no en vivo)

Ya funciona en staging, con pagos reales en testnet (fase 3, `docs/mejora/fase-3.md`):

- **El verificador ejecuta el código**, aislado con gVisor en una VM sin credenciales: tests ocultos que no ve el programador. Corpus de 60 entregas: 213 verificaciones, 0 falsas aprobaciones.
- **Sitios web:** un navegador real revisa la página a 1440 px y 390 px, toma capturas y el modelo juzga lo visual. 39 verificaciones, 0 falsas aprobaciones.
- La VM se enciende sola cuando hay trabajo y se apaga a los 15 minutos.

No se muestra en vivo: staging comparte la llave del árbitro con producción y la VM tarda 1 o 2 minutos en encender.

## Si algo falla

Las mismas salidas que en [`demo.md`](demo.md) («Si algo falla»), y además:

| Síntoma | Qué hacer |
| --- | --- |
| «No se pudo leer tu cuenta…» | Recargar. Si sigue, la red de testnet cambió otra vez: video de respaldo |
| La primera petición tarda 15 s | La API estaba fría: esperar una vez. Con el mínimo de instancias en 1 no debería pasar |
| «Demasiadas solicitudes» | Esperar el tiempo que indica (ventanas de 60 s) |

## Guion del video de respaldo (grabación de pantalla, unos 3 minutos)

Grabar las dos ventanas lado a lado, con el mismo recorrido de arriba, sin cortes:

1. (0:00) Cliente: el pedido en lenguaje natural → la IA lo convierte en criterios medibles; marcar «Que sea rápido» como vago.
2. (0:40) Crear la tarea con 20 MXN y depositar con Pollar: «Depósito confirmado».
3. (1:10) Programador: abrir la invitación y aceptar los criterios.
4. (1:30) Caso C: rechazo por inyección, con el aviso de seguridad.
5. (2:00) Caso A: aprobado, pago en segundos, transacción en el explorador.
6. (2:40) Cliente: veredictos criterio por criterio y código entregado tras el pago.

## Después de la cumbre

- [ ] Devolver el mínimo de instancias de la API a 0: `gcloud run services update cumpleycobra-api --region=us-central1 --min-instances=0`.
- [ ] Reembolsar con `timeout_refund` las tareas que hayan quedado depositadas (comando en `demo.md`).
- [ ] Empezar la fase 2 del plan de mejora (cuentas reales).
