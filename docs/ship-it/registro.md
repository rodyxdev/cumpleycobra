# Ship It: Builder Challenge (BAF x Stellar)

Del 23 al 27 de noviembre de 2026. Cuentan los commits a `main` por su calidad, no por su volumen: nada de commits vacíos ni de relleno. Cada día a las 00:00 (hora de la Ciudad de México) se abre una misión.

**Convenciones:**
- Los commits del reto llevan el prefijo `ship-it: …`.
- Los del Instaward llevan otro prefijo (`instaward(avance-N): …`) y se registran en `docs/instaward/seguimiento.md`.

**Despliegue:** cada push a `main` despliega el frontend en Vercel a producción, aunque el commit solo toque documentación. Cloud Run no se despliega solo: la API se publica a mano con `gcloud`.

| Fecha | Misión | Commit | Qué cambió |
| --- | --- | --- | --- |
| 23 nov | 01 · Despegue | [`a5167b1`](https://github.com/rodyxdev/cumpleycobra/commit/a5167b1) | Regla permanente de seguimiento (Instaward y Ship It) en `CLAUDE.md`, el seguimiento del SOW con evidencia y este registro |
| 23 nov | 01 · Despegue | [`631238e`](https://github.com/rodyxdev/cumpleycobra/commit/631238e) | «Iniciar sesión» en lugar de «Login with Pollar»; los textos de la interfaz ya no dicen «con Pollar» |
| 23 nov | 01 · Despegue | [`816c5f9`](https://github.com/rodyxdev/cumpleycobra/commit/816c5f9) | El programador ve «Esta tarea ya se pagó» (o «el depósito volvió al cliente») en lugar de «La tarea ya no está depositada» |
| 23 nov | 01 · Despegue | [`355ef0a`](https://github.com/rodyxdev/cumpleycobra/commit/355ef0a) | Vista de celular medida a 375 px: encabezado de 220 a 105 px, línea de estado de 387 a 258 px, botón de `/probar` en la primera pantalla y áreas de toque de 40 px o más |
| 23 nov | 01 · Despegue | [`b209867`](https://github.com/rodyxdev/cumpleycobra/commit/b209867) | README: qué lanzamos el 27 de noviembre (lo pide la misión) |
| 23 nov | 01 · Historia | — | Historia de Instagram con el avance: [`historia-dia-1.png`](historia-dia-1.png) |
| 24 nov | 02 · Toca Stellar | — | Pago real del contrato en producción tras verificar ejecutando: [tx `9038ddab…`](https://stellar.expert/explorer/testnet/tx/9038ddab89f2d8efd1d843998411b9bf6bb3be067fad7816baab4a7469f90c47) (`release`, 24 nov 07:17 UTC) |
| 24 nov | Suma más · Función nueva | [`b9d4ecc`](https://github.com/rodyxdev/cumpleycobra/commit/b9d4ecc) | Contrato v2 con pago por hitos: `deposit_milestones`, `release_milestone`, `client_release_milestone` y `timeout_refund_milestone`, con 14 tests nuevos (32 en total) |
| 24 nov | Suma más · Función nueva | [`7f95fd9`](https://github.com/rodyxdev/cumpleycobra/commit/7f95fd9) | v2 desplegado en testnet (`CAUBTDTW…R2K77K`) y un proyecto real de 3 hitos que usó las cuatro funciones: [depósito](https://stellar.expert/explorer/testnet/tx/937e9e5fa76c729c1ed8c5091365e94c55af6194e68900298be5785d28f50869), [pago del árbitro](https://stellar.expert/explorer/testnet/tx/7dba94e6ed54ac3506cf278d5ec7116ba6b53233e5dafee42196ee109a88d18b), [aprobación manual](https://stellar.expert/explorer/testnet/tx/f77f3d03909f5d7787314902d5a75daa191fa43330a0c79858b2601ef2a8acf6) y [reembolso por plazo](https://stellar.expert/explorer/testnet/tx/bf5c4aa051043d1e6a67841eb3b304342fde045b8b11eb7aaba969859bf94fd5) |
| 25 nov | Suma más · Función nueva | [`54acf58`](https://github.com/rodyxdev/cumpleycobra/commit/54acf58) | Contrato v3 con `add_milestone` y `top_up_milestone`, con 6 tests nuevos (38 en total, 0 advertencias) |
| 25 nov | Suma más · Función nueva | [`e993609`](https://github.com/rodyxdev/cumpleycobra/commit/e993609) | Documentación de v3 (`docs/hitos/diseno.md`, `contracts/cumpleycobra/README.md`) y script `scripts/hitos_v3_testnet.sh` |
| 25 nov | Suma más · Función nueva | [`73da953`](https://github.com/rodyxdev/cumpleycobra/commit/73da953) | v3 desplegado en testnet (`CCBZZMNY…JFJTC`, [despliegue](https://stellar.expert/explorer/testnet/tx/df4c596db8c558d1997d24e12ea69c94cb8fccf1d0e81d6955d1e8396414da23), [`initialize`](https://stellar.expert/explorer/testnet/tx/37ac8df43e762140894e873834a65e74b09183619f4af8b0e90389d550984f4a)) y proyecto `hitos-v3-1795672283`: [depósito](https://stellar.expert/explorer/testnet/tx/af63c030efaed7222543f93cf105c6d93237c7c314f15b07ecde9b2bec0e9f89), [`add_milestone`](https://stellar.expert/explorer/testnet/tx/99c24b57fd288231c31f8a728ccc1283386fa76b89e5aa67590defe55932c712), [`top_up_milestone`](https://stellar.expert/explorer/testnet/tx/34bcc592979a29854ce50028c2c79356fef9611a769a4461a7e9ab0c9b48b7af) y 3 `release_milestone` ([hito 0](https://stellar.expert/explorer/testnet/tx/4a89d7eb0a92f742d74eb8e479cb32794ad904e21d2f084bfcc7dfa8fc95abb5), [hito 1](https://stellar.expert/explorer/testnet/tx/9a6920d7aed5a1712b61bc3544153428904080e35cd9e7258f023de97d67459e), [hito 2](https://stellar.expert/explorer/testnet/tx/32e540258a27a4432b9421b57f8f4efec57eaa620f14d9cbd1d8ef6f17da5013)) |
| 26 nov | Etapa 2 · Backend hitos | [`cf041ed`](https://github.com/rodyxdev/cumpleycobra/commit/cf041ed)–[`a83a4ae`](https://github.com/rodyxdev/cumpleycobra/commit/a83a4ae) | Backend de hitos detrás de `MILESTONES_ENABLED`: hash v3, `get_project`/`release_milestone` en `stellar_client.py`, `POST /tasks` con `milestones`, evaluación/verificación/pago por hito y 22 tests nuevos |
| 26 nov | Suma más · Función nueva | [`a55341e`](https://github.com/rodyxdev/cumpleycobra/commit/a55341e) | Contrato v4 (lote 1): `mutual_split_task` y `mutual_split_milestone` con doble firma cliente + programador y tests en `src/test_v4.rs` |
| 26 nov | Suma más · Función nueva | [`85ffd25`](https://github.com/rodyxdev/cumpleycobra/commit/85ffd25) | Contrato v4 (lote 2): `cancel_unassigned_task` y `cancel_unassigned_project` con doble firma cliente + árbitro (`AlreadyAssigned` #13) |
| 26 nov | Suma más · Función nueva | [`d2bea08`](https://github.com/rodyxdev/cumpleycobra/commit/d2bea08) | Contrato v4 (lote 3): `refund_all_expired_milestones` (lote sin permisos) y `reduce_milestone` (doble firma) |
| 26 nov | Suma más · Función nueva | [`d6851dc`](https://github.com/rodyxdev/cumpleycobra/commit/d6851dc) | Contrato v4 (lote 4): `client_release_with_bonus` y `batch_deposit` |
| 26 nov | Suma más · Función nueva | [`72512a6`](https://github.com/rodyxdev/cumpleycobra/commit/72512a6) | Contrato v4 (lote 5): `split_milestone` y `extend_milestone_deadline` |
| 26 nov | Suma más · Función nueva | [`a23eda7`](https://github.com/rodyxdev/cumpleycobra/commit/a23eda7) | Contrato v4 (lote 6): `rotate_arbiter` con doble firma atómica (`SameArbiter` #14) |
| 26 nov | Suma más · Función nueva | [`2c83420`](https://github.com/rodyxdev/cumpleycobra/commit/2c83420) | Pruebas estrictas de autorización e invariante contable combinado de v4 (52 tests totales en verde, 0 advertencias) |
| 26 nov | Suma más · Función nueva | [`d56f050`](https://github.com/rodyxdev/cumpleycobra/commit/d56f050) | v4 desplegado en testnet (`CBZ6TBVT…TFK2E`, [despliegue](https://stellar.expert/explorer/testnet/tx/01c4d856c1b4b797cfe8ff2adc2978a29540f604d75971e79e17f4322f71dcd8), [`initialize`](https://stellar.expert/explorer/testnet/tx/f7ad54e0734e999fb3f96adff9cfaa3e9eb567ba6ace40be893b4d1483210fca)) y corrida real `1795741507` ejecutando las 11 funciones nuevas (`scripts/hitos_v4_testnet.sh`, saldo final del contrato en 0 USDC) |
| 26 nov | Suma más · Función nueva | [`c7a0ff2`](https://github.com/rodyxdev/cumpleycobra/commit/c7a0ff2) | Página `/verificar`: el navegador recalcula el `rules_hash` (JSON canónico + SHA-256 con Web Crypto) y lo compara con el del contrato. Probada con la tarea real `Fzw_5tOvZG-FmM7o` de producción (coincide on-chain) |
| 26 nov | Suma más · Función nueva | [`673ca08`](https://github.com/rodyxdev/cumpleycobra/commit/673ca08) | «Agregar al calendario»: descarga un `.ics` con el plazo on-chain de la tarea y un aviso 30 minutos antes |
| 26 nov | Suma más · Función nueva | [`042ca80`](https://github.com/rodyxdev/cumpleycobra/commit/042ca80) | Insignia SVG pública del programador (`/programadores/{address}/insignia.svg`) con sus pagos confirmados on-chain. Experimental, detrás de `EXTRAS_ENABLED` |
| 26 nov | Suma más · Función nueva | [`94efdcb`](https://github.com/rodyxdev/cumpleycobra/commit/94efdcb) | Comprobante público de pago (`/tasks/{id}/comprobante`) con transacción, `rules_hash`, `code_hash` y `verdict_hash`. Experimental, detrás de `EXTRAS_ENABLED` |
| 26 nov | Suma más · Función nueva | [`044713d`](https://github.com/rodyxdev/cumpleycobra/commit/044713d) | Contrato v5 (lote 1): `assign_freelancer` y `assign_project_freelancer`; con programador registrado, ningún pago del cliente puede ir a otra dirección (`WrongFreelancer`) |
| 26 nov | Suma más · Función nueva | [`a2db595`](https://github.com/rodyxdev/cumpleycobra/commit/a2db595) | Contrato v5 (lote 2): `extend_deadline`, `top_up_task`, `freelancer_refund` y `get_tasks` (68 tests en verde, 0 advertencias) |
| 26 nov | Suma más · Función nueva | [`da45f69`](https://github.com/rodyxdev/cumpleycobra/commit/da45f69) | v5 desplegado en testnet (`CDWVPFHQ…UZEXM`, [despliegue](https://stellar.expert/explorer/testnet/tx/4a4e568f6c54c042dc8dc6adc5cc926c2179d9b9f81ec8c4e52f860072532579), [`initialize`](https://stellar.expert/explorer/testnet/tx/0f111a6d0ba9535c53ba628b22ca7b47411b9414b5aefc96e94e048ba9ee5c2c)) y corrida real `1795754103` de las 6 funciones nuevas (`scripts/v5_testnet.sh`): el pago a otra dirección se rechazó on-chain con `#12` y el saldo final del contrato quedó en 0 USDC |
| 27 nov | Suma más · Función nueva | [`7b668b0`](https://github.com/rodyxdev/cumpleycobra/commit/7b668b0) | Contrato v6 (lote 1): `amend_rules`, `release_partial`, `mutual_cancel`, `reassign_freelancer` y `transfer_client`; todo cambio entre las partes lo firman las dos |
| 27 nov | Suma más · Función nueva | [`a66b156`](https://github.com/rodyxdev/cumpleycobra/commit/a66b156) | Contrato v6 (lote 2): `tip`, `bump_ttl`, `get_stats` (totales que cuadran con el saldo real) y `deposit_assigned` |
| 27 nov | Suma más · Función nueva | [`b35bdce`](https://github.com/rodyxdev/cumpleycobra/commit/b35bdce) | Contrato v6 (lote 3): `open_dispute`, `resolve_dispute`, `get_dispute`, `pause` y `unpause` (84 tests en verde, 0 advertencias) |
| 27 nov | Suma más · Función nueva | [`600371f`](https://github.com/rodyxdev/cumpleycobra/commit/600371f) | v6 desplegado en testnet (`CD5ZI4KI…5TABU`, [despliegue](https://stellar.expert/explorer/testnet/tx/a2589fb6731db86a033f694bccd12bfb751017b2642171b26ae205686e5b34fc), [`initialize`](https://stellar.expert/explorer/testnet/tx/8dd3d71df35957ce4eb69ff76fe518af7dd24be50ed5bd72f3e4cbf4841b0b0a)) y corrida real `1795755491` de las 14 funciones nuevas, hasta con tres firmas por transacción (`scripts/v6_testnet.sh`): saldo final 0 USDC y `get_stats` cuadrado |
| 27 nov | Suma más · Función nueva | [`272efc5`](https://github.com/rodyxdev/cumpleycobra/commit/272efc5) | Contrato v7 (lote 1): `amend_milestone_rules`, `release_milestone_partial`, `mutual_cancel_project`, `reassign_project_freelancer` y `transfer_project_client` |
| 27 nov | Suma más · Función nueva | [`e2c38f3`](https://github.com/rodyxdev/cumpleycobra/commit/e2c38f3) | Contrato v7 (lote 2): `open_milestone_dispute`, `resolve_milestone_dispute`, `get_milestone_dispute`, `cancel_dispute` y `cancel_milestone_dispute` |
| 27 nov | Suma más · Función nueva | [`90df24e`](https://github.com/rodyxdev/cumpleycobra/commit/90df24e) | Contrato v7 (lote 3): `release_batch`, `refund_batch` y `get_projects` (97 tests en verde, 0 advertencias) |
| 27 nov | Suma más · Función nueva | [`6dcfc85`](https://github.com/rodyxdev/cumpleycobra/commit/6dcfc85) | v7 desplegado en testnet (`CCTEXF2I…JAHDM`, [despliegue](https://stellar.expert/explorer/testnet/tx/78b4207eba881f10f31082b2f43779fcd0b47b5a4d5eb573e96b61977fd640bc), [`initialize`](https://stellar.expert/explorer/testnet/tx/59eaa2c7c47b1c019a4cc62c08873c9755eda3b89871bda773c2742de3ac60c2)) y corrida real `1795757039` de las 13 funciones nuevas (`scripts/v7_testnet.sh`): saldo final 0 USDC y `get_stats` cuadrado |
| 27 nov | Suma más · Función nueva | [`4696c1d`](https://github.com/rodyxdev/cumpleycobra/commit/4696c1d) | Contrato v8 (lote 1): pago por tiempo con `deposit_stream`, `withdraw_stream` y `cancel_stream` |
| 27 nov | Suma más · Función nueva | [`d284872`](https://github.com/rodyxdev/cumpleycobra/commit/d284872) | Contrato v8 (lote 2): garantía del programador con `post_bond`, `reclaim_bond` y `slash_bond` (106 tests en verde, 0 advertencias) |
| 27 nov | Suma más · Función nueva | este commit | v8 desplegado en testnet (`CB3VPJSL…O4AKZ`, [despliegue](https://stellar.expert/explorer/testnet/tx/72411331252ce21e5f8614653621832a9c30f543052276b8ca1ef7ec7dd848fd), [`initialize`](https://stellar.expert/explorer/testnet/tx/fcf7406c6b5d2f5f3cbe9dc30a9f737c676fb0ad7183907eff797d60d57a2372)) y corrida real `1795759595` de las 6 funciones nuevas (`scripts/v8_testnet.sh`): saldo final 0 USDC y `get_stats` cuadrado |

## Funciones experimentales (por revisar)

Se agregaron durante el reto y **no están en el plan de mejora** (`docs/mejora/plan.md`). Después del 27 de noviembre se revisan una por una: las que se queden pasan a su lugar definitivo y las demás se borran sin tocar nada más.

| Función | Commit | Dónde vive | Cómo quitarla | En producción |
| --- | --- | --- | --- | --- |
| Página `/verificar` | [`c7a0ff2`](https://github.com/rodyxdev/cumpleycobra/commit/c7a0ff2) | `frontend/src/app/verificar/`, `frontend/src/lib/acuerdo.ts`, enlace en `frontend/src/app/cliente/page.tsx` | Revertir el commit | Sí, al hacer push (solo lectura de `GET /tasks/{id}`) |
| Plazo en el calendario (`.ics`) | [`673ca08`](https://github.com/rodyxdev/cumpleycobra/commit/673ca08) | `frontend/src/lib/calendario.ts`, botón en `frontend/src/components/status-card.tsx` | Revertir el commit | Sí, al hacer push (no llama a la API) |
| Insignia SVG del programador | [`042ca80`](https://github.com/rodyxdev/cumpleycobra/commit/042ca80) | `backend/extras.py` | Borrar `backend/extras.py`, su `include_router` en `backend/main.py` y `backend/tests/test_extras.py` | No: requiere desplegar la API y `EXTRAS_ENABLED=true` |
| Comprobante público de pago | [`94efdcb`](https://github.com/rodyxdev/cumpleycobra/commit/94efdcb) | `backend/extras.py` | Igual que la insignia | No: requiere desplegar la API y `EXTRAS_ENABLED=true` |

## Revisión de las funciones reclamadas (27 de noviembre de 2026)

De 37 reclamos, 28 se aprobaron y 9 se rechazaron. Los rechazos dejan cinco reglas que se aplican antes de proponer o reclamar una función:

| Regla del revisor | Rechazadas por esa regla |
| --- | --- |
| Solo lectura no cuenta | `get_dispute`, `get_stats`, `get_tasks` (se había aprobado por error y se corrigió) |
| Solo guardar un valor o una bandera no cuenta | `pause`, `unpause` |
| Mantenimiento no cuenta | `bump_ttl` |
| Combinar funciones que ya existen no cuenta | `deposit_assigned` (= `deposit` + `assign_freelancer`) |
| Repetir una regla o un resultado que ya existe no cuenta | `assign_project_freelancer` (repite `bind_freelancer`), `mutual_cancel` (mismo resultado que `freelancer_refund`) |

Las funciones siguen en los contratos y sus tests siguen en el repositorio: solo no suman puntos.

**Contrato v7 antes de reclamar, con esas reglas:**

| Función | Riesgo | Por qué |
| --- | --- | --- |
| `release_milestone_partial` | Bajo | Mueve dinero; versión de hito de `release_partial` (aprobada), como otras de hito ya aprobadas |
| `resolve_milestone_dispute` | Bajo | Reparte dinero; versión de hito de `resolve_dispute` (aprobada) |
| `reassign_project_freelancer` | Bajo | `bind_freelancer` no permite cambiar al programador ya fijado; versión de proyecto de `reassign_freelancer` (aprobada) |
| `transfer_project_client` | Bajo | Versión de proyecto de `transfer_client` (aprobada) |
| `open_milestone_dispute` | Medio | Versión de hito de `open_dispute` (aprobada), pero en el fondo guarda quién la abrió |
| `amend_milestone_rules` | Medio | Versión de hito de `amend_rules` (aprobada), pero solo cambia un hash guardado |
| `release_batch` | Medio | Lote nuevo como `batch_deposit` (aprobada), pero podría verse como `release` repetido |
| `refund_batch` | Medio | Lote como `refund_all_expired_milestones` (aprobada), pero podría verse como `timeout_refund` repetido |
| `mutual_cancel_project` | Alto | Es el `mutual_cancel` de proyectos, y `mutual_cancel` se rechazó |
| `cancel_dispute`, `cancel_milestone_dispute` | Alto | Solo borran un valor guardado |
| `get_milestone_dispute`, `get_projects` | No reclamar | Solo lectura |
