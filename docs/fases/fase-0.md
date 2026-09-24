# Fase 0: contrato Soroban

Fecha: jueves 24 de septiembre de 2026.
Hito: `cargo test -p escrow` en verde; contrato extendido con los 8 tests obligatorios; deploy en testnet; `deposit`, `release` y `timeout_refund` funcionan desde la CLI. **Cumplido.**

La fase se cerró en dos rondas:

1. **Primera entrega:** contrato con 15 tests, desplegado en `CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND` (ya no se usa).
2. **Revisión:** Rodrigo la aprobó con cambios. Se agregó `DeadlinePassed` y hubo 3 tests nuevos, limpieza de vocabulario, CLAUDE.md actualizado, redeploy y un nuevo caso en el script. **El despliegue vigente es `CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ`.**

## 1. Qué se hizo

Entorno: Rust 1.98.1 (`x86_64-pc-windows-gnu`), target `wasm32v1-none`, Stellar CLI 28.0.0, soroban-sdk 25.3.2.

1. Se clonó la guía (CriptoUNAM-Team/Stellar-Guide) y se corrió `cargo test -p escrow`: 3/3 en verde (sección 3.1).
2. Se creó el repositorio con el workspace de la guía (`Cargo.toml` con los mismos perfiles `release` y `release-with-logs`) y se copió `contracts/escrow` como `contracts/cumpleycobra` (paquete `cumpleycobra`).
3. Se aplicaron los 9 cambios sustanciales, más la regla del plazo en `release` pedida en la revisión. Se escribieron los 8 tests obligatorios, los 3 de la revisión y 7 adicionales (18 en total).
4. Se desplegó en testnet, se inicializó con el árbitro y el SAC de USDC y se probaron `deposit`, `release` y `timeout_refund` desde la CLI con USDC real de testnet (1 USDC por tarea).
5. Se documentaron comandos e ID del contrato y se actualizó CLAUDE.md.

Archivos creados o modificados:

| Archivo | Contenido |
| --- | --- |
| `Cargo.toml` | Workspace (copiado de la guía, sin el `exclude` de `mxn`) |
| `Cargo.lock` | Versiones exactas de dependencias (ver desviaciones) |
| `.gitignore` | `target/`, `*.wasm`, `test_snapshots/`, `.env`, `backend/state.json`, `.stellar/` |
| `.env.example` | Variables de entorno de CLAUDE.md, con `CONTRACT_ID` y `USDC_SAC_ID` ya llenos |
| `CLAUDE.md` | Revisión: error `DeadlinePassed`, regla de `release`, margen de 120 s, plazo de demo de 10 min |
| `contracts/cumpleycobra/Cargo.toml`, `Makefile` | Paquete `cumpleycobra` (Makefile copiado de la guía) |
| `contracts/cumpleycobra/src/lib.rs` | Contrato con comentarios en español por bloque |
| `contracts/cumpleycobra/src/test.rs` | 18 tests |
| `contracts/cumpleycobra/README.md` | ID del contrato, funciones, errores, nota de CLI 28 y comandos usados |
| `scripts/fase0-testnet.sh` | Prueba reproducible en testnet (tareas A, B y C) |
| `docs/fases/fase-0.md` | Este reporte |

### Cambios sustanciales respecto a `contracts/escrow`

| # | Cambio | Dónde en `lib.rs` |
| --- | --- | --- |
| 1 | El árbitro es el backend: `release` exige `arbiter.require_auth()` | `release` |
| 2 | `task_id: String` en lugar de `u64` autoincremental; `deposit` rechaza repetidos (`AlreadyExists`) | `DataKey::Task(String)`, `deposit` |
| 3 | El freelancer se define al liberar (`Task.freelancer: Option<Address>`, `None` hasta `release`/`client_release`) | `Task`, `release`, `client_release` |
| 4 | `rules_hash: BytesN<32>` guardado en el depósito | `Task`, `deposit` |
| 5 | `release` publica `ReleaseEvent` con `code_hash` y `verdict_hash` | `ReleaseEvent` |
| 6 | `client_release`: solo el cliente de la tarea (`task.client.require_auth()`); permitido también tras el plazo | `client_release` |
| 7 | `timeout_refund` sin auth, solo tras el plazo, paga siempre a `task.client` | `timeout_refund` |
| 8 | El estado cambia antes de transferir (en la base se transfería y luego se cerraba) | `save_task` antes de `pay` en las tres salidas |
| 9 | Eventos en cada paso (`#[contractevent]`) y TTL extendido en cada escritura, de la tarea y de la instancia | `save_task`, `extend_instance` |
| R | **Revisión:** `release` solo antes del plazo; si `timestamp >= deadline`, error `DeadlinePassed = 9` | `release` |

