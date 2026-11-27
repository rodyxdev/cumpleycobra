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

Mismo código y mismas funciones de v1 y v2 sin cambios, más dos funciones para ampliar un proyecto por hitos ya depositado (diseño en [`docs/hitos/diseno.md`](../../docs/hitos/diseno.md)). **Los contratos v1 y v2 desplegados no se modifican:** v3 es otra instancia, con el mismo árbitro y el mismo USDC de testnet.

| | |
| --- | --- |
| ID del contrato v3 (testnet) | `CCBZZMNYLDIDL55G7LFGVPRA2QPVTPOGYKWDNO3GKQ2CHRIR5O5JFJTC` |
| WASM hash (`stellar contract build`) | `c623639b5c80662d21e76556edd81820a20fed103c2e095317947e12dea8db70` (16 663 bytes optimizado; subida tx [`8bc08783…`](https://stellar.expert/explorer/testnet/tx/8bc08783bd191465f683bdfba7f4d164a2fb1688b93f9d7f87bc196ac192ea15)) |
| Despliegue | tx [`df4c596d…`](https://stellar.expert/explorer/testnet/tx/df4c596db8c558d1997d24e12ea69c94cb8fccf1d0e81d6955d1e8396414da23) (`--alias cumpleycobra-v3`) |
| `initialize` | tx [`37ac8df4…`](https://stellar.expert/explorer/testnet/tx/37ac8df43e762140894e873834a65e74b09183619f4af8b0e90389d550984f4a), árbitro `GAGGEH…VOKZGY`, token `CBIELTK6…CAMA` |
| Tests | `cargo test -p cumpleycobra`: 38 en verde (18 de v1 sin cambios, 14 de v2 y 6 de v3 en `src/test_hitos.rs`) |

Explorador: https://stellar.expert/explorer/testnet/contract/CCBZZMNYLDIDL55G7LFGVPRA2QPVTPOGYKWDNO3GKQ2CHRIR5O5JFJTC

**Funciones nuevas:**

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `add_milestone(task_id, amount, deadline_secs, rules_hash)` | Cliente del proyecto | Proyecto existente (`NotFound`), total ≤ 10 hitos (`InvalidMilestones`), `amount > 0` (`InvalidAmount`), plazo entre 1 s y 28 días con `checked_add` (`InvalidDeadline`), vencimiento absoluto ≥ plazo del último hito (`InvalidMilestones`). Guarda el hito en `Funded` (checks-effects-interactions + TTL), transfiere `amount` al contrato y publica `add_milestone` |
| `top_up_milestone(task_id, index, amount)` | Cliente del proyecto | Hito existente (`MilestoneNotFound`), en `Funded` (`NotFunded`), antes de su plazo (`DeadlinePassed`), `amount > 0` y `checked_add` sobre el monto (`InvalidAmount`). Guarda el nuevo monto (checks-effects-interactions + TTL), transfiere `amount` al contrato y publica `top_up_milestone` |

**Errores:** los códigos del 1 al 12 no cambian ni se agrega ninguno nuevo.

**Proyecto real en testnet** con [`scripts/hitos_v3_testnet.sh`](../../scripts/hitos_v3_testnet.sh), proyecto `hitos-v3-1795672283`:

| Paso | Quién | tx |
| --- | --- | --- |
| `deposit_milestones`: 2 hitos de 0.2 + 0.2 USDC (120 s) | `cyc-client` | [`af63c030…`](https://stellar.expert/explorer/testnet/tx/af63c030efaed7222543f93cf105c6d93237c7c314f15b07ecde9b2bec0e9f89) |
| `add_milestone`: 3.º hito (índice 2) de 0.1 USDC (120 s) | `cyc-client` | [`99c24b57…`](https://stellar.expert/explorer/testnet/tx/99c24b57fd288231c31f8a728ccc1283386fa76b89e5aa67590defe55932c712) |
| `top_up_milestone`: hito 0 +0.1 USDC (pasa a 0.3 USDC) | `cyc-client` | [`34bcc592…`](https://stellar.expert/explorer/testnet/tx/34bcc592979a29854ce50028c2c79356fef9611a769a4461a7e9ab0c9b48b7af) |
| `release_milestone`: hito 0 (0.3 USDC) al programador | `cyc-arbiter` | [`4a89d7eb…`](https://stellar.expert/explorer/testnet/tx/4a89d7eb0a92f742d74eb8e479cb32794ad904e21d2f084bfcc7dfa8fc95abb5) |
| `release_milestone`: hito 1 (0.2 USDC) al programador | `cyc-arbiter` | [`9a6920d7…`](https://stellar.expert/explorer/testnet/tx/9a6920d7aed5a1712b61bc3544153428904080e35cd9e7258f023de97d67459e) |
| `release_milestone`: hito 2 (0.1 USDC) al programador | `cyc-arbiter` | [`32e54025…`](https://stellar.expert/explorer/testnet/tx/32e540258a27a4432b9421b57f8f4efec57eaa620f14d9cbd1d8ef6f17da5013) |

`get_project` al final: 3 hitos en `Released` (`3000000`, `2000000`, `1000000`), programador `GDOEME…DPHPNK` fijo y saldo del contrato en `0` USDC. Los hashes de esta corrida son SHA-256 de textos de ejemplo: el backend todavía no verifica hitos (etapa 2 del diseño).

```bash
bash scripts/hitos_v3_testnet.sh
```

## v4: acuerdos parciales, cancelaciones, lotes y operación del escrow (26 de noviembre de 2026)

Mismo código y mismas funciones de v1, v2 y v3 sin cambios, más 11 funciones nuevas en 6 lotes (acuerdos parciales con doble firma, cancelaciones antes del plazo, reembolso en lote, recorte/división/prórroga de hitos, bono manual, depósito por lote y rotación segura del árbitro). **Los contratos v1, v2 y v3 desplegados no se modifican:** v4 es otra instancia, con el mismo árbitro y el mismo USDC de testnet.

| | |
| --- | --- |
| ID del contrato v4 (testnet) | `CBZ6TBVTNYOWGEFCSUGPO4GRWRNW4YAY6SK222XECEVVIIXFLD6TFK2E` |
| WASM hash (`stellar contract build --optimize`) | `ceba9ed8ad12693e015dace7d5815dbf68ac7dc9473d5ff2f9618e799337b311` (27 411 bytes optimizado; subida tx [`7d2201de…`](https://stellar.expert/explorer/testnet/tx/7d2201de623221b1e7a45d9ccc733e8c957fa02c7acb4e2a1d6eb4dda4c8b90c)) |
| Despliegue | tx [`01c4d856…`](https://stellar.expert/explorer/testnet/tx/01c4d856c1b4b797cfe8ff2adc2978a29540f604d75971e79e17f4322f71dcd8) (`--alias cumpleycobra-v4`) |
| `initialize` | tx [`f7ad54e0…`](https://stellar.expert/explorer/testnet/tx/f7ad54e0734e999fb3f96adff9cfaa3e9eb567ba6ace40be893b4d1483210fca), árbitro `GAGGEH…VOKZGY`, token `CBIELTK6…CAMA` |
| Tests | `cargo test -p cumpleycobra`: 52 en verde (18 de v1, 14 de v2, 6 de v3 y 14 de v4 en `src/test_v4.rs`) |

Explorador: https://stellar.expert/explorer/testnet/contract/CBZ6TBVTNYOWGEFCSUGPO4GRWRNW4YAY6SK222XECEVVIIXFLD6TFK2E

**Funciones nuevas:**

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `mutual_split_task(task_id, freelancer, freelancer_amount)` | Cliente + Programador | Tarea en `Funded`; `0 < freelancer_amount < amount`; paga `freelancer_amount` al programador y devuelve la diferencia al cliente en una transacción atómica |
| `mutual_split_milestone(task_id, index, freelancer, freelancer_amount)` | Cliente + Programador | Hito en `Funded`; fija/valida programador (`WrongFreelancer`); `0 < freelancer_amount < amount`; reparto atómico en dos transferencias de USDC |
| `cancel_unassigned_task(task_id)` | Cliente + Árbitro | Tarea en `Funded` antes del plazo (`DeadlinePassed`); marca `Refunded` y devuelve el depósito íntegro al cliente |
| `cancel_unassigned_project(task_id)` | Cliente + Árbitro | Proyecto sin programador fijado (`AlreadyAssigned`); marca todos los hitos en `Funded` como `Refunded` y devuelve el total en una transferencia |
| `refund_all_expired_milestones(task_id)` | Cualquiera | Recorre los hitos en `Funded` cuyo plazo venció (`DeadlineNotReached` si ninguno venció, `NotFunded` si no hay `Funded`), los marca `Refunded` y devuelve la suma al cliente en una transferencia |
| `reduce_milestone(task_id, index, reduce_amount)` | Cliente + Programador (si fijado) o Cliente + Árbitro | Hito en `Funded` antes de su plazo; `0 < reduce_amount < amount`; reduce el hito y devuelve la diferencia al cliente |
| `client_release_with_bonus(task_id, freelancer, bonus)` | Cliente | Tarea en `Funded` (también tras plazo); `bonus > 0`; libera `task.amount` del contrato y transfiere `bonus` del cliente al programador atómicamente |
| `batch_deposit(client, task_ids, amounts, deadlines_secs, rules_hashes)` | Cliente | 2 a 10 tareas independientes en una sola llamada y una sola transferencia de USDC; valida unicidad contra almacenamiento y dentro del mismo lote |
| `split_milestone(task_id, index, first_amount, first_deadline_secs, first_rules_hash, second_rules_hash)` | Cliente (y Programador si ya está fijado) | Divide un hito `Funded` antes del plazo en dos hitos consecutivos conservando el total, el tope de 10 hitos y el orden de plazos |
| `extend_milestone_deadline(task_id, index, extra_secs)` | Cliente | Prorroga un hito `Funded` hacia adelante (`extra_secs > 0`), dentro de 28 días desde ahora y sin rebasar el hito siguiente |
| `rotate_arbiter(new_arbiter)` | Árbitro actual + Nuevo árbitro | Rotación atómica del árbitro con doble firma; rechaza rotar hacia la misma dirección (`SameArbiter`) y extiende TTL de instancia |

**Errores nuevos:** 13 `AlreadyAssigned`, 14 `SameArbiter`. Los códigos del 1 al 12 no cambian.

**Corrida real en testnet** con [`scripts/hitos_v4_testnet.sh`](../../scripts/hitos_v4_testnet.sh) (corrida `1795741507`, saldo final del contrato `0` USDC y `cyc-arbiter` restaurado):

| Función | Quién firmó | tx |
| --- | --- | --- |
| `batch_deposit` (3 tareas: 0.03 + 0.02 + 0.02 USDC) | `cyc-client` | [`70cbb7eb…`](https://stellar.expert/explorer/testnet/tx/70cbb7eb9fa9bf0d5956c94a6b870f69102466bded70f18f79626a0584cc5096) |
| `mutual_split_task` (0.01 programador + 0.02 cliente) | `cyc-client` + `cyc-freelancer` | [`30cd7690…`](https://stellar.expert/explorer/testnet/tx/30cd7690be98e572b4b389b2d76f0d2b9a6ce38fba0e41a76f3e6c983ab58b01) |
| `cancel_unassigned_task` (devuelve 0.02 al cliente) | `cyc-client` + `cyc-arbiter` | [`ee0b6408…`](https://stellar.expert/explorer/testnet/tx/ee0b6408da6dab1dcaf8b31f23bbbf0094fe439dc95a027ee0c6e98848073177) |
| `client_release_with_bonus` (0.02 + 0.005 bono) | `cyc-client` | [`5d41bfbb…`](https://stellar.expert/explorer/testnet/tx/5d41bfbbcd408481ce0522934857cc5d65084315bf47d8f617f15687076dffc0) |
| `cancel_unassigned_project` (devuelve 0.04 al cliente) | `cyc-client` + `cyc-arbiter` | [`0b91cfaa…`](https://stellar.expert/explorer/testnet/tx/0b91cfaa8332a834638c41b26d2e02fa70a7e34761f8a9b0da941a7ec95b8c98) |
| `reduce_milestone` (hito 0: 0.03 → 0.02, devuelve 0.01) | `cyc-client` + `cyc-arbiter` | [`70a045ea…`](https://stellar.expert/explorer/testnet/tx/70a045ea5a84effd0436bc5271e67b9aa75edfff5973287a0a98184f2a606870) |
| `split_milestone` (hito 1: 0.04 → 0.02 + 0.02) | `cyc-client` | [`1003972a…`](https://stellar.expert/explorer/testnet/tx/1003972ab0086e17ea4db24f280083693009b7c2948b9cbf310bfc80c895c085) |
| `extend_milestone_deadline` (hito 0: +10 s) | `cyc-client` | [`d78633a4…`](https://stellar.expert/explorer/testnet/tx/d78633a418c70c2c19a8ceb852065b9f728393144df4dd2760dc355be4cc42cf) |
| `mutual_split_milestone` (hito 0: 0.01 + 0.01) | `cyc-client` + `cyc-freelancer` | [`00e1b4b4…`](https://stellar.expert/explorer/testnet/tx/00e1b4b4cafb25807f5f87fb392a73c30cb09de7579ee09eaccc8c6702141f1e) |
| `rotate_arbiter` (`cyc-arbiter` → `cyc-third` y regreso) | `cyc-arbiter` + `cyc-third` | [`f63bb8a6…`](https://stellar.expert/explorer/testnet/tx/f63bb8a67b2b6a34a17ce5326bf5e17d8185a1e589d53a41405427a9edd2a5ca) / [`483255f5…`](https://stellar.expert/explorer/testnet/tx/483255f596c27328b57468d7606bf4472af572d879dffbd1dd5d86413ce8facb) |
| `refund_all_expired_milestones` (hitos 1 y 2: 0.04) | `cyc-third` (sin permisos) | [`f194133e…`](https://stellar.expert/explorer/testnet/tx/f194133eee9b88a67aa2ef20386876dae95a8bd26380d1bf856d52759ca104be) |

```bash
bash scripts/hitos_v4_testnet.sh
```

## v5: el contrato conoce al programador antes de pagar (26 de noviembre de 2026)

En v1 a v4, el contrato no sabe quién es el programador hasta el pago: un cliente podía usar `client_release` (o `mutual_split_task`, o `client_release_milestone` antes del primer pago) para pagarle a una dirección suya en lugar de al programador que aceptó. v5 cierra ese hueco: el árbitro registra al programador en cuanto acepta los criterios y, desde ahí, ningún pago puede ir a otra dirección. **Los contratos v1 a v4 desplegados no se modifican:** v5 es otra instancia, con el mismo árbitro y el mismo USDC de testnet.

| | |
| --- | --- |
| ID del contrato v5 (testnet) | `CDWVPFHQJGBHI7DJQDFGYAHWRQKNDHIESFKO3MSUD6NPS7AKDYKUZEXM` |
| WASM hash (`stellar contract build --optimize`) | `764204ff5c69b663759e0380c3d04836ecb529f8791e5c89ed9e9096f8e2982f` (31 376 bytes) |
| Despliegue | tx [`4a4e568f…`](https://stellar.expert/explorer/testnet/tx/4a4e568f6c54c042dc8dc6adc5cc926c2179d9b9f81ec8c4e52f860072532579) (`--alias cumpleycobra-v5`) |
| `initialize` | tx [`0f111a6d…`](https://stellar.expert/explorer/testnet/tx/0f111a6d0ba9535c53ba628b22ca7b47411b9414b5aefc96e94e048ba9ee5c2c), árbitro `GAGGEH…VOKZGY`, token `CBIELTK6…CAMA` |
| Tests | `cargo test -p cumpleycobra`: 68 en verde (16 de v5 en `src/test_v5.rs`), 0 advertencias |

Explorador: https://stellar.expert/explorer/testnet/contract/CDWVPFHQJGBHI7DJQDFGYAHWRQKNDHIESFKO3MSUD6NPS7AKDYKUZEXM

**Funciones nuevas:**

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `assign_freelancer(task_id, freelancer)` | Árbitro | Tarea en `Funded`; idempotente con la misma dirección, `AlreadyAssigned` con otra. No mueve dinero |
| `assign_project_freelancer(task_id, freelancer)` | Árbitro | Proyecto con al menos un hito en `Funded`; idempotente; `AlreadyAssigned` con otra dirección |
| `extend_deadline(task_id, extra_secs) -> u64` | Cliente | Tarea en `Funded`; `extra_secs > 0`; el nuevo plazo no puede quedar a más de 28 días del ledger actual (`InvalidDeadline`). Se permite tras vencer si nadie pidió el reembolso |
| `top_up_task(task_id, amount) -> i128` | Cliente | Tarea en `Funded` antes del plazo; `amount > 0`; transfiere el extra al contrato y devuelve el nuevo monto |
| `freelancer_refund(task_id)` | Programador registrado | Tarea en `Funded` con programador registrado (`WrongFreelancer` si no hay); devuelve el depósito íntegro al cliente |
| `get_tasks(task_ids) -> Vec<Option<Task>>` | Lectura | De 1 a 20 tareas (`TooManyItems`); `None` para los `task_id` que no existen |

**Cambio en funciones anteriores (solo con programador registrado):** `release`, `client_release`, `client_release_with_bonus` y `mutual_split_task` exigen que `freelancer` sea el registrado (`WrongFreelancer`), y `cancel_unassigned_task` falla con `AlreadyAssigned`. Sin registro, todo se comporta igual que en v4 (test `v5_sin_asignacion_todo_funciona_igual_que_v4`).

**Error nuevo:** 15 `TooManyItems`. Los códigos del 1 al 14 no cambian.

**Corrida real en testnet** con [`scripts/v5_testnet.sh`](../../scripts/v5_testnet.sh) (corrida `1795754103`, saldo final del contrato `0` USDC):

| Paso | Quién firmó | tx |
| --- | --- | --- |
| `deposit` de las tareas A (0.02) y B (0.01) | `cyc-client` | [`01ccb637…`](https://stellar.expert/explorer/testnet/tx/01ccb6374b50cdc4e7028000e62f409440d73f75a6bf42080cde9cfe51b51fcc) / [`54ccaa89…`](https://stellar.expert/explorer/testnet/tx/54ccaa89f136ee27c858645432b201c2f44e87da37ce4fbf6808a8c11fae6728) |
| `assign_freelancer` (A y B) | `cyc-arbiter` | [`875d297a…`](https://stellar.expert/explorer/testnet/tx/875d297a11d33c1dc83335594e172f51a40b8dc15e389d7dd8d84aa36bab38f9) / [`1571898a…`](https://stellar.expert/explorer/testnet/tx/1571898a4e6d43bad5d87275eac1476f0064898ad6db047a9bd23c71d2508489) |
| `extend_deadline` (A, +300 s) | `cyc-client` | [`0bbe7a38…`](https://stellar.expert/explorer/testnet/tx/0bbe7a387d043b9b633a9b7b90ac635690a82fd07b5dea880fb1e56675186eaf) |
| `top_up_task` (A, +0.01 → 0.03) | `cyc-client` | [`e54e32c8…`](https://stellar.expert/explorer/testnet/tx/e54e32c816c1780c95c42ecd3eb2816449be5d6c15c4ec3648a87ef917c54fa3) |
| `client_release` de A hacia el propio cliente | `cyc-client` | Rechazado en la simulación: `Error(Contract, #12)` (`WrongFreelancer`) |
| `client_release` de A al programador registrado (0.03) | `cyc-client` | [`eb230368…`](https://stellar.expert/explorer/testnet/tx/eb2303689454394ee9dd53cd4ed695d19ba6240e9b7ea6e4baf2b0744ffd5136) |
| `freelancer_refund` (B, devuelve 0.01 al cliente) | `cyc-freelancer` | [`4088bff5…`](https://stellar.expert/explorer/testnet/tx/4088bff57ddf33615c5417d774747c2d1d04634cc1d3a3ca2991afceec187763) |
| `deposit_milestones` del proyecto (0.01 + 0.01) | `cyc-client` | [`c2de96f2…`](https://stellar.expert/explorer/testnet/tx/c2de96f260760befac56193f52eb846f6a6cd4c83542465765f70cb135eeda16) |
| `assign_project_freelancer` | `cyc-arbiter` | [`7945c648…`](https://stellar.expert/explorer/testnet/tx/7945c6481de3e59e869d15f98b29c94e6774efcb604f0ea4cc016e551d41a198) |
| `client_release_milestone` (hitos 0 y 1) | `cyc-client` | [`aaa0d8f6…`](https://stellar.expert/explorer/testnet/tx/aaa0d8f62340bc4089467c26de9cec4e4d46a6143d1eee4cb0d4b8ae9ddb303a) / [`1016ca1b…`](https://stellar.expert/explorer/testnet/tx/1016ca1bfb718b139477d2ea1fe6e924edb973e14328805888fb15ee4de22a4f) |
| `get_tasks` (A `Released`, B `Refunded`, uno inexistente → `null`) | Lectura | — |

```bash
bash scripts/v5_testnet.sh
```

El backend todavía usa el contrato v1 para las tareas simples: firmar `assign_freelancer` en `/accept` es el siguiente paso para que el registro proteja a los programadores en producción.

## v6: acuerdos de dos partes, disputas, estadísticas y pausa (27 de noviembre de 2026)

14 funciones nuevas en 3 lotes. Regla de diseño: **todo cambio que afecta al cliente y al programador lo firman los dos**, y cuando entra una parte nueva (otro programador u otro cliente) firma también ella. **Los contratos v1 a v5 desplegados no se modifican:** v6 es otra instancia, con el mismo árbitro y el mismo USDC de testnet.

| | |
| --- | --- |
| ID del contrato v6 (testnet) | `CD5ZI4KIEUT4QI46SJHVRORDQXLTRBFGJTRJQ5SZI2WMJVYTBKN5TABU` |
| WASM hash (`stellar contract build --optimize`) | `bceff64ba99dd9fbaa5fca93d8e3292c0953df25064fb479c03ae104284ee21f` (39 056 bytes; subida tx [`8752c591…`](https://stellar.expert/explorer/testnet/tx/8752c591d430fd07c69aeb6e4224cabbd2e3e6c50928c2ba13c93b42c5959ea2)) |
| Despliegue | tx [`a2589fb6…`](https://stellar.expert/explorer/testnet/tx/a2589fb6731db86a033f694bccd12bfb751017b2642171b26ae205686e5b34fc) (`--alias cumpleycobra-v6`) |
| `initialize` | tx [`8dd3d71d…`](https://stellar.expert/explorer/testnet/tx/8dd3d71df35957ce4eb69ff76fe518af7dd24be50ed5bd72f3e4cbf4841b0b0a), árbitro `GAGGEH…VOKZGY`, token `CBIELTK6…CAMA` |
| Tests | `cargo test -p cumpleycobra`: 84 en verde (16 de v6 en `src/test_v6.rs`), 0 advertencias |

Explorador: https://stellar.expert/explorer/testnet/contract/CD5ZI4KIEUT4QI46SJHVRORDQXLTRBFGJTRJQ5SZI2WMJVYTBKN5TABU

**Funciones nuevas:**

| Función | Quién firma | Reglas |
| --- | --- | --- |
| `amend_rules(task_id, new_rules_hash)` | Cliente + programador | Tarea `Funded` con programador registrado; cambia el `rules_hash` (`NoChange` si es el mismo) |
| `release_partial(task_id, amount, code_hash, verdict_hash) -> i128` | Árbitro | Antes del plazo; `0 < amount < monto`; paga al programador registrado y el resto sigue en `Funded` |
| `mutual_cancel(task_id)` | Cliente + programador | Devuelve todo al cliente, antes o después del plazo |
| `reassign_freelancer(task_id, new_freelancer)` | Cliente + programador actual + programador nuevo | Cambia el programador registrado |
| `transfer_client(task_id, new_client)` | Cliente actual + cliente nuevo (+ programador, si hay uno registrado) | El reembolso y la aprobación manual pasan al cliente nuevo |
| `tip(task_id, amount)` | Cliente | Solo con la tarea `Released`; va directo al programador y deja un evento |
| `bump_ttl(task_id)` | Cualquiera | Extiende la vida de la tarea o proyecto y de la instancia; no mueve dinero |
| `get_stats() -> Stats` | Lectura | `deposited`, `paid_out` y `held`; toda entrada pasa por `collect` y toda salida por `pay` |
| `deposit_assigned(client, task_id, amount, deadline_secs, rules_hash, freelancer)` | Cliente + programador | `deposit` con el programador ya registrado |
| `open_dispute(task_id, by)` | `by` (cliente o programador registrado) | Antes del plazo; congela `timeout_refund` hasta 14 días después del plazo |
| `resolve_dispute(task_id, freelancer_amount)` | Árbitro | Reparte el depósito (cualquiera de los dos puede recibir 0), también tras el plazo |
| `get_dispute(task_id) -> Option<Address>` | Lectura | Quién abrió la disputa |
| `pause()` / `unpause()` | Árbitro | Detienen solo los depósitos y recargas (`Paused`); pagos y reembolsos nunca se detienen |

**Errores nuevos:** 16 `NoChange`, 17 `NotParty`, 18 `DisputeOpen`, 19 `NoDispute`, 20 `Paused`. Los códigos del 1 al 15 no cambian.

**Límite conocido:** si una tarea con disputa abierta se cierra por otra vía (aprobación manual, reparto, cancelación), `get_dispute` sigue devolviendo quién la abrió; la tarea ya no está en `Funded` y la disputa no tiene efecto.

**Corrida real en testnet** con [`scripts/v6_testnet.sh`](../../scripts/v6_testnet.sh) (corrida `1795755491`, saldo final del contrato `0` USDC y depósitos sin pausa):

| Función | Quién firmó | Qué pasó | tx |
| --- | --- | --- | --- |
| `deposit_assigned` | `cyc-client` + `cyc-freelancer` | Depósito de 0.03 USDC con el programador registrado desde el inicio | [`cb3856a6…`](https://stellar.expert/explorer/testnet/tx/cb3856a667163647deed6416fee098de5d3c40d83dc5969bce0ef77dcfcb8d1c) |
| `amend_rules` | `cyc-client` + `cyc-freelancer` | `rules_hash` nuevo, firmado por los dos | [`2216825d…`](https://stellar.expert/explorer/testnet/tx/2216825dd49c379c06d7f28794be83c5207719d71aa57b97e69aaa551a0c9f38) |
| `release_partial` | `cyc-arbiter` | Paga 0.01 al programador; quedan 0.02 en el contrato | [`4137e37f…`](https://stellar.expert/explorer/testnet/tx/4137e37f2ed806c866e4bc15e5815511be5bfbe02ef8199a8d1b28cc23e7f6b3) |
| `open_dispute` | `cyc-freelancer` | El programador abre la disputa | [`24982cef…`](https://stellar.expert/explorer/testnet/tx/24982cefb7cf6f528ac2b8758e6b15e4414cfb2862cee9ba886455bd16875f18) |
| `get_dispute` | Lectura (enviada como tx) | Devuelve la dirección del programador | [`5745d170…`](https://stellar.expert/explorer/testnet/tx/5745d1701113c82a9e3270a5dc1e89743b7b5c47b059c83859339525b13fed9a) |
| `resolve_dispute` | `cyc-arbiter` | 0.01 al programador y 0.01 de vuelta al cliente | [`db4e276f…`](https://stellar.expert/explorer/testnet/tx/db4e276f96131ecd388f38798d9934cfdda33292592b7f63c883890caea12c9f) |
| `tip` | `cyc-client` | Propina de 0.005 directo al programador, con evento de la tarea | [`fa92d72a…`](https://stellar.expert/explorer/testnet/tx/fa92d72a0076543deaf397a238d540ff5539f22052a020075c9c1a1d876f9f2e) |
| `reassign_freelancer` | `cyc-client` + `cyc-freelancer` + `cyc-third` | Otra tarea (0.02) pasa de `cyc-freelancer` a `cyc-third` | [`525eec18…`](https://stellar.expert/explorer/testnet/tx/525eec185d11e417dc09b2491af88e71683e302de16eded1be4aba167943f782) |
| `transfer_client` | `cyc-client` + cliente nuevo + `cyc-third` | La tarea cambia de cliente con la firma de los tres | [`c862b35a…`](https://stellar.expert/explorer/testnet/tx/c862b35af73b8e64ccb6b0eef657f2c50bdf88db011b4088768c5da10ed7ed53) |
| `mutual_cancel` | Cliente nuevo + `cyc-third` | Cancelan de común acuerdo y los 0.02 vuelven al cliente nuevo | [`f2559894…`](https://stellar.expert/explorer/testnet/tx/f2559894e9273aaf31af9b55933bf5f8ca2e6dd68ffc109c4fc9a98cb650f063) |
| `bump_ttl` | `cyc-third` (sin permisos) | Extiende la vida de la tarea en el ledger | [`cca0e9cb…`](https://stellar.expert/explorer/testnet/tx/cca0e9cb8b704a69901d45d3f9b0305e86c8b6b97ae089339d9f484295b3abe9) |
| `pause` | `cyc-arbiter` | Un depósito durante la pausa se rechazó con `Error(Contract, #20)` | [`d1c70399…`](https://stellar.expert/explorer/testnet/tx/d1c703990429434081379dc879a205454352911adcb0dc4e671c035db2c93357) |
| `unpause` | `cyc-arbiter` | Reanuda los depósitos | [`523bea2c…`](https://stellar.expert/explorer/testnet/tx/523bea2cd5cb89b1bc235176ecbfdb95fb0e5c030ba011d03250ebae7338deb5) |
| `get_stats` | Lectura (enviada como tx) | `deposited` 0.05, `paid_out` 0.05, `held` 0 (igual al saldo real del contrato) | [`8f92999d…`](https://stellar.expert/explorer/testnet/tx/8f92999d38f76f4736030de8d96479e1b7968ff151251a4fe2a0d880791afeb9) |

```bash
bash scripts/v6_testnet.sh
```

