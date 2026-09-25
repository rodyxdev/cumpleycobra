# Demo de Cumple&Cobra: checklist

Duración objetivo: menos de 5 minutos. Todo en la testnet de Stellar. Plazo de la tarea: 10 minutos.

## Antes de subir

- [ ] **Backend arriba** (desde la raíz del repositorio):

  ```bash
  backend/.venv/Scripts/python -m uvicorn backend.main:app --port 8000
  ```

  `curl -s localhost:8000/health` → `{"ok":true}`. `curl -s localhost:8000/fx/usd-mxn` → `"source":"Frankfurter"`. Si dice «Referencia fija de respaldo», la demo funciona igual, pero con la tasa de 17.50.
- [ ] **Frontend arriba:**

  ```bash
  cd frontend && npm run build && npx next start -p 3000
  ```

- [ ] **Dos ventanas de Chrome con perfiles separados**, cliente a la izquierda y programador a la derecha:

  ```bash
  "C:/Program Files/Google/Chrome/Application/chrome.exe" --user-data-dir=frontend/.perfiles/cliente http://localhost:3000/cliente
  "C:/Program Files/Google/Chrome/Application/chrome.exe" --user-data-dir=frontend/.perfiles/programador http://localhost:3000/cliente
  ```

- [ ] **Iniciar sesión en Pollar en los dos perfiles**, justo antes de subir: las sesiones caducan (se perdieron entre la fase 3 y la 4b). Login por correo (OTP): cliente `GBGK4N…D4FL` y programador `GA7MXQ…BEVJ`. Hay que ver la dirección en el botón de arriba a la derecha.
- [ ] **XLM de la gas wallet de Pollar** (paga los fee-bump; las wallets tienen 0 XLM). Debe tener más de 10 XLM (el 25 de septiembre: 9999.71):

  ```bash
  curl -s https://horizon-testnet.stellar.org/accounts/GDP2IYGXTDLRLMPSWKY5W5LDQADTW3EG6E6JCBAM4F6LHNKJB7GKB2MT | grep -A1 '"native"'
  ```

  Dashboard de Pollar: Treasury → Sponsorship activo. Domains: `http://localhost:3000`.
- [ ] **Saldos de USDC:**
  - cliente Pollar ≥ 1.2 USDC (la tarea de 20 MXN son ≈ 1.14 USDC; tras los ensayos del 25 de septiembre quedan 2.72);
  - programador Pollar con trustline activa;
  - `cyc-client` ≥ 1 USDC para el respaldo (hay 2).

  Si al cliente le falta: `bash scripts/fondear.sh GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL 2`.
- [ ] **Video de Drive público:** abrir el enlace en una ventana de incógnito sin sesión. Debe reproducirse. Enlace: `https://drive.google.com/file/d/1jg-nMazcC4Cln9eSSia5be0RsHSFizM9/view?usp=sharing`.
- [ ] **Video de respaldo de la demo completa**, grabado y a la mano (archivo local, no depende de la red). *Pendiente: todavía no está grabado.*
- [ ] **Cuota de Vertex:** no correr `probar_pedido.py`, `probar_revision.py` ni `estabilizar_motor.py` en los 10 minutos anteriores.
- [ ] **Sin tareas abiertas** de ensayos: la lista «Tareas creadas en este navegador» puede quedarse; el contrato no debe tener depósitos pendientes que distraigan.

## Pasos, en orden

**Ventana del cliente**, en `http://localhost:3000/cliente`:

1. En «1. Tu pedido original» debe estar este texto exacto (precargado):

   > Necesito una función en Python que reciba una lista de precios y un porcentaje de descuento, y me regrese los precios con el descuento aplicado, redondeados a 2 decimales. Sin librerías externas.

2. **«Pídele a la IA que mejore tu pedido».** Aparece «2. Revisa tu acuerdo verificable»: el pedido original a la izquierda y la versión mejorada editable a la derecha, con criterios y ejemplos.
3. **«Agregar criterio»**, escribir `Que sea rápido` y pulsar **«Revisar criterios»**. Ese criterio aparece marcado como vago, con una sugerencia medible («una sola pasada, sin recorridos anidados…»). Mensaje: la IA no deja pasar criterios que no se pueden verificar. **Quitar** ese criterio (no aplicar la sugerencia): así los criterios son los que se midieron.
4. En «3. Crea la tarea»: monto **20** MXN (se ve `≈ $20.00 MXN` y el USDC debajo), plazo **10** minutos. **«Crear tarea»**.
5. **«Copiar»** el enlace de invitación (la invitación sale enmascarada en pantalla).
6. **«Depositar … USDC con Pollar»**. Esperar «Depósito confirmado en la red» y el estado «Depositada».