Además:

- **Plazo:** `ledger().timestamp().checked_add(deadline_secs)`, con `InvalidDeadline` si desborda.
- **Errores:** 1 `NotInitialized`, 2 `AlreadyInitialized`, 3 `InvalidAmount`, 4 `AlreadyExists`, 5 `NotFound`, 6 `NotFunded`, 7 `DeadlineNotReached`, 8 `InvalidDeadline`, 9 `DeadlinePassed`. Los números del 1 al 8 no cambiaron.
- **Eventos:** se usa `#[contractevent]`. `env.events().publish(...)` está marcado `#[deprecated]` en soroban-sdk 25.3.2 y no se usa; compila sin advertencias.

**Regla del plazo (revisión):** tras el plazo, el árbitro ya no puede pagar. La única salida es `timeout_refund`, o `client_release` si el propio cliente decide pagar, así que no hay carrera entre un `release` tardío y el reembolso. En `release` la guardia va después de `funded_task`: una tarea ya cerrada sigue respondiendo `NotFunded` (idempotencia del backend) y no `DeadlinePassed`.

### Tests

| Obligatorio (CLAUDE.md) | Test |
| --- | --- |
| Happy path con saldos finales (cliente, contrato, freelancer) | `test_flujo_feliz_saldos_finales` |
| Doble `release` falla y no mueve fondos | `test_doble_release_falla_sin_mover_fondos` |
| `release` de árbitro falso falla, **sin** `mock_all_auths` | `test_release_arbitro_falso_falla` (modo estricto; control positivo con el árbitro real) |
| `timeout_refund` antes del plazo falla (`env.ledger()`) | `test_timeout_refund_antes_del_plazo_falla` (al depositar y a plazo − 1 s) |
| `timeout_refund` de un tercero devuelve al cliente; saldo del tercero intacto | `test_timeout_refund_por_tercero_devuelve_al_cliente` (sin ninguna firma; `env.auths()` vacío) |
| `timeout_refund` tras `release` falla, y viceversa | `test_timeout_refund_y_release_son_excluyentes` |
| `deposit` con `task_id` repetido falla | `test_deposit_task_id_repetido_falla` (también tras cerrar la tarea) |
| `client_release` de alguien que no es el cliente falla | `test_client_release_no_cliente_falla` (tercero, freelancer y árbitro; control positivo con el cliente) |
| **Revisión:** `release` exactamente en el plazo falla con `DeadlinePassed` y no mueve fondos | `test_release_en_el_plazo_falla` (en el plazo y 1 s después; luego `timeout_refund` sí funciona) |
| **Revisión:** `release` un segundo antes del plazo funciona | `test_release_un_segundo_antes_del_plazo_funciona` |
| **Revisión:** `client_release` después del plazo funciona | `test_client_release_despues_del_plazo_funciona` (modo estricto; después `timeout_refund` da `NotFunded`) |

Adicionales: `test_initialize_dos_veces_falla`, `test_sin_initialize_falla`, `test_deposit_monto_invalido`, `test_deposit_plazo_invalido` (desbordamiento de `checked_add`, plazo 0 y el límite exacto), `test_tarea_inexistente`, `test_evento_release_con_hashes`, `test_ttl_extendido_en_tarea_e_instancia`.

Los tests de permisos (árbitro falso, tercero, cliente falso, `client_release` tras el plazo) usan un modo estricto que nunca llama `mock_all_auths`. Cada firma es una firma de prueba explícita (`mock_auths`) para una cuenta y una llamada concretas, incluida la subinvocación `transfer` del token en `deposit`. Cada test de rechazo tiene un control positivo con la firma correcta, para que el rechazo no se deba a una firma de prueba mal armada. En la revisión se quitó de `test.rs` el vocabulario prohibido por la regla 9.

