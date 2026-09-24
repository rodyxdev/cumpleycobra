# Fase 0: contrato Soroban

Fecha: jueves 24 de septiembre de 2026.
Hito: `cargo test -p escrow` en verde; contrato extendido con los 8 tests obligatorios; deploy en testnet; `deposit`, `release` y `timeout_refund` funcionan desde la CLI. **Cumplido.**

## 1. Qué se hizo

Entorno: Rust 1.98.1 (`x86_64-pc-windows-gnu`), target `wasm32v1-none`, Stellar CLI 28.0.0, soroban-sdk 25.3.2.

1. Se clonó la guía (CriptoUNAM-Team/Stellar-Guide) y se corrió `cargo test -p escrow`: 3/3 en verde (salida en la sección 3.1).
2. Se creó el repositorio con el workspace de la guía (`Cargo.toml` con los mismos perfiles `release` y `release-with-logs`) y se copió `contracts/escrow` como `contracts/cumpleycobra` (paquete `cumpleycobra`).
3. Se aplicaron los 9 cambios sustanciales y se escribieron los 8 tests obligatorios, más 7 adicionales.
4. Se desplegó en testnet, se inicializó con el árbitro y el SAC de USDC y se probaron `deposit`, `release` y `timeout_refund` desde la CLI con USDC real de testnet (1 USDC por tarea).
5. Se documentaron comandos e ID del contrato.

Archivos creados:

| Archivo | Contenido |
| --- | --- |
| `Cargo.toml` | Workspace (copiado de la guía, sin el `exclude` de `mxn`) |
| `Cargo.lock` | Versiones exactas de dependencias (ver desviaciones) |
| `.gitignore` | `target/`, `*.wasm`, `test_snapshots/`, `.env`, `backend/state.json`, `.stellar/` |
| `.env.example` | Variables de entorno de CLAUDE.md, con `CONTRACT_ID` y `USDC_SAC_ID` ya llenos |
| `contracts/cumpleycobra/Cargo.toml`, `Makefile` | Paquete `cumpleycobra` (Makefile copiado de la guía) |
| `contracts/cumpleycobra/src/lib.rs` | Contrato con comentarios en español por bloque |
| `contracts/cumpleycobra/src/test.rs` | 15 tests |
| `contracts/cumpleycobra/README.md` | ID del contrato, funciones, errores y comandos usados |
| `scripts/fase0-testnet.sh` | Prueba reproducible en testnet (deposit, release, timeout_refund y casos que deben fallar) |
| `docs/fases/fase-0.md` | Este reporte |

### Cambios sustanciales respecto a `contracts/escrow`

| # | Cambio | Dónde en `lib.rs` |
| --- | --- | --- |
| 1 | El árbitro es el backend: `release` exige `arbiter.require_auth()` | `release` |
| 2 | `task_id: String` en lugar de `u64` autoincremental; `deposit` rechaza repetidos (`AlreadyExists`) | `DataKey::Task(String)`, `deposit` |
| 3 | El freelancer se define al liberar (`Task.freelancer: Option<Address>`, `None` hasta `release`/`client_release`) | `Task`, `release`, `client_release` |
| 4 | `rules_hash: BytesN<32>` guardado en el depósito | `Task`, `deposit` |
| 5 | `release` publica `ReleaseEvent` con `code_hash` y `verdict_hash` | `ReleaseEvent` |
| 6 | `client_release`: solo el cliente de la tarea (`task.client.require_auth()`) | `client_release` |
| 7 | `timeout_refund` sin auth, solo tras el plazo, paga siempre a `task.client` | `timeout_refund` |
| 8 | El estado cambia antes de transferir (en la base se transfería y luego se cerraba) | `save_task` antes de `pay` en las tres salidas |
| 9 | Eventos en cada paso (`#[contractevent]`) y TTL extendido en cada escritura, de la tarea y de la instancia | `save_task`, `extend_instance` |

