# cumpleycobra — contrato Soroban

Contrato de Cumple&Cobra: el cliente deposita USDC amarrado a una tarea y al hash de los criterios acordados; el árbitro (backend) libera el pago al programador tras el veredicto del Motor de Análisis Estático de Código basado en LLM. Base: `contracts/escrow` de [CriptoUNAM-Team/Stellar-Guide](https://github.com/CriptoUNAM-Team/Stellar-Guide), extendido.

## Despliegue en testnet

| Dato | Valor |
| --- | --- |
| Contract ID | `CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ` |
| WASM hash | `b5391058c9f211b1fee80a06d50a168c6c66aa25e934bac4b06ad82546dc2a14` |
| Árbitro (`cyc-arbiter`) | `GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY` |
| Token: SAC de USDC testnet | `CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA` |
| Emisor USDC (Circle testnet) | `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` |
| Red | Testnet (`Test SDF Network ; September 2015`) |
| Despliegue anterior (sin `DeadlinePassed`, ya no se usa) | `CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND` |

Explorador: https://stellar.expert/explorer/testnet/contract/CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ

## Funciones

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `initialize(arbiter, token)` | El árbitro | Una sola vez (`AlreadyInitialized`) |
| `deposit(client, task_id, amount, deadline_secs, rules_hash)` | Cliente | `task_id` nuevo, `amount > 0`, `deadline_secs > 0`, plazo con `checked_add` |
| `release(task_id, freelancer, code_hash, verdict_hash)` | Árbitro | Solo desde `Funded` y con timestamp < plazo (`DeadlinePassed`); evento con los hashes |
| `client_release(task_id, freelancer)` | Cliente de la tarea | Solo desde `Funded`; también después del plazo |
| `timeout_refund(task_id)` | Nadie (sin auth) | Solo desde `Funded` y timestamp ≥ plazo; paga al cliente |
| `get_task(task_id)` | Lectura | `Task { task_id, client, freelancer, amount, deadline, rules_hash, status }` |
| `get_config()` | Lectura | `{ arbiter, token }` |

Errores (`Error(Contract, #N)`): 1 `NotInitialized`, 2 `AlreadyInitialized`, 3 `InvalidAmount`, 4 `AlreadyExists`, 5 `NotFound`, 6 `NotFunded`, 7 `DeadlineNotReached`, 8 `InvalidDeadline`, 9 `DeadlinePassed`.

Regla del plazo: el árbitro solo puede hacer `release` antes del plazo. Tras el plazo, la única salida es `timeout_refund` (o `client_release` si el cliente decide pagar), así que no hay carrera entre un `release` tardío y el reembolso.

Eventos (`#[contractevent]`): el primer tópico es la acción (`initialize`, `deposit`, `release`, `client_release`, `timeout_refund`) y el segundo el `task_id`.

TTL: cada escritura extiende la entrada persistente de la tarea y la instancia (configuración) a 30 días si les quedan menos de 7.

## Hashes

En el contrato los hashes (`rules_hash`, `code_hash`, `verdict_hash`) son `BytesN<32>` con los 32 bytes crudos del SHA-256; en la CLI y en la API van en hexadecimal (64 caracteres). La definición de cada hash está en el `CLAUDE.md` de la raíz (sección "Hashes y JSON canónico").

## Comandos usados (Stellar CLI 28.0.0)

> Se usó **Stellar CLI 28.0.0**, la versión instalada; la guía (`docs/comandos-basicos.md`) está escrita para la CLI 25. Los comandos de la guía funcionaron sin cambios. El contrato sigue usando soroban-sdk 25.

Tests y compilación, desde la raíz del repositorio:

```bash
cargo test -p cumpleycobra
rustup target add wasm32v1-none
stellar contract build
# WASM en target/wasm32v1-none/release/cumpleycobra.wasm
```

Identidades de testnet (las llaves quedan en `~/.config/stellar/identity`, fuera del repo):

```bash
stellar keys generate --fund cyc-arbiter --network testnet
stellar keys generate --fund cyc-client --network testnet
stellar keys generate --fund cyc-freelancer --network testnet
stellar keys generate --fund cyc-third --network testnet

# ID del SAC de USDC a partir del emisor de Circle
stellar contract id asset --asset USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5 --network testnet

# Trustline de USDC (cliente, programador y tercero)
stellar tx new change-trust --source cyc-client \
  --line USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5 --network testnet
```

USDC de testnet para `cyc-client`: faucet de Circle (https://faucet.circle.com, red Stellar Testnet).

Despliegue e inicialización:

```bash
stellar contract deploy --wasm target/wasm32v1-none/release/cumpleycobra.wasm \
  --source cyc-arbiter --network testnet --alias cumpleycobra

ID=CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA

stellar contract invoke --id $ID --source cyc-arbiter --network testnet -- \
  initialize --arbiter cyc-arbiter --token $USDC

stellar contract invoke --id $ID --source cyc-arbiter --network testnet --send=no -- get_config
```

Invocaciones (1 USDC = `10000000` unidades; los `String` van con comillas internas):

```bash
# Depósito del cliente (plazo de 600 s = 10 min, el de la demo)
stellar contract invoke --id $ID --source cyc-client --network testnet -- \
  deposit --client cyc-client --task_id '"tarea-1"' --amount 10000000 \
  --deadline_secs 600 --rules_hash <64 hex>

# Release del árbitro (solo antes del plazo; después falla con #9)
stellar contract invoke --id $ID --source cyc-arbiter --network testnet -- \
  release --task_id '"tarea-1"' --freelancer cyc-freelancer \
  --code_hash <64 hex> --verdict_hash <64 hex>

# Aprobación manual del cliente
stellar contract invoke --id $ID --source cyc-client --network testnet -- \
  client_release --task_id '"tarea-1"' --freelancer cyc-freelancer

# Reembolso por plazo vencido (lo puede enviar cualquiera)
stellar contract invoke --id $ID --source cyc-third --network testnet -- \
  timeout_refund --task_id '"tarea-1"'

# Lectura
stellar contract invoke --id $ID --source cyc-arbiter --network testnet --send=no -- \
  get_task --task_id '"tarea-1"'
```

La prueba completa y reproducible está en [`scripts/fase0-testnet.sh`](../../scripts/fase0-testnet.sh) (mueve 3 USDC de `cyc-client`: 1 lo cobra el programador y 2 vuelven al cliente; incluye el caso `release` tras el plazo → `#9` → `timeout_refund`):

```bash
bash scripts/fase0-testnet.sh
```

## v2: pago por hitos (24 de noviembre de 2026)

Mismo código y mismas funciones de v1, más el pago por hitos (diseño en [`docs/hitos/diseno.md`](../../docs/hitos/diseno.md)). **El contrato v1 desplegado no se modifica:** v2 es otra instancia, con el mismo árbitro y el mismo USDC de testnet.

| | |
| --- | --- |
| ID del contrato v2 (testnet) | `CAUBTDTWJKWKXH25LHXPES3ADTDRMBHYK4VOSWEWIBIYNLUINDR2K77K` |
| Despliegue | tx [`70218cec…`](https://stellar.expert/explorer/testnet/tx/70218cec8726b4c70d933feb53eb970bd07c61bb12ee0a6656433377bccb9037) (`--alias cumpleycobra-v2`) |
| `initialize` | tx [`d85744ec…`](https://stellar.expert/explorer/testnet/tx/d85744ec411155c4637be8d707a469c87546391aa32b48bc782f1bb7a97d961a), árbitro `GAGGEH…VOKZGY`, token `CBIELTK6…CAMA` |
| Tests | `cargo test -p cumpleycobra`: 32 en verde (18 de v1 sin cambios y 14 de hitos en `src/test_hitos.rs`) |

**Funciones nuevas:**

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `deposit_milestones(client, task_id, amounts, deadlines_secs, rules_hashes)` | Cliente | 2 a 10 hitos; listas del mismo largo; montos > 0; plazos de 1 s a 28 días que no bajan; deposita el total de una vez; el `task_id` no puede existir como tarea ni como proyecto |
| `release_milestone(task_id, index, freelancer, code_hash, verdict_hash)` | Árbitro | Solo un hito en `Funded` y antes de su plazo; el primer pago fija al programador |
| `client_release_milestone(task_id, index, freelancer)` | Cliente | Aprobación manual de un hito, también después de su plazo |
| `timeout_refund_milestone(task_id, index)` | Cualquiera | Solo un hito en `Funded` y vencido; el dinero vuelve al cliente |
| `get_project(task_id)` | Lectura | Cliente, programador y los hitos con monto, plazo, `rules_hash` y estado |

**Errores nuevos:** 10 `InvalidMilestones`, 11 `MilestoneNotFound`, 12 `WrongFreelancer`. Los del 1 al 9 no cambian.

**Proyecto real de 3 hitos en testnet** con [`scripts/hitos_testnet.sh`](../../scripts/hitos_testnet.sh), proyecto `hitos-1795584057`:

| Paso | Quién | tx |
| --- | --- | --- |
| `deposit_milestones`: 0.3 + 0.3 + 0.2 USDC | `cyc-client` | [`937e9e5f…`](https://stellar.expert/explorer/testnet/tx/937e9e5fa76c729c1ed8c5091365e94c55af6194e68900298be5785d28f50869) |
| `release_milestone`: hito 0 al programador | `cyc-arbiter` | [`7dba94e6…`](https://stellar.expert/explorer/testnet/tx/7dba94e6ed54ac3506cf278d5ec7116ba6b53233e5dafee42196ee109a88d18b) |
| `client_release_milestone`: hito 1 | `cyc-client` | [`f77f3d03…`](https://stellar.expert/explorer/testnet/tx/f77f3d03909f5d7787314902d5a75daa191fa43330a0c79858b2601ef2a8acf6) |
| `timeout_refund_milestone`: hito 2 vencido | `cyc-third` | [`bf5c4aa0…`](https://stellar.expert/explorer/testnet/tx/bf5c4aa051043d1e6a67841eb3b304342fde045b8b11eb7aaba969859bf94fd5) |

`get_project` al final: hitos `Released`, `Released` y `Refunded`, y el programador `GDOEME…DPHPNK` fijo. Los hashes de esta corrida son SHA-256 de textos de ejemplo: el backend todavía no verifica hitos (etapa 2 del diseño).

```bash
bash scripts/hitos_testnet.sh
```

## v3: agregar y aumentar hitos (25 de noviembre de 2026)

Mismo código y mismas funciones de v1 y v2 sin cambios, más dos funciones para ampliar un proyecto por hitos ya depositado (diseño en [`docs/hitos/diseno.md`](../../docs/hitos/diseno.md)). **Los contratos v1 y v2 desplegados no se modifican:** v3 se despliega como otra instancia aparte.

| | |
| --- | --- |
| ID del contrato v3 (testnet) | pendiente de despliegue |
| WASM hash (`stellar contract build`) | `c623639b5c80662d21e76556edd81820a20fed103c2e095317947e12dea8db70` (16 663 bytes optimizado) |
| Tests | `cargo test -p cumpleycobra`: 38 en verde (18 de v1 sin cambios, 14 de v2 y 6 de v3 en `src/test_hitos.rs`) |

**Funciones nuevas:**

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `add_milestone(task_id, amount, deadline_secs, rules_hash)` | Cliente del proyecto | Proyecto existente (`NotFound`), total ≤ 10 hitos (`InvalidMilestones`), `amount > 0` (`InvalidAmount`), plazo entre 1 s y 28 días con `checked_add` (`InvalidDeadline`), vencimiento absoluto ≥ plazo del último hito (`InvalidMilestones`). Guarda el hito en `Funded` (checks-effects-interactions + TTL), transfiere `amount` al contrato y publica `add_milestone` |
| `top_up_milestone(task_id, index, amount)` | Cliente del proyecto | Hito existente (`MilestoneNotFound`), en `Funded` (`NotFunded`), antes de su plazo (`DeadlinePassed`), `amount > 0` y `checked_add` sobre el monto (`InvalidAmount`). Guarda el nuevo monto (checks-effects-interactions + TTL), transfiere `amount` al contrato y publica `top_up_milestone` |

**Errores:** los códigos del 1 al 12 no cambian ni se agrega ninguno nuevo.

**Script de prueba en testnet** (cuando v3 esté desplegado): [`scripts/hitos_v3_testnet.sh`](../../scripts/hitos_v3_testnet.sh) deposita 2 hitos (`0.2 + 0.2` USDC, 120 s), agrega un 3.º (`0.1` USDC, 120 s), aumenta el hito 0 (`+0.1` USDC), libera los 3 hitos con el árbitro y consulta `get_project`:

```bash
bash scripts/hitos_v3_testnet.sh <ID_DEL_CONTRATO_V3>
```