### Cambios en CLAUDE.md (revisión)

- Tabla del contrato: `release` "solo desde `Funded` y con timestamp < plazo (si no, `DeadlinePassed`)"; `client_release` "permitido también después del plazo"; diagrama de estados con "release (árbitro, antes del plazo)".
- Lista de errores con números fijos (1 a 9), más el párrafo con la regla del plazo.
- Tres tests nuevos en la lista de tests obligatorios.
- Flujo, paso 5 (guardias de `/evaluate`): "quedan al menos 120 s de plazo on-chain (si no, `409 DEADLINE_TOO_CLOSE`)". Paso 9: qué pasa si el contrato responde `DeadlinePassed`.
- Errores de la API: nuevo `DEADLINE_TOO_CLOSE` 409.
- UX: la UI desactiva el envío con menos de **120 s** (antes 60 s), y el backend aplica el mismo margen; plazo de la demo **10 minutos** (antes 5). En `test.rs`, `DEADLINE_SECS` pasó a 600.

## 2. Desviaciones de CLAUDE.md y por qué

1. **Stellar CLI 28.0.0 en lugar de 25.** Es la versión instalada en la máquina. Los comandos de `docs/comandos-basicos.md` de la guía funcionaron sin cambios. El contrato sí usa soroban-sdk 25 (25.3.2). Anotado en el README del contrato.
2. **`initialize` exige la firma del árbitro.** La base no pedía firma. Con `arbiter.require_auth()` nadie puede nombrar árbitro a una cuenta que no controla. La función sigue siendo `initialize` con `AlreadyInitialized`.
3. **Configuración en almacenamiento de instancia.** La base guardaba `Arbiter`/`Token` en persistente; CLAUDE.md pide extender el TTL de la instancia (configuración), así que la configuración vive ahí. Se quitó `NextId` (ya no hay ids autoincrementales).
4. **`deadline_secs = 0` se rechaza con `InvalidDeadline`.** No lo pide CLAUDE.md; un plazo de 0 permitiría reembolsar en el mismo ledger del depósito.
5. **Función de lectura extra `get_config()`.** Devuelve `{arbiter, token}`; sirve para verificar el despliegue (y al backend en sus guardias). No cambia estado.
6. **Eventos con tópicos explícitos** (`#[contractevent(topics = ["release"])]`, etc.): el primer tópico es el nombre de la función y el segundo el `task_id`, para filtrar en el explorador.
7. **`Cargo.lock` sí va al repositorio** (la guía lo ignora): fija las versiones exactas para que el WASM sea reproducible. `test_snapshots/` se ignora.
8. **`contracts/escrow` no se copió como crate aparte**: `cargo test -p escrow` se corrió en el clon de la guía; en este repo solo existe `cumpleycobra`.
9. **Árbitro falso en testnet:** la CLI no llega a enviar la transacción (`Missing signing key for account GAGG…`): al preparar la transacción, la CLI detecta que hace falta la firma del árbitro y `cyc-third` no la tiene. Es la evidencia que da la CLI; el rechazo en el contrato de una firma incorrecta está probado en `test_release_arbitro_falso_falla`.
10. **Código de error de API `DEADLINE_TOO_CLOSE` (409).** La revisión pide que el backend aplique el margen de 120 s; CLAUDE.md no tenía un código para ese rechazo y se agregó uno nuevo sin tocar los existentes. Queda a revisión el nombre.

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

### 3.2 `cargo test -p cumpleycobra` (salida completa, versión final)

```
$ cargo test -p cumpleycobra
    Finished `test` profile [unoptimized + debuginfo] target(s) in 0.25s
     Running unittests src\lib.rs (target\debug\deps\cumpleycobra-70157149090ae560.exe)

running 18 tests
test test::test_sin_initialize_falla ... ok
test test::test_initialize_dos_veces_falla ... ok
test test::test_tarea_inexistente ... ok
test test::test_deposit_monto_invalido ... ok
test test::test_release_en_el_plazo_falla ... ok
test test::test_timeout_refund_por_tercero_devuelve_al_cliente ... ok
test test::test_doble_release_falla_sin_mover_fondos ... ok
test test::test_timeout_refund_antes_del_plazo_falla ... ok
test test::test_flujo_feliz_saldos_finales ... ok
test test::test_release_un_segundo_antes_del_plazo_funciona ... ok
test test::test_deposit_plazo_invalido ... ok
test test::test_deposit_task_id_repetido_falla ... ok
test test::test_client_release_despues_del_plazo_funciona ... ok
test test::test_evento_release_con_hashes ... ok
test test::test_client_release_no_cliente_falla ... ok
test test::test_release_arbitro_falso_falla ... ok
test test::test_timeout_refund_y_release_son_excluyentes ... ok
test test::test_ttl_extendido_en_tarea_e_instancia ... ok

test result: ok. 18 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.19s
```