Además: plazo = `ledger().timestamp().checked_add(deadline_secs)`, con `InvalidDeadline` si desborda. Errores exactamente los de CLAUDE.md: 1 `NotInitialized`, 2 `AlreadyInitialized`, 3 `InvalidAmount`, 4 `AlreadyExists`, 5 `NotFound`, 6 `NotFunded`, 7 `DeadlineNotReached`, 8 `InvalidDeadline`. Los eventos usan `#[contractevent]`; `env.events().publish(...)` está marcado `#[deprecated]` en soroban-sdk 25.3.2 y no se usa (compila sin advertencias).

### Tests

| Obligatorio (CLAUDE.md) | Test |
| --- | --- |
| Happy path con saldos finales (cliente, contrato, freelancer) | `test_flujo_feliz_saldos_finales` |
| Doble `release` falla y no mueve fondos | `test_doble_release_falla_sin_mover_fondos` |
| `release` de árbitro falso falla, **sin** `mock_all_auths` | `test_release_arbitro_falso_falla` (modo estricto; control positivo con el árbitro real) |
| `timeout_refund` antes del plazo falla (`env.ledger()`) | `test_timeout_refund_antes_del_plazo_falla` (al depositar y a plazo − 1 s) |
| `timeout_refund` de un tercero devuelve al cliente; saldo del tercero intacto | `test_timeout_refund_por_tercero_devuelve_al_cliente` (sin ninguna auth; `env.auths()` vacío) |
| `timeout_refund` tras `release` falla, y viceversa | `test_timeout_refund_y_release_son_excluyentes` |
| `deposit` con `task_id` repetido falla | `test_deposit_task_id_repetido_falla` (también tras cerrar la tarea) |
| `client_release` de alguien que no es el cliente falla | `test_client_release_no_cliente_falla` (tercero, freelancer y árbitro; control positivo con el cliente) |

Adicionales: `test_initialize_dos_veces_falla`, `test_sin_initialize_falla`, `test_deposit_monto_invalido`, `test_deposit_plazo_invalido` (desbordamiento de `checked_add`, plazo 0 y el límite exacto), `test_tarea_inexistente`, `test_evento_release_con_hashes`, `test_ttl_extendido_en_tarea_e_instancia`.

Los tests de permisos (árbitro falso, tercero, cliente falso) usan un modo estricto que nunca llama `mock_all_auths`: cada firma se simula con `mock_auths` para una cuenta y una llamada concretas (incluida la subinvocación `transfer` del token en `deposit`). Cada uno tiene un control positivo con la firma correcta, para que el rechazo no se deba a un mock mal armado.

## 2. Desviaciones de CLAUDE.md y por qué

1. **Stellar CLI 28.0.0 en lugar de 25.** Es la versión instalada en la máquina. Los comandos de `docs/comandos-basicos.md` de la guía funcionaron sin cambios. El contrato sí usa soroban-sdk 25 (25.3.2), como pide CLAUDE.md.
2. **`initialize` exige la firma del árbitro.** La base no pedía firma. Con `arbiter.require_auth()` nadie puede nombrar árbitro a una cuenta que no controla. La función sigue siendo `initialize` con `AlreadyInitialized`.
3. **Configuración en almacenamiento de instancia.** La base guardaba `Arbiter`/`Token` en persistente; CLAUDE.md pide extender el TTL de la instancia (configuración), así que la configuración vive ahí. Se quitó `NextId` (ya no hay ids autoincrementales).
4. **`deadline_secs = 0` se rechaza con `InvalidDeadline`.** No lo pide CLAUDE.md; un plazo de 0 permitiría reembolsar en el mismo ledger del depósito.
5. **Función de lectura extra `get_config()`.** Devuelve `{arbiter, token}`; sirve para verificar el despliegue (y al backend en sus guardias). No cambia estado.
6. **Eventos con tópicos explícitos** (`#[contractevent(topics = ["release"])]`, etc.): el primer tópico es el nombre de la función y el segundo el `task_id`, para filtrar en el explorador.
7. **`Cargo.lock` sí va al repositorio** (la guía lo ignora): fija las versiones exactas para que el WASM sea reproducible. `test_snapshots/` se ignora.
8. **`contracts/escrow` no se copió como crate aparte**: `cargo test -p escrow` se corrió en el clon de la guía; en este repo solo existe `cumpleycobra`.
9. **Árbitro falso en testnet:** la CLI no llega a enviar la transacción (`Missing signing key for account GAGG…`): la simulación exige la firma del árbitro y `cyc-third` no la tiene. Es la evidencia que da la CLI; el rechazo en el contrato de una firma incorrecta está probado en `test_release_arbitro_falso_falla`.

