# cumpleycobra — contrato Soroban

Contrato de Cumple&Cobra: el cliente deposita USDC amarrado a una tarea y al hash de los criterios acordados; el árbitro (backend) libera el pago al programador tras el veredicto del Motor de Análisis Estático de Código basado en LLM. Base: `contracts/escrow` de [CriptoUNAM-Team/Stellar-Guide](https://github.com/CriptoUNAM-Team/Stellar-Guide), extendido.

## Despliegue en testnet

| Dato | Valor |
| --- | --- |
| Contract ID | `CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND` |
| WASM hash | `f71f516bc6d634bcfc93891770ceee0f522e4ac355ee224d3c353499562a8fea` |
| Árbitro (`cyc-arbiter`) | `GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY` |
| Token: SAC de USDC testnet | `CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA` |
| Emisor USDC (Circle testnet) | `GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5` |
| Red | Testnet (`Test SDF Network ; September 2015`) |

Explorador: https://stellar.expert/explorer/testnet/contract/CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND

## Funciones

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `initialize(arbiter, token)` | El árbitro | Una sola vez (`AlreadyInitialized`) |
| `deposit(client, task_id, amount, deadline_secs, rules_hash)` | Cliente | `task_id` nuevo, `amount > 0`, `deadline_secs > 0`, plazo con `checked_add` |
| `release(task_id, freelancer, code_hash, verdict_hash)` | Árbitro | Solo desde `Funded`; evento con los hashes |
| `client_release(task_id, freelancer)` | Cliente de la tarea | Solo desde `Funded` |
| `timeout_refund(task_id)` | Nadie (sin auth) | Solo desde `Funded` y timestamp ≥ plazo; paga al cliente |
| `get_task(task_id)` | Lectura | `Task { task_id, client, freelancer, amount, deadline, rules_hash, status }` |
| `get_config()` | Lectura | `{ arbiter, token }` |

Errores (`Error(Contract, #N)`): 1 `NotInitialized`, 2 `AlreadyInitialized`, 3 `InvalidAmount`, 4 `AlreadyExists`, 5 `NotFound`, 6 `NotFunded`, 7 `DeadlineNotReached`, 8 `InvalidDeadline`.

Eventos (`#[contractevent]`): el primer tópico es la acción (`initialize`, `deposit`, `release`, `client_release`, `timeout_refund`) y el segundo el `task_id`.

TTL: cada escritura extiende la entrada persistente de la tarea y la instancia (configuración) a 30 días si les quedan menos de 7.

## Hashes

En el contrato los hashes (`rules_hash`, `code_hash`, `verdict_hash`) son `BytesN<32>` con los 32 bytes crudos del SHA-256; en la CLI y en la API van en hexadecimal (64 caracteres). La definición de cada hash está en el `CLAUDE.md` de la raíz (sección "Hashes y JSON canónico").

## Comandos usados (Stellar CLI 28.0.0)

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

ID=CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND
USDC=CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA

stellar contract invoke --id $ID --source cyc-arbiter --network testnet -- \
  initialize --arbiter cyc-arbiter --token $USDC

stellar contract invoke --id $ID --source cyc-arbiter --network testnet --send=no -- get_config
```

Invocaciones (1 USDC = `10000000` unidades; los `String` van con comillas internas):

```bash
# Depósito del cliente (plazo de 300 s)
stellar contract invoke --id $ID --source cyc-client --network testnet -- \
  deposit --client cyc-client --task_id '"tarea-1"' --amount 10000000 \
  --deadline_secs 300 --rules_hash <64 hex>

# Release del árbitro
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

La prueba completa y reproducible está en [`scripts/fase0-testnet.sh`](../../scripts/fase0-testnet.sh) (gasta 2 USDC de `cyc-client`: 1 lo cobra el programador y 1 vuelve al cliente):

```bash
bash scripts/fase0-testnet.sh
```
