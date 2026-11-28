# Cumple&Cobra en mainnet (edición experimental)

Misión especial de Ship It (27 de noviembre de 2026): llevar el contrato a la red principal de Stellar y usar desde el frontend sus cinco funciones más importantes.

> **Experimental, sin auditoría.** Se usa con montos mínimos y con la wallet propia del equipo. No acepta fondos de terceros. El flujo normal de Cumple&Cobra sigue en testnet. Es una excepción acotada a la regla 16 de `CLAUDE.md` (nada de mainnet todavía): la llave del árbitro de mainnet es nueva y distinta de la de testnet, y el contrato se pausa al terminar el reto.

## Qué se desplegó

| | |
| --- | --- |
| Contrato | [`CAAP6Y242FALZ4M46BAICKABWA5T2HG7VL62E3M6BSVG3XI77SA6IYNX`](https://stellar.expert/explorer/public/contract/CAAP6Y242FALZ4M46BAICKABWA5T2HG7VL62E3M6BSVG3XI77SA6IYNX) |
| Código | Edición ligera [`contracts/cumpleycobra-mainnet`](../contracts/cumpleycobra-mainnet/src/lib.rs): el mismo contrato de testnet recortado a `initialize`, las cinco funciones de abajo, `get_task` y `pause`/`unpause`. Misma estructura `Task`, mismas reglas y mismos números de error. 9 235 bytes (WASM `e2920dde…d671a`), 5 tests en verde. El contrato completo (63 KB) costaba unos 77 XLM solo de subida en mainnet |
| Red | Mainnet (`Public Global Stellar Network ; September 2015`) |
| RPC | Gateway.fm, `https://soroban-rpc.mainnet.stellar.gateway.fm` (público, gratis, CORS abierto); respaldo `https://mainnet.sorobanrpc.com` |
| Token | XLM nativo (SAC `CAS3J7GYLGXMF6TDJBBYYSE3HQ6BBSMLNUQ34T6TZMYMW2EVH34XOWMA`): la wallet de prueba no necesita trustline. Para un lanzamiento real, USDC de Circle (`USDC:GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN`, SAC `CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75`) |
| Árbitro | Llave nueva solo de mainnet (`GBPHVFM2…I46ZC`, en el almacén seguro de Windows). No firma ninguna de las cinco funciones de abajo; solo `initialize` y, al final, `pause` |
| Despliegue | Subida del WASM [`ef41019c…`](https://stellar.expert/explorer/public/tx/ef41019ce9452da13f5e369567643d6eb297d8476f93f86cc525703c4407542b) (12.5 XLM), contrato [`2da9c28d…`](https://stellar.expert/explorer/public/tx/2da9c28dcd691554ddf92a6a01736a5d4cc252ff46b34bed6c4c52b755bf53c9), `initialize` [`07b54ef7…`](https://stellar.expert/explorer/public/tx/07b54ef7cc79b72fa2e9fa0c256a5d364f327b42d19bd19b33ea716aa8e659f1) (0.03 XLM) |

## Dónde y cómo usa el frontend cada función

Todo vive en la página **`/mainnet`** ([`frontend/src/app/mainnet/page.tsx`](../frontend/src/app/mainnet/page.tsx)), con la configuración separada en [`frontend/src/lib/mainnet.ts`](../frontend/src/lib/mainnet.ts) para que nada del flujo de testnet apunte a mainnet.

1. **Conectar:** el botón «Conectar Freighter (Mainnet)» pide acceso con `requestAccess` y comprueba con `getNetworkDetails` que la extensión esté en la red pública; si no, no deja continuar.
2. **Armar y firmar:** cada botón arma la invocación con `@stellar/stellar-sdk` (`buildCall`), la prepara contra el RPC (simulación: footprint, recursos y autorizaciones), Freighter la firma (`signTransaction` con la frase de mainnet) y `submitAndWait` la envía y espera `SUCCESS`.
3. **Resultado:** el hash aparece en «Transacciones de esta sesión» con su enlace a stellar.expert, y «Leer tarea» muestra el estado on-chain (`get_task`, solo simulación).

| # | Función | Botón en `/mainnet` | Quién firma | Qué hace |
| --- | --- | --- | --- | --- |
| 1 | `deposit` | «Depositar» | Cliente (Freighter) | Deposita el monto en USDC con el plazo en minutos. El `rules_hash` se calcula en el navegador con la misma definición del backend (`lib/acuerdo.ts`, la que usa `/verificar`) sobre el acuerdo de prueba fijo de la página |
| 2 | `top_up_task` | «Recargar» | Cliente | Agrega USDC a la tarea antes del plazo; el pago posterior incluye el extra |
| 3 | `extend_deadline` | «Prorrogar» | Cliente | Suma minutos al plazo; solo puede crecer y nunca más de 28 días desde ahora |
| 4 | `client_release` | «Pagar» | Cliente | Aprueba manualmente y el contrato paga al programador (por defecto, la misma wallet conectada) |
| 5 | `timeout_refund` | «Reembolsar por plazo» | Cualquiera | Tras el plazo, devuelve el depósito íntegro al cliente |

## Transacciones en mainnet

| Función | Transacción |
| --- | --- |
| `deposit` | _pendiente_ |
| `top_up_task` | _pendiente_ |
| `extend_deadline` | _pendiente_ |
| `client_release` | _pendiente_ |
| `timeout_refund` | _pendiente_ |

## Costos medidos

En mainnet, la subida del contrato completo de 63 KB se simuló en 77 XLM; la edición ligera de 9 KB costó 12.5 XLM y su `initialize` 0.03 XLM. En testnet, al subir v8: subir el código costó 5.72 XLM, crear el contrato 0.002 XLM e `initialize` 18.75 XLM (incluye la renta de 30 días del código). Cada llamada costó entre 0.001 y 0.05 XLM. Con las reservas mínimas de las cuentas, el presupuesto es de unos 30 XLM más centavos de USDC, que vuelven a la wallet al cerrar las tareas.

## Cómo se cierra después del reto

Un contrato desplegado no se puede borrar de la red. La edición experimental se cierra así:

1. Se cierran las tareas de prueba: el contrato queda en saldo 0 (`get_stats`).
2. El árbitro llama `pause`: nadie puede volver a depositar. Pagos y reembolsos nunca se pausan.
3. Se quita la página `/mainnet` del frontend.
4. Sin uso, el ledger archiva el contrato al vencer su TTL (unos 30 días).

Un lanzamiento real en mainnet sería otro contrato, con solo las funciones que se usen, auditado y con lo legal y lo fiscal revisados.