## 3. Comandos ejecutados y salida real

### 3.1 Guía: `cargo test -p escrow`

```
$ cd Stellar-Guide && cargo test -p escrow
   (…compilación de dependencias…)
   Compiling escrow v0.0.0 (…\Stellar-Guide\contracts\escrow)
    Finished `test` profile [unoptimized + debuginfo] target(s) in 1m 50s
     Running unittests src\lib.rs (target\debug\deps\escrow-02363c1dba55c2f4.exe)

running 3 tests
test test::test_refund_to_payer ... ok
test test::test_cannot_release_twice ... ok
test test::test_release_to_payee ... ok

test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.07s
```

### 3.2 `cargo test -p cumpleycobra` (salida completa)

```
$ cargo test -p cumpleycobra
    Finished `test` profile [unoptimized + debuginfo] target(s) in 0.29s
     Running unittests src\lib.rs (target\debug\deps\cumpleycobra-70157149090ae560.exe)

running 15 tests
test test::test_sin_initialize_falla ... ok
test test::test_initialize_dos_veces_falla ... ok
test test::test_tarea_inexistente ... ok
test test::test_deposit_monto_invalido ... ok
test test::test_timeout_refund_antes_del_plazo_falla ... ok
test test::test_ttl_extendido_en_tarea_e_instancia ... ok
test test::test_flujo_feliz_saldos_finales ... ok
test test::test_evento_release_con_hashes ... ok
test test::test_deposit_plazo_invalido ... ok
test test::test_timeout_refund_por_tercero_devuelve_al_cliente ... ok
test test::test_client_release_no_cliente_falla ... ok
test test::test_doble_release_falla_sin_mover_fondos ... ok
test test::test_deposit_task_id_repetido_falla ... ok
test test::test_release_arbitro_falso_falla ... ok
test test::test_timeout_refund_y_release_son_excluyentes ... ok

test result: ok. 15 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.15s
```

(La primera corrida, con compilación, terminó igual: 15 passed, sin advertencias.)

### 3.3 `stellar contract build`

```
$ rustup target add wasm32v1-none
$ stellar contract build
   Compiling cumpleycobra v0.1.0 (C:\Users\rodri\Desktop\cumpleycobra\contracts\cumpleycobra)
    Finished `release` profile [optimized] target(s) in 33.34s
ℹ️  Build Summary:
    Wasm File: target\wasm32v1-none\release\cumpleycobra.wasm (8519 bytes optimized (original size was 9852 bytes))
    Wasm Hash: f71f516bc6d634bcfc93891770ceee0f522e4ac355ee224d3c353499562a8fea
    Wasm Size: 8519 bytes optimized (original size was 9852 bytes)
    Exported Functions: 7 found
      • client_release
      • deposit
      • get_config
      • get_task
      • initialize
      • release
      • timeout_refund
✅ Build Complete
```

### 3.4 Cuentas de testnet

```
$ stellar keys generate --fund <alias> --network testnet   (x4)
cyc-arbiter    GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY
cyc-client     GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB
cyc-freelancer GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK
cyc-third      GCF4HYJD4L6O7AX3YSTKA2MJAC4G35T26F3HIE2LBCMKM64R3VNQNWJD

$ stellar contract id asset --asset USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5 --network testnet
CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA

$ stellar contract invoke --id CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA --send=no -- name
"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
```

Trustlines de USDC (`stellar tx new change-trust --line USDC:GBBD…FLA5`), las tres con `successful: true` en Horizon:

| Cuenta | Tx |
| --- | --- |
| cyc-client | `e7f552f4396bc63e3d51c1c6835b1c3fee681af6126ff3f7c37c511df4aff4d3` |
| cyc-freelancer | `1a9447fdc95e95d136d1dcffb9c34033b6d95df9b0fbf672f2086ce3ca2e9751` |
| cyc-third | `329d773201e8d877b6f98dae449639d94020fb8ac49244cedcf4e2b5e1f785d4` |

Rodrigo fondeó `cyc-client` con 20 USDC desde el faucet de Circle. Horizon confirmó `balance 20.0000000`, `asset_issuer GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5`, el mismo emisor del SAC con el que se inicializó el contrato (`get_config().token` = `CBIELTK6…DAMA` = `stellar contract id asset` de ese emisor).

### 3.5 Deploy e initialize

```
$ stellar contract deploy --wasm target/wasm32v1-none/release/cumpleycobra.wasm --source cyc-arbiter --network testnet --alias cumpleycobra
ℹ️  Uploading contract WASM…
ℹ️  Signing transaction: 443d75fa80ce425548223ec5f2ce3e12a1046b793be17d36bd1a239c9086d3eb
✅ Transaction submitted successfully!
ℹ️  Deploying contract using wasm hash f71f516bc6d634bcfc93891770ceee0f522e4ac355ee224d3c353499562a8fea
ℹ️  Signing transaction: 0c3d2e8db51e684d35c10251836458255d36f54b8d0f7756a84df0a7e3ec5ea0
✅ Transaction submitted successfully!
🔗 https://lab.stellar.org/r/testnet/contract/CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND
✅ Deployed!
CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND

$ stellar contract invoke --id CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND --source cyc-arbiter --network testnet -- initialize --arbiter cyc-arbiter --token CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
ℹ️  Signing transaction: aadabf706b95e2768e5a68e958d46c03527428f3aae3d5720c716fc1b259ae02
✅ Transaction submitted successfully!
📅 CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND - Success - Event: InitializeEvent (initialize), arbiter: "GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY", token: "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"
null

$ stellar contract invoke --id CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND --source cyc-arbiter --network testnet --send=no -- get_config
{"arbiter":"GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY","token":"CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"}
```

### 3.6 Resumen de testnet

**Contract ID:** `CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND`

| Paso | Hash de la transacción | Ledger | Firmó |
| --- | --- | --- | --- |
| Upload WASM | `443d75fa80ce425548223ec5f2ce3e12a1046b793be17d36bd1a239c9086d3eb` | | cyc-arbiter |
| Deploy | `0c3d2e8db51e684d35c10251836458255d36f54b8d0f7756a84df0a7e3ec5ea0` | | cyc-arbiter |
| `initialize` | `aadabf706b95e2768e5a68e958d46c03527428f3aae3d5720c716fc1b259ae02` | | cyc-arbiter |
| `deposit` (tarea A, 1 USDC) | `c86cc33e305f70677538960af12be20ed089d60c1d37b5821773d771d8a334ec` | 4847242 | cyc-client |
| `release` (tarea A) | `1cdf178c3a8cb0209b67cfeb9ec923ee5684ad305d63ec562c89e1af377029e1` | 4847243 | cyc-arbiter |
| `deposit` (tarea B, 1 USDC, plazo 30 s) | `f0f55ce6d6cf4780f7aa7fd29d81fb7d8088990cfb80fdd10329e1c512d7470c` | 4847245 | cyc-client |
| `timeout_refund` (tarea B) | `95573e46551e6240135d7e2c988263ae1933b43243432a2b0e5ca839f3d11914` | 4847255 | cyc-third (tercero) |

Las cuatro transacciones de `deposit`, `release` y `timeout_refund` aparecen en Horizon con `successful: true`. Casos que debían fallar, y fallaron:

- `release` con `--source cyc-third` (árbitro falso): la CLI no envía la transacción (`Missing signing key for account GAGG…`).
- Segundo `release` de la tarea A: `Error(Contract, #6)` = `NotFunded`.
- `timeout_refund` de la tarea B antes del plazo: `Error(Contract, #7)` = `DeadlineNotReached`.

