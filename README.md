# Cumple&Cobra

**Si cumple lo acordado, cobras. Sin discusiones.**

Cumple&Cobra es el acuerdo verificable para trabajo de código. El cliente fija criterios medibles y deposita USDC en un contrato Soroban. El programador acepta esos criterios y entrega un script de Python. El Motor de Análisis Estático de Código basado en LLM lo evalúa contra lo acordado; si cumple, el backend (árbitro) firma `release` y el programador cobra en segundos. El código no llega al cliente hasta que el programador cobra.

MVP para GOYA HACK (reto Stellar BAF). Todo corre en la testnet de Stellar.

## Cómo funciona

1. **Acuerdo:** el cliente crea la tarea con criterios verificables y comparte un enlace de invitación con su programador.
2. **Depósito:** el cliente deposita el monto en el contrato. El `rules_hash` (SHA-256 de los criterios) queda guardado on-chain.
3. **Aceptación:** el programador acepta los criterios; la tarea queda amarrada a su dirección.
4. **Veredicto:** el motor revisa el código en cuatro capas:
   - higiene;
   - revisión determinista con `ast`;
   - Gemini con salida estructurada;
   - regla final del backend.
5. **Pago:** si cumple, el contrato paga al programador. Si no, el cliente puede aprobar manualmente, y si vence el plazo cualquiera puede disparar el reembolso al cliente.

## Estructura

```
contracts/cumpleycobra/   # contrato Soroban (Rust) y sus tests
backend/                  # FastAPI: motor de análisis, tokens, release firmado por el árbitro
frontend/                 # Next.js + Tailwind + shadcn/ui
scripts/                  # pruebas reproducibles y utilidades de testnet
docs/fases/               # un reporte por fase, con comandos, salidas y hashes reales
```

Contrato en testnet: `CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ` (detalles en [`contracts/cumpleycobra/README.md`](contracts/cumpleycobra/README.md)).

## Cómo correrlo

```bash
# Contrato
cargo test -p cumpleycobra
stellar contract build

# Backend (copia .env.example a backend/.env y llénalo)
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
backend/.venv/Scripts/python -m pytest backend/tests
backend/.venv/Scripts/python -m uvicorn backend.main:app --port 8000

# Frontend (NEXT_PUBLIC_* en frontend/.env.local)
cd frontend && npm install && npm run build && npx next start -p 3000
```

## Wallet: Pollar (y respaldos)

La app usa [Pollar](https://pollar.xyz) para iniciar sesión, obtener la wallet, activar USDC y firmar `deposit` y `client_release`. Las transacciones se arman en el navegador con `@stellar/stellar-sdk` y se preparan contra el RPC. Pollar las firma en su servidor y las envuelve en un fee-bump pagado por la app, así que las wallets no necesitan XLM. La app las envía al RPC y consulta hasta `SUCCESS`.

Configuración del dashboard de Pollar (https://dashboard.pollar.xyz) para desarrollo local:

| Sección | Qué configurar |
| --- | --- |
| Build → API Keys | Clave publicable de testnet (`pub_testnet_…`) en `frontend/.env.local` como `NEXT_PUBLIC_POLLAR_API_KEY` |
| Build → Domains | `http://localhost:3000` (sin él, la API responde `403 ORIGIN_NOT_ALLOWED`) |
| Autenticación | Correo (OTP). Google necesita además URIs de redirección (sin ellas: `APPLICATION_HAS_NO_REDIRECT_URIS`) |
| Treasury → Tokens & Trustlines | `USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` |
| Treasury → Auth Policy | El contrato `CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ` |
| Treasury → Sponsorship | Activo para contratos y transferencias (sin él, la red responde `txInsufficientBalance`) |

Si la firma con Pollar falla, hay dos respaldos:

- **Plan B:** `NEXT_PUBLIC_WALLET=freighter`. La extensión Freighter firma `deposit` y `client_release`, y Pollar se queda para iniciar sesión, la wallet y la trustline.
- **Plan C:** `bash scripts/deposit.sh TASK_ID MONTO PLAZO_S RULES_HASH` deposita con la Stellar CLI.

Para la demo, `bash scripts/fondear.sh DIRECCION_G MONTO_USDC` manda USDC de testnet desde `cyc-client` a una wallet que ya activó USDC.

## Hashes verificables

Todos los hashes usan SHA-256 sobre JSON canónico:

- claves ordenadas y separadores `,` y `:` sin espacios;
- UTF-8 sin escapar;
- cadenas en NFC;
- sin `float`: los montos van en enteros, 1 USDC = 10 000 000 unidades.

La implementación está en [`backend/hashing.py`](backend/hashing.py).

| Hash | Se calcula sobre |
| --- | --- |
| `rules_hash` | `{"version": 1, "description", "criteria", "language", "allowed_deps" (ordenada), "examples"}` |
| `code_hash` | los bytes UTF-8 del código tal como se entregó |
| `verdict_hash` | `{"version": 1, "task_id", "code_hash", "approved", "reason", "stage", "comparison", "security_flags", "video_url"}` |

`rules_hash` queda en el depósito. `code_hash` y `verdict_hash` quedan en el evento `release` del contrato, así que cualquiera puede recalcularlos y comparar.

## Créditos

Desarrollado por Rodrigo Martínez Reyes. Construido con asistencia de IA: Claude Code (Anthropic) como agente de programación, y Claude en claude.ai para planeación y revisión de cada fase.