(La primera entrega tenía 15 tests, todos en verde; la revisión agregó 3.)

### 3.3 `stellar contract build`

```
$ stellar contract build
   Compiling cumpleycobra v0.1.0 (C:\Users\rodri\Desktop\cumpleycobra\contracts\cumpleycobra)
    Finished `release` profile [optimized] target(s)
ℹ️  Build Summary:
    Wasm File: target\wasm32v1-none\release\cumpleycobra.wasm
    Wasm Hash: b5391058c9f211b1fee80a06d50a168c6c66aa25e934bac4b06ad82546dc2a14
    Wasm Size: 8561 bytes optimized (original size was 9898 bytes)
    Exported Functions: 7 found
✅ Build Complete
```

Funciones exportadas: `client_release`, `deposit`, `get_config`, `get_task`, `initialize`, `release`, `timeout_refund`. El hash del WASM desplegado coincide con el que se compila del código del commit (los cambios de `test.rs` no afectan el WASM).

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

Rodrigo fondeó `cyc-client` con 20 USDC desde el faucet de Circle. Horizon confirmó `balance 20.0000000` y `asset_issuer GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5`, el mismo emisor del SAC con el que se inicializó el contrato.

### 3.5 Deploy e initialize (despliegue vigente, tras la revisión)

```
$ stellar contract deploy --wasm target/wasm32v1-none/release/cumpleycobra.wasm --source cyc-arbiter --network testnet --alias cumpleycobra
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/e7e292272947848d1fc5581393cad0ada82b76196c3f050a7db14592bf71f5df
ℹ️  Deploying contract using wasm hash b5391058c9f211b1fee80a06d50a168c6c66aa25e934bac4b06ad82546dc2a14
ℹ️  Signing transaction: 8dffcf15ae6da3e6f1b8f0d1bafd5b07d5652295c5c3a9919ee5bd09d2fb170e
✅ Transaction submitted successfully!
🔗 https://lab.stellar.org/r/testnet/contract/CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ
✅ Deployed!
⚠️  Overwriting existing alias 'cumpleycobra' that currently links to contract ID: CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND
CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ

$ stellar contract invoke --id CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ --source cyc-arbiter --network testnet -- initialize --arbiter cyc-arbiter --token CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA
ℹ️  Signing transaction: 9fb2bbaa2b50e45d97fba17a6681fc5280ed69cfa4507a6e96be46d5e607ba17
📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: InitializeEvent (initialize), arbiter: "GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY", token: "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"

$ stellar contract invoke --id CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ --source cyc-arbiter --network testnet --send=no -- get_config
{"arbiter":"GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY","token":"CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"}
```

### 3.6 Resumen de testnet (despliegue vigente)

**Contract ID:** `CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ`