Saldos USDC (unidades): cliente 200000000 → 190000000; contrato 0 → 0; freelancer 0 → 10000000; tercero 0 → 0. A `cyc-client` le quedan 19 USDC para las fases siguientes.

### 3.7 Salida completa de `bash scripts/fase0-testnet.sh`

```
== Contrato CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND | USDC CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA | monto 10000000
== Saldos iniciales
   cliente:    "200000000"
   contrato:   "0"
   freelancer: "0"
   tercero:    "0"

== Tarea A (fase0-a-1790259793): deposit
ℹ️  Simulating transaction…
ℹ️  Signing transaction: c86cc33e305f70677538960af12be20ed089d60c1d37b5821773d771d8a334ec
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/c86cc33e305f70677538960af12be20ed089d60c1d37b5821773d771d8a334ec
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"address":"CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND - Success - Event: DepositEvent (deposit), task_id: "fase0-a-1790259793", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790260097, rules_hash: "f8bdef47cbd7ae5079f5b0eaa325dce19f45ba73e489acba451d614abe817325"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790260097,"freelancer":null,"rules_hash":"f8bdef47cbd7ae5079f5b0eaa325dce19f45ba73e489acba451d614abe817325","status":"Funded","task_id":"fase0-a-1790259793"}

== Tarea A: release firmado por un árbitro falso (cyc-third)
❌ error: Missing signing key for account GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY
   -> falló como se esperaba

== Tarea A: release del árbitro
ℹ️  Simulating transaction…
ℹ️  Signing transaction: 1cdf178c3a8cb0209b67cfeb9ec923ee5684ad305d63ec562c89e1af377029e1
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/1cdf178c3a8cb0209b67cfeb9ec923ee5684ad305d63ec562c89e1af377029e1
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND"},{"address":"GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND - Success - Event: ReleaseEvent (release), task_id: "fase0-a-1790259793", freelancer: "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", amount: "10000000", code_hash: "8eeee3ba714ef1694ed6c1bf087bc5a076a4bbcc75622a6e393d50bfe81cea48", verdict_hash: "bc665178769965f96e7cfa9a0c66f2243e83d62db7be3b2c67fa8978aa4b5347"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790260097,"freelancer":"GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK","rules_hash":"f8bdef47cbd7ae5079f5b0eaa325dce19f45ba73e489acba451d614abe817325","status":"Released","task_id":"fase0-a-1790259793"}

== Tarea A: segundo release (debe fallar con NotFunded = #6)
❌ error: transaction simulation failed: HostError: Error(Contract, #6)
   0: [Diagnostic Event] contract:CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND, topics:[error, Error(Contract, #6)], data:"escalating Ok(ScErrorType::Contract) frame-exit to Err"
   -> falló como se esperaba

== Saldos tras la tarea A
   cliente:    "190000000"
   contrato:   "0"
   freelancer: "10000000"
   tercero:    "0"

== Tarea B (fase0-b-1790259793): deposit con plazo de 30 s
ℹ️  Simulating transaction…
ℹ️  Signing transaction: f0f55ce6d6cf4780f7aa7fd29d81fb7d8088990cfb80fdd10329e1c512d7470c
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/f0f55ce6d6cf4780f7aa7fd29d81fb7d8088990cfb80fdd10329e1c512d7470c
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"address":"CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND - Success - Event: DepositEvent (deposit), task_id: "fase0-b-1790259793", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790259842, rules_hash: "f8bdef47cbd7ae5079f5b0eaa325dce19f45ba73e489acba451d614abe817325"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790259842,"freelancer":null,"rules_hash":"f8bdef47cbd7ae5079f5b0eaa325dce19f45ba73e489acba451d614abe817325","status":"Funded","task_id":"fase0-b-1790259793"}

== Tarea B: timeout_refund antes del plazo (debe fallar con DeadlineNotReached = #7)
❌ error: transaction simulation failed: HostError: Error(Contract, #7)
   0: [Diagnostic Event] contract:CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND, topics:[error, Error(Contract, #7)], data:"escalating Ok(ScErrorType::Contract) frame-exit to Err"
   -> falló como se esperaba

== Esperando 45 s a que venza el plazo…

== Tarea B: timeout_refund disparado por un tercero (cyc-third)
ℹ️  Simulating transaction…
ℹ️  Signing transaction: 95573e46551e6240135d7e2c988263ae1933b43243432a2b0e5ca839f3d11914
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/95573e46551e6240135d7e2c988263ae1933b43243432a2b0e5ca839f3d11914
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND - Success - Event: TimeoutRefundEvent (timeout_refund), task_id: "fase0-b-1790259793", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790259842,"freelancer":null,"rules_hash":"f8bdef47cbd7ae5079f5b0eaa325dce19f45ba73e489acba451d614abe817325","status":"Refunded","task_id":"fase0-b-1790259793"}
   USDC del tercero antes: "0", después: "0"

== Saldos finales
   cliente:    "190000000"
   contrato:   "0"
   freelancer: "10000000"
   tercero:    "0"

== Resumen
rules_hash:   f8bdef47cbd7ae5079f5b0eaa325dce19f45ba73e489acba451d614abe817325
code_hash:    8eeee3ba714ef1694ed6c1bf087bc5a076a4bbcc75622a6e393d50bfe81cea48
verdict_hash: bc665178769965f96e7cfa9a0c66f2243e83d62db7be3b2c67fa8978aa4b5347
deposit A:      c86cc33e305f70677538960af12be20ed089d60c1d37b5821773d771d8a334ec
release A:      1cdf178c3a8cb0209b67cfeb9ec923ee5684ad305d63ec562c89e1af377029e1
deposit B:      f0f55ce6d6cf4780f7aa7fd29d81fb7d8088990cfb80fdd10329e1c512d7470c
timeout_refund: 95573e46551e6240135d7e2c988263ae1933b43243432a2b0e5ca839f3d11914
```

