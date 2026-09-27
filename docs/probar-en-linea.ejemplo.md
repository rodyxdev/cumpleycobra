# Probar Cumple&Cobra en línea — instrucciones para jueces

Este documento es un ejemplo público **sin enlaces ni tokens de invitación**. Solicita al equipo una invitación privada a una tarea depositada en la testnet de Stellar. El primer juez que la acepta queda asignado a ella; si ya está tomada, pide otra. El equipo te indicará su monto y plazo.

## Recorrido

1. Abre la invitación privada que te compartió el equipo.
2. **Inicia sesión con Pollar** con tu correo desde el botón del encabezado. Recibirás un código para entrar con tu wallet.
3. **Activa USDC** si se solicita. Pollar patrocina la reserva; no necesitas XLM para este paso.
4. Lee los criterios del acuerdo verificable y pulsa **«Acepto los criterios»**.
5. Selecciona **«Caso C: inyección en el docstring»** y pulsa **Enviar**. El Motor de Análisis Estático de Código basado en LLM debe rechazar la manipulación y mostrar el aviso de seguridad.
6. Selecciona **«Caso A: implementación correcta»** y pulsa **Enviar**. Si cumple los criterios, el contrato libera el pago en testnet.
7. Pulsa **«Ver transacción»** para comprobar el pago y el evento `release` con los hashes del código y del veredicto.
8. Opcionalmente, consulta tu historial en **Programadores**. **«Verificar identidad»** permite publicar tu perfil con un reto SEP-10 firmado por tu wallet.

## Límites y esperas

- Máximo **3 envíos evaluados por tarea**. Los rechazos por límite de peticiones o cuota no consumen esos envíos.
- Los límites por conexión usan ventanas de **60 segundos** y también cuentan peticiones inválidas. Si recibes «Demasiadas solicitudes», espera el tiempo indicado y reintenta. Crear tareas, propuestas, retos y tokens, editar perfiles y calificar también tiene un límite por conexión (30 por minuto por defecto), sin cuota diaria.
- Hay **dos cuotas diarias independientes**, una para borradores/revisión de criterios y otra para evaluar código. Solo consumen cuota las llamadas reales a la IA, incluidos reintentos; las peticiones inválidas y las respuestas de caché no la consumen.
- Si se agota la cuota diaria de esa operación, vuelve al día siguiente **UTC**. Agotar el borrador no agota el motor, ni viceversa.
- Deben quedar al menos **120 segundos de plazo** para enviar código. Si el plazo ya no alcanza, solicita otra tarea.

Las tareas que no se usen pueden reembolsarse al cliente cuando venza su plazo. Este documento no concede acceso a ninguna tarea. El archivo generado con invitaciones, `docs/probar-en-linea.md`, es privado y está excluido de Git.