| Paso | Hash de la transacción | Ledger | Firmó |
| --- | --- | --- | --- |
| Upload WASM | `e7e292272947848d1fc5581393cad0ada82b76196c3f050a7db14592bf71f5df` | 4847405 | cyc-arbiter |
| Deploy | `8dffcf15ae6da3e6f1b8f0d1bafd5b07d5652295c5c3a9919ee5bd09d2fb170e` | 4847406 | cyc-arbiter |
| `initialize` | `9fb2bbaa2b50e45d97fba17a6681fc5280ed69cfa4507a6e96be46d5e607ba17` | 4847409 | cyc-arbiter |
| `deposit` (tarea A, 1 USDC, plazo 600 s) | `c7a30f110bcf399b32d08c69ccf864597cde6e1868ffcc29c2a4a085533c3054` | 4847418 | cyc-client |
| `release` (tarea A) | `1f09cbf7ecb9bcd6d0cbd222291520c30c17fb9285e1357e6c244a9cb7578ee5` | 4847419 | cyc-arbiter |
| `deposit` (tarea B, 1 USDC, plazo 30 s) | `77241b6d00f7811ed132dc7b526f7a2e3846f0abc1c24769ff660e45055e4bd3` | 4847420 | cyc-client |
| `deposit` (tarea C, 1 USDC, plazo 30 s) | `79223db662f1fbc73e3b2d5dd9e593998bf1b754564c4fa1eb6ef9ad3ad91a92` | 4847421 | cyc-client |
| `timeout_refund` (tarea C, tras el `release` rechazado con #9) | `00bd244d1f461ad09898f5a1f7ba09e4dd9df386df2fd2afca166fad78657624` | 4847433 | cyc-client |
| `timeout_refund` (tarea B) | `96b3e1db8de593418f8af732de5a49eded24ab67f39c33b518bbd143c05fa2ba` | 4847434 | cyc-third (tercero) |

Las nueve transacciones aparecen en Horizon con `successful: true`. Casos que debían fallar, y fallaron:

- `release` con `--source cyc-third` (árbitro falso): la CLI no envía la transacción (`Missing signing key for account GAGG…`).
- Segundo `release` de la tarea A: `Error(Contract, #6)` = `NotFunded`.
- `timeout_refund` de la tarea B antes del plazo: `Error(Contract, #7)` = `DeadlineNotReached`.
- **Nuevo:** `release` del árbitro verdadero sobre la tarea C, ya vencido el plazo: `Error(Contract, #9)` = `DeadlinePassed`. Después, `timeout_refund` devolvió el USDC al cliente.

El script ahora comprueba el número exacto de cada error (`must_fail_code`), no solo que falle.

Saldos USDC (unidades) en esta corrida: cliente 190000000 → 180000000; contrato 0 → 0; freelancer 10000000 → 20000000; tercero 0 → 0. A `cyc-client` le quedan **18 USDC** para las fases siguientes.

Primer despliegue, reemplazado por el vigente (`CCGF6WGE3ZJNIY5HBVIDF4HTPLXMUHNNFSNQZCOVOZQEJVQBSWJMU2ND`, WASM `f71f516b…8fea`): deploy `0c3d2e8d…5ea0`, `initialize` `aadabf70…ae02`, `deposit` `c86cc33e…34ec`, `release` `1cdf178c…29e1`, `deposit` `f0f55ce6…470c`, `timeout_refund` `95573e46…1914`. Todas con `successful: true`. Quedó con saldo 0 y todas sus tareas cerradas.

### 3.7 Salida completa de `bash scripts/fase0-testnet.sh` (contra el despliegue vigente)

```
== Contrato CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ | USDC CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA | monto 10000000
== Saldos iniciales
   cliente:    "190000000"
   contrato:   "0"
   freelancer: "10000000"
   tercero:    "0"

== Tarea A (fase0-a-1790260671): deposit con plazo de 600 s
ℹ️  Simulating transaction…
ℹ️  Signing transaction: c7a30f110bcf399b32d08c69ccf864597cde6e1868ffcc29c2a4a085533c3054
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/c7a30f110bcf399b32d08c69ccf864597cde6e1868ffcc29c2a4a085533c3054
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"address":"CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: DepositEvent (deposit), task_id: "fase0-a-1790260671", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790261277, rules_hash: "cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790261277,"freelancer":null,"rules_hash":"cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f","status":"Funded","task_id":"fase0-a-1790260671"}

== Tarea A: release firmado por un árbitro falso (cyc-third)
❌ error: Missing signing key for account GAGGEH7TNBV7Z7TX7OLTBJPEFBWTMLD477P3DTTFFBUAYOZXGGVOKZGY
   -> falló como se esperaba

== Tarea A: release del árbitro
ℹ️  Simulating transaction…
ℹ️  Signing transaction: 1f09cbf7ecb9bcd6d0cbd222291520c30c17fb9285e1357e6c244a9cb7578ee5
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/1f09cbf7ecb9bcd6d0cbd222291520c30c17fb9285e1357e6c244a9cb7578ee5
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ"},{"address":"GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: ReleaseEvent (release), task_id: "fase0-a-1790260671", freelancer: "GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK", amount: "10000000", code_hash: "6fb6a1be31a0c88fa2dca9b726a544095219bf0d9dd9d09cd4b1bd16bdaa8bba", verdict_hash: "838e5cae93a17409b3daa1070c954edcae6e2c6ff0f36afa921a74b8a8fe134f"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790261277,"freelancer":"GDOEMEMACZEM77IREHP6UTOMOJ5MZAKGA4KVPG2CPIKMGT5R5WDPHPNK","rules_hash":"cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f","status":"Released","task_id":"fase0-a-1790260671"}

== Tarea A: segundo release (debe fallar con NotFunded = #6)
❌ error: transaction simulation failed: HostError: Error(Contract, #6)
   0: [Diagnostic Event] contract:CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ, topics:[error, Error(Contract, #6)], data:"escalating Ok(ScErrorType::Contract) frame-exit to Err"
   -> falló con #6 como se esperaba

== Saldos tras la tarea A
   cliente:    "180000000"
   contrato:   "0"
   freelancer: "20000000"
   tercero:    "0"

== Tarea B (fase0-b-1790260671): deposit con plazo de 30 s
ℹ️  Simulating transaction…
ℹ️  Signing transaction: 77241b6d00f7811ed132dc7b526f7a2e3846f0abc1c24769ff660e45055e4bd3
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/77241b6d00f7811ed132dc7b526f7a2e3846f0abc1c24769ff660e45055e4bd3
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"address":"CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: DepositEvent (deposit), task_id: "fase0-b-1790260671", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790260717, rules_hash: "cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790260717,"freelancer":null,"rules_hash":"cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f","status":"Funded","task_id":"fase0-b-1790260671"}

== Tarea B: timeout_refund antes del plazo (debe fallar con DeadlineNotReached = #7)
❌ error: transaction simulation failed: HostError: Error(Contract, #7)
   0: [Diagnostic Event] contract:CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ, topics:[error, Error(Contract, #7)], data:"escalating Ok(ScErrorType::Contract) frame-exit to Err"
   -> falló con #7 como se esperaba

== Tarea C (fase0-c-1790260671): deposit con plazo de 30 s
ℹ️  Simulating transaction…
ℹ️  Signing transaction: 79223db662f1fbc73e3b2d5dd9e593998bf1b754564c4fa1eb6ef9ad3ad91a92
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/79223db662f1fbc73e3b2d5dd9e593998bf1b754564c4fa1eb6ef9ad3ad91a92
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"address":"CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: DepositEvent (deposit), task_id: "fase0-c-1790260671", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000", deadline: 1790260722, rules_hash: "cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790260722,"freelancer":null,"rules_hash":"cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f","status":"Funded","task_id":"fase0-c-1790260671"}

== Saldos con B y C depositadas
   cliente:    "160000000"
   contrato:   "20000000"
   freelancer: "20000000"
   tercero:    "0"

== Esperando 50 s a que venzan los plazos de B y C…

== Tarea C: release del árbitro después del plazo (debe fallar con DeadlinePassed = #9)
❌ error: transaction simulation failed: HostError: Error(Contract, #9)
   0: [Diagnostic Event] contract:CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ, topics:[error, Error(Contract, #9)], data:"escalating Ok(ScErrorType::Contract) frame-exit to Err"
   -> falló con #9 como se esperaba

== Tarea C: timeout_refund
ℹ️  Simulating transaction…
ℹ️  Signing transaction: 00bd244d1f461ad09898f5a1f7ba09e4dd9df386df2fd2afca166fad78657624
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/00bd244d1f461ad09898f5a1f7ba09e4dd9df386df2fd2afca166fad78657624
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: TimeoutRefundEvent (timeout_refund), task_id: "fase0-c-1790260671", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790260722,"freelancer":null,"rules_hash":"cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f","status":"Refunded","task_id":"fase0-c-1790260671"}

== Tarea B: timeout_refund disparado por un tercero (cyc-third)
ℹ️  Simulating transaction…
ℹ️  Signing transaction: 96b3e1db8de593418f8af732de5a49eded24ab67f39c33b518bbd143c05fa2ba
🌎 Sending transaction…
✅ Transaction submitted successfully!
🔗 https://stellar.expert/explorer/testnet/tx/96b3e1db8de593418f8af732de5a49eded24ab67f39c33b518bbd143c05fa2ba
📅 CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA - Success - Event: [{"symbol":"transfer"},{"address":"CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ"},{"address":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB"},{"string":"USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"}] = {"i128":"10000000"}
📅 CAWAZODOFP67HETHN4NLYOECPCJACGLUTCLARVGLBZ7TJDLT4KLQRATQ - Success - Event: TimeoutRefundEvent (timeout_refund), task_id: "fase0-b-1790260671", client: "GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB", amount: "10000000"
null
{"amount":"10000000","client":"GCJUXZSMNWHTRXRCRH5PIZU7USEMYAM4GGJRGF7FLZBNMO3R2WZY6CAB","deadline":1790260717,"freelancer":null,"rules_hash":"cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f","status":"Refunded","task_id":"fase0-b-1790260671"}
   USDC del tercero antes: "0", después: "0"

== Saldos finales
   cliente:    "180000000"
   contrato:   "0"
   freelancer: "20000000"
   tercero:    "0"

== Resumen
rules_hash:   cb6f7e47d1dca33bafb9a37bdf918d5ea7b2bfa7ed1cb7b885cfef958407d88f
code_hash:    6fb6a1be31a0c88fa2dca9b726a544095219bf0d9dd9d09cd4b1bd16bdaa8bba
verdict_hash: 838e5cae93a17409b3daa1070c954edcae6e2c6ff0f36afa921a74b8a8fe134f
deposit A:        c7a30f110bcf399b32d08c69ccf864597cde6e1868ffcc29c2a4a085533c3054
release A:        1f09cbf7ecb9bcd6d0cbd222291520c30c17fb9285e1357e6c244a9cb7578ee5
deposit B:        77241b6d00f7811ed132dc7b526f7a2e3846f0abc1c24769ff660e45055e4bd3
timeout_refund B: 96b3e1db8de593418f8af732de5a49eded24ab67f39c33b518bbd143c05fa2ba
deposit C:        79223db662f1fbc73e3b2d5dd9e593998bf1b754564c4fa1eb6ef9ad3ad91a92
timeout_refund C: 00bd244d1f461ad09898f5a1f7ba09e4dd9df386df2fd2afca166fad78657624
```

## 4. Pendientes y riesgos detectados

1. **Margen de 120 s en el backend (fase 1).** La guardia de `/evaluate` debe leer el plazo on-chain (`get_task`) y rechazar con `DEADLINE_TOO_CLOSE` si quedan menos de 120 s. Si aun así el plazo vence entre la guardia y el `release` (Gemini tarda hasta 45 s más reintentos), el contrato responde `#9`. El backend debe reportar "no se pagó", no reintentar, y dejar `client_release`/`timeout_refund` como salidas.
2. **Ventana entre deploy e `initialize`.** Son dos transacciones; entre ellas un tercero podría inicializar con un árbitro propio (desde la desviación 2, solo con un árbitro que él mismo firme). Mitigación: `get_config` verificado justo después (sección 3.5). Alternativa para producción: `__constructor`, que despliega e inicializa en una sola transacción.
3. **`client_release` y `release` pagan a la dirección que reciben.** Por diseño, el contrato confía en el árbitro y en el cliente. El backend debe pasar siempre la dirección amarrada en `/accept`, nunca una que llegue en el cuerpo de `/evaluate`.
4. **`task_id` sin límite de longitud en el contrato.** Lo genera el backend. Conviene un formato corto y fijo (por ejemplo, 16 a 24 caracteres URL-safe).
5. **TTL.** Las tareas y la instancia quedan con 30 días de vida tras cada escritura. Una tarea cerrada que se archive se puede restaurar; por eso `deposit` sigue viendo el `task_id` como existente y no se reutiliza.
6. **Llaves de testnet** en `C:\Users\rodri\.config\stellar\identity\` (fuera del repo). Para la fase 1: `ARBITER_SECRET_KEY` = `stellar keys secret cyc-arbiter`, solo en el `.env` del backend.
7. **Saldo USDC:** 18 USDC en `cyc-client`. `scripts/fase0-testnet.sh` gasta 1 USDC neto por corrida (el que cobra el freelancer).