**Ventana del programador:**

7. Pegar el enlace de invitación. Se ven los criterios acordados y el monto leído del contrato. **«Acepto los criterios»**.
8. **«Caso C: inyección en el docstring»** → **«Enviar»**. La terminal muestra el análisis con el contador real y termina en **RECHAZADO**, con la bandera de seguridad por el texto que intenta dar instrucciones al evaluador. Sin pago.
9. **«Caso A: implementación correcta»**. En el campo del video, pegar el enlace de Drive. **«Enviar»**. Resultado: **APROBADO** con ✓ en cada criterio y `Transacción <hash>`. Abrir el enlace al explorador: el pago es real y el evento `release` lleva `code_hash` y `verdict_hash`.

**Ventana del cliente:**

10. El estado pasa a «Pagada». En «Veredictos del motor» se ve el rechazo de C y la aprobación de A, cada criterio con su razón, y «Ver video demo». «Código entregado» → **«Ver código»**: el código llega al cliente solo después del pago.

### Tiempos medidos en el ensayo

Ensayo automatizado del 25 de septiembre de 2026 (`frontend/scripts/fase5-ensayo.mjs`). Los tiempos van desde el clic hasta que la pantalla muestra el resultado. No incluyen hablar ni teclear, así que en vivo hay que sumar la narración.

| Paso | Segundos |
| --- | --- |
| 2. Mejorar el pedido con IA | 5.4 |
| 3. Revisar criterios (con «Que sea rápido») | 4.7 |
| 4. Crear tarea | 0.6 |
| 6. Depositar con Pollar hasta «Depositada» | 7.0 |
| 7. Abrir invitación y aceptar | 1.6 |
| 8. Caso C → rechazado | 12.4 |
| 9. Caso A → aprobado y pagado | 11.3 |
| 10. Cliente: «Pagada» y código | 1.6 |
| **Total** | **45.9** |

Frase de cierre: «Si cumple lo acordado, cobras. Sin discusiones.»

## Si algo falla

| Pieza | Síntoma | Qué hacer |
| --- | --- | --- |
| **Pollar** (login o firma del depósito) | No abre el login, «Pollar no firmó», `txInsufficientBalance` | Crear y depositar la tarea desde la terminal. `scripts/deposit.sh` solo sirve si el cliente de la tarea es la identidad de la CLI: con una tarea creada con la wallet de Pollar, `/evaluate` responde `TASK_MISMATCH`. Por eso el respaldo es `backend/.venv/Scripts/python scripts/tarea_respaldo.py`, que crea la tarea con `cyc-client` y la deposita con el mismo `deposit` de `deposit.sh`. El programador sigue en el navegador con el enlace que imprime; los veredictos del cliente se ven con el `curl` que imprime. Si Pollar falla también para el programador (no puede aceptar sin wallet), pasar al video de respaldo. |
| **Gemini** (motor o pedido asistido) | «No se pudo preparar el pedido», `ENGINE_UNAVAILABLE`, 429 | Pedido: **«Usar la plantilla de la demo»** (mismos criterios, sin Gemini). Motor: enviar el **caso D** (en «Más casos»), que la capa determinista rechaza sin llamar a Gemini (lectura de `os.environ`). Para mostrar un pago aprobado, usar el **video de respaldo**. |
| **Red o testnet** | `CHAIN_UNAVAILABLE`, el depósito no confirma, el explorador no carga | **Video de respaldo.** No reintentar en vivo más de una vez. |
| Plazo | «Quedan menos de 120 s…» o `DEADLINE_TOO_CLOSE` | Crear una tarea nueva (el plazo es de 10 minutos). La anterior se reembolsa después con `timeout_refund`. |
| Saldo | «Tu saldo no alcanza para el depósito» | `bash scripts/fondear.sh GBGK4NLPUTTOTHR5SLSFPOWA74EYH727WGZQ5CKGVX2B4DGF3UVPD4FL 2` |

## Después

- Reembolsar cualquier tarea que haya quedado depositada, cuando venza su plazo (cualquiera puede dispararlo y el dinero solo vuelve al cliente):

  ```bash
  stellar contract invoke --id CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ --source cyc-third --network testnet -- timeout_refund --task_id '"TASK_ID"'
  ```