## 4. Pendientes y riesgos detectados

1. **`release` después del plazo.** El contrato permite `release` mientras la tarea siga en `Funded`, aunque el plazo ya haya vencido (CLAUDE.md solo pide "solo desde `Funded`"). Pasado el plazo, `release` y `timeout_refund` compiten y gana la primera transacción que entra al ledger. La UI ya bloquea envíos con menos de 60 s. En la fase 1 el backend no debe firmar `release` si el plazo on-chain ya venció. **Decisión para revisar:** ¿el contrato debería rechazar `release` después del plazo?
2. **Ventana entre deploy e `initialize`.** Son dos transacciones; entre ellas un tercero podría inicializar con un árbitro propio (con el cambio de la desviación 2, solo con un árbitro que él mismo firme). Mitigación: `get_config` verificado justo después (sección 3.5). Alternativa para producción: `__constructor`, que despliega e inicializa en una sola transacción.
3. **`client_release` y `release` pagan a la dirección que reciben.** Por diseño, el contrato confía en el árbitro y en el cliente. El backend debe pasar siempre la dirección amarrada en `/accept`, nunca una que llegue en el cuerpo de `/evaluate`.
4. **`task_id` sin límite de longitud en el contrato.** Lo genera el backend. Conviene un formato corto y fijo (por ejemplo, 16 a 24 caracteres URL-safe).
5. **TTL.** Las tareas y la instancia quedan con 30 días de vida tras cada escritura. Una tarea cerrada que se archive se puede restaurar; por eso `deposit` sigue viendo el `task_id` como existente y no se reutiliza.
6. **Llaves de testnet** en `C:\Users\rodri\.config\stellar\identity\` (fuera del repo). Para la fase 1: `ARBITER_SECRET_KEY` = `stellar keys secret cyc-arbiter`, solo en el `.env` del backend.
7. **Saldo USDC:** 19 USDC en `cyc-client`. `scripts/fase0-testnet.sh` gasta 1 USDC neto por corrida (el que cobra el freelancer).
