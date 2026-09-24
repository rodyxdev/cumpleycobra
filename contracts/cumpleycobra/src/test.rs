#![cfg(test)]

// Pruebas del contrato Cumple&Cobra.
//
// Hay dos modos de preparación:
// - `Modo::Libre`: usa `mock_all_auths`, cualquier `require_auth` pasa. Sirve
//   para probar la lógica de estados y saldos.
// - `Modo::Estricto`: NUNCA llama `mock_all_auths`. Cada firma es una firma de
//   prueba explícita (`mock_auths`) para una cuenta y una llamada concretas.
//   Es el único modo válido para probar que alguien SIN permiso es rechazado.

extern crate std;

use super::*;
use soroban_sdk::{
    testutils::{
        storage::{Instance as _, Persistent as _},
        Address as _, Events as _, Ledger as _, MockAuth, MockAuthInvoke,
    },
    token::{Client as TokenClient, StellarAssetClient},
    Address, BytesN, Env, Event, IntoVal, String,
};

// 1 USDC = 10_000_000 unidades (7 decimales).
const UNIT: i128 = 10_000_000;
// Saldo inicial del cliente: 100 USDC.
const MINT: i128 = 100 * UNIT;
// Monto de cada tarea: 10 USDC.
const AMOUNT: i128 = 10 * UNIT;
// Plazo de la demo: 10 minutos.
const DEADLINE_SECS: u64 = 600;
// Timestamp inicial del ledger en las pruebas.
const START_TS: u64 = 1_000_000;

#[derive(PartialEq)]
enum Modo {
    Libre,
    Estricto,
}

// Todo lo que necesita una prueba.
struct Ctx {
    env: Env,
    modo: Modo,
    arbiter: Address,
    client: Address,
    freelancer: Address,
    third: Address,
    token: TokenClient<'static>,
    contract_id: Address,
    c: CumpleYCobraContractClient<'static>,
}

// Hashes de ejemplo (en producción son SHA-256 calculados en el backend).
fn rules_hash(env: &Env) -> BytesN<32> {
    BytesN::from_array(env, &[1u8; 32])
}
fn code_hash(env: &Env) -> BytesN<32> {
    BytesN::from_array(env, &[2u8; 32])
}
fn verdict_hash(env: &Env) -> BytesN<32> {
    BytesN::from_array(env, &[3u8; 32])
}
fn tid(env: &Env, s: &str) -> String {
    String::from_str(env, s)
}

// Prepara el entorno: token SAC, saldos iniciales, contrato inicializado.
fn setup(modo: Modo) -> Ctx {
    let env = Env::default();
    if modo == Modo::Libre {
        env.mock_all_auths();
    }
    env.ledger().set_timestamp(START_TS);

    let arbiter = Address::generate(&env);
    let client = Address::generate(&env);
    let freelancer = Address::generate(&env);
    let third = Address::generate(&env);
    let token_admin = Address::generate(&env);

    // Token SAC de prueba (hace el papel del USDC de testnet).
    let sac = env.register_stellar_asset_contract_v2(token_admin.clone());
    let token_id = sac.address();
    let sac_admin = StellarAssetClient::new(&env, &token_id);

    // Acuñar: al cliente 100 USDC y al tercero 7 unidades (para comprobar
    // después que su saldo no cambia).
    for (to, amt) in [(&client, MINT), (&third, 7i128)] {
        if modo == Modo::Estricto {
            env.mock_auths(&[MockAuth {
                address: &token_admin,
                invoke: &MockAuthInvoke {
                    contract: &token_id,
                    fn_name: "mint",
                    args: (to, amt).into_val(&env),
                    sub_invokes: &[],
                },
            }]);
        }
        sac_admin.mint(to, &amt);
    }

    // Registrar e inicializar el contrato (initialize exige la firma del árbitro).
    let contract_id = env.register(CumpleYCobraContract, ());
    let c = CumpleYCobraContractClient::new(&env, &contract_id);
    if modo == Modo::Estricto {
        env.mock_auths(&[MockAuth {
            address: &arbiter,
            invoke: &MockAuthInvoke {
                contract: &contract_id,
                fn_name: "initialize",
                args: (&arbiter, &token_id).into_val(&env),
                sub_invokes: &[],
            },
        }]);
    }
    c.initialize(&arbiter, &token_id);

    let token = TokenClient::new(&env, &token_id);
    Ctx {
        env,
        modo,
        arbiter,
        client,
        freelancer,
        third,
        token,
        contract_id,
        c,
    }
}

// El cliente deposita AMOUNT para `id`. En modo estricto se registra una firma
// de prueba del cliente exactamente sobre `deposit` y la transferencia interna.
fn deposit(ctx: &Ctx, id: &str) -> String {
    let env = &ctx.env;
    let task_id = tid(env, id);
    let rules = rules_hash(env);
    if ctx.modo == Modo::Estricto {
        env.mock_auths(&[MockAuth {
            address: &ctx.client,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "deposit",
                args: (&ctx.client, task_id.clone(), AMOUNT, DEADLINE_SECS, rules.clone())
                    .into_val(env),
                sub_invokes: &[MockAuthInvoke {
                    contract: &ctx.token.address,
                    fn_name: "transfer",
                    args: (&ctx.client, &ctx.contract_id, AMOUNT).into_val(env),
                    sub_invokes: &[],
                }],
            },
        }]);
    }
    ctx.c
        .deposit(&ctx.client, &task_id, &AMOUNT, &DEADLINE_SECS, &rules);
    task_id
}

// Registra una firma de prueba de `quien` sobre `release` con los argumentos dados.
fn mock_release(ctx: &Ctx, quien: &Address, task_id: &String) {
    let env = &ctx.env;
    env.mock_auths(&[MockAuth {
        address: quien,
        invoke: &MockAuthInvoke {
            contract: &ctx.contract_id,
            fn_name: "release",
            args: (
                task_id.clone(),
                &ctx.freelancer,
                code_hash(env),
                verdict_hash(env),
            )
                .into_val(env),
            sub_invokes: &[],
        },
    }]);
}

// Registra una firma de prueba de `quien` sobre `client_release`.
fn mock_client_release(ctx: &Ctx, quien: &Address, task_id: &String) {
    ctx.env.mock_auths(&[MockAuth {
        address: quien,
        invoke: &MockAuthInvoke {
            contract: &ctx.contract_id,
            fn_name: "client_release",
            args: (task_id.clone(), &ctx.freelancer).into_val(&ctx.env),
            sub_invokes: &[],
        },
    }]);
}

// Saldos (cliente, contrato, freelancer, tercero).
fn saldos(ctx: &Ctx) -> (i128, i128, i128, i128) {
    (
        ctx.token.balance(&ctx.client),
        ctx.token.balance(&ctx.contract_id),
        ctx.token.balance(&ctx.freelancer),
        ctx.token.balance(&ctx.third),
    )
}

// ===========================================================================
// Tests obligatorios (CLAUDE.md)
// ===========================================================================

// 1. Happy path: deposit + release con saldos finales correctos.
#[test]
fn test_flujo_feliz_saldos_finales() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "tarea-1");

    // Tras el depósito, el dinero está en el contrato.
    assert_eq!(saldos(&ctx), (MINT - AMOUNT, AMOUNT, 0, 7));
    let t = ctx.c.get_task(&id);
    assert_eq!(t.status, TaskStatus::Funded);
    assert_eq!(t.freelancer, None);
    assert_eq!(t.rules_hash, rules_hash(env));
    assert_eq!(t.deadline, START_TS + DEADLINE_SECS);

    ctx.c
        .release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));

    // Tras el release: cliente -10, contrato 0, freelancer +10.
    assert_eq!(saldos(&ctx), (MINT - AMOUNT, 0, AMOUNT, 7));
    let t = ctx.c.get_task(&id);
    assert_eq!(t.status, TaskStatus::Released);
    assert_eq!(t.freelancer, Some(ctx.freelancer.clone()));
}

// 2. Un segundo release falla con NotFunded y no mueve fondos.
#[test]
fn test_doble_release_falla_sin_mover_fondos() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "tarea-1");
    ctx.c
        .release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    let antes = saldos(&ctx);

    let res = ctx
        .c
        .try_release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    assert_eq!(res, Err(Ok(Error::NotFunded)));

    // Tampoco a otra dirección.
    let res = ctx
        .c
        .try_release(&id, &ctx.third, &code_hash(env), &verdict_hash(env));
    assert_eq!(res, Err(Ok(Error::NotFunded)));

    assert_eq!(saldos(&ctx), antes);
}

// 3. release firmado por un árbitro falso falla (sin mock_all_auths).
#[test]
fn test_release_arbitro_falso_falla() {
    let ctx = setup(Modo::Estricto);
    let env = &ctx.env;
    let id = deposit(&ctx, "tarea-1");
    let antes = saldos(&ctx);

    // El "árbitro falso" (el tercero) firma el release: debe fallar por auth.
    mock_release(&ctx, &ctx.third, &id);
    let res = ctx
        .c
        .try_release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    assert!(res.is_err());
    // No es un error del contrato: es un fallo de autorización del host.
    assert!(matches!(res, Err(Err(_))));

    // Tampoco lo puede firmar el propio freelancer.
    mock_release(&ctx, &ctx.freelancer, &id);
    let res = ctx
        .c
        .try_release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    assert!(res.is_err());

    // Nada se movió y la tarea sigue en Funded.
    assert_eq!(saldos(&ctx), antes);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Funded);

    // Control: con la firma del árbitro verdadero sí funciona.
    mock_release(&ctx, &ctx.arbiter, &id);
    ctx.c
        .release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    assert_eq!(saldos(&ctx), (MINT - AMOUNT, 0, AMOUNT, 7));
}

// 4. timeout_refund antes del plazo falla (moviendo el tiempo del ledger).
#[test]
fn test_timeout_refund_antes_del_plazo_falla() {
    let ctx = setup(Modo::Libre);
    let id = deposit(&ctx, "tarea-1");
    let antes = saldos(&ctx);

    // Justo al depositar.
    assert_eq!(
        ctx.c.try_timeout_refund(&id),
        Err(Ok(Error::DeadlineNotReached))
    );

    // Un segundo antes del plazo.
    ctx.env
        .ledger()
        .set_timestamp(START_TS + DEADLINE_SECS - 1);
    assert_eq!(
        ctx.c.try_timeout_refund(&id),
        Err(Ok(Error::DeadlineNotReached))
    );
    assert_eq!(saldos(&ctx), antes);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Funded);
}

// 5. timeout_refund disparado por un tercero (sin firma de nadie) devuelve el
//    dinero al cliente; el saldo del tercero no cambia.
#[test]
fn test_timeout_refund_por_tercero_devuelve_al_cliente() {
    let ctx = setup(Modo::Estricto);
    let id = deposit(&ctx, "tarea-1");

    // Exactamente en el plazo (timestamp >= plazo).
    ctx.env.ledger().set_timestamp(START_TS + DEADLINE_SECS);

    // Sin ninguna firma de prueba: modo estricto con lista vacía.
    ctx.env.set_auths(&[]);
    ctx.c.timeout_refund(&id);

    // No se pidió ninguna firma.
    assert_eq!(ctx.env.auths(), std::vec![]);

    // El cliente recupera todo, el contrato queda en 0, el tercero igual.
    assert_eq!(saldos(&ctx), (MINT, 0, 0, 7));
    let t = ctx.c.get_task(&id);
    assert_eq!(t.status, TaskStatus::Refunded);
    assert_eq!(t.freelancer, None);
}

// 6. timeout_refund después de release falla, y viceversa.
#[test]
fn test_timeout_refund_y_release_son_excluyentes() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;

    // Tarea A: release y luego, ya vencido el plazo, timeout_refund.
    let a = deposit(&ctx, "tarea-a");
    ctx.c
        .release(&a, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    env.ledger().set_timestamp(START_TS + DEADLINE_SECS + 1);
    let antes = saldos(&ctx);
    assert_eq!(ctx.c.try_timeout_refund(&a), Err(Ok(Error::NotFunded)));
    assert_eq!(saldos(&ctx), antes);

    // Tarea B: timeout_refund y luego release / client_release.
    let b = deposit(&ctx, "tarea-b");
    env.ledger()
        .set_timestamp(START_TS + 2 * DEADLINE_SECS + 10);
    ctx.c.timeout_refund(&b);
    let antes = saldos(&ctx);
    assert_eq!(
        ctx.c
            .try_release(&b, &ctx.freelancer, &code_hash(env), &verdict_hash(env)),
        Err(Ok(Error::NotFunded))
    );
    assert_eq!(
        ctx.c.try_client_release(&b, &ctx.freelancer),
        Err(Ok(Error::NotFunded))
    );
    assert_eq!(ctx.c.try_timeout_refund(&b), Err(Ok(Error::NotFunded)));
    assert_eq!(saldos(&ctx), antes);

    // Resultado final: A pagada al freelancer, B devuelta al cliente.
    assert_eq!(saldos(&ctx), (MINT - AMOUNT, 0, AMOUNT, 7));
}

// 7. deposit con task_id repetido falla y no cobra dos veces.
#[test]
fn test_deposit_task_id_repetido_falla() {
    let ctx = setup(Modo::Libre);
    let id = deposit(&ctx, "tarea-1");
    let antes = saldos(&ctx);

    let res = ctx.c.try_deposit(
        &ctx.client,
        &id,
        &AMOUNT,
        &DEADLINE_SECS,
        &rules_hash(&ctx.env),
    );
    assert_eq!(res, Err(Ok(Error::AlreadyExists)));
    assert_eq!(saldos(&ctx), antes);

    // Tampoco después de cerrar la tarea (no se reutilizan identificadores).
    ctx.env.ledger().set_timestamp(START_TS + DEADLINE_SECS);
    ctx.c.timeout_refund(&id);
    let res = ctx.c.try_deposit(
        &ctx.client,
        &id,
        &AMOUNT,
        &DEADLINE_SECS,
        &rules_hash(&ctx.env),
    );
    assert_eq!(res, Err(Ok(Error::AlreadyExists)));
}

// 8. client_release firmado por alguien que no es el cliente falla.
#[test]
fn test_client_release_no_cliente_falla() {
    let ctx = setup(Modo::Estricto);
    let id = deposit(&ctx, "tarea-1");
    let antes = saldos(&ctx);

    // Un tercero intenta aprobar manualmente.
    mock_client_release(&ctx, &ctx.third, &id);
    assert!(ctx.c.try_client_release(&id, &ctx.freelancer).is_err());

    // El freelancer intenta aprobarse a sí mismo.
    mock_client_release(&ctx, &ctx.freelancer, &id);
    assert!(ctx.c.try_client_release(&id, &ctx.freelancer).is_err());

    // El árbitro tampoco puede usar la aprobación manual del cliente.
    mock_client_release(&ctx, &ctx.arbiter, &id);
    assert!(ctx.c.try_client_release(&id, &ctx.freelancer).is_err());

    assert_eq!(saldos(&ctx), antes);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Funded);

    // Control: el cliente verdadero sí puede.
    mock_client_release(&ctx, &ctx.client, &id);
    ctx.c.client_release(&id, &ctx.freelancer);
    assert_eq!(saldos(&ctx), (MINT - AMOUNT, 0, AMOUNT, 7));
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Released);
}

// ===========================================================================
// Regla del plazo en release (revisión de fase 0)
// ===========================================================================

// release exactamente en el plazo falla con DeadlinePassed y no mueve fondos.
#[test]
fn test_release_en_el_plazo_falla() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "tarea-1");
    let antes = saldos(&ctx);

    env.ledger().set_timestamp(START_TS + DEADLINE_SECS);
    assert_eq!(
        ctx.c
            .try_release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env)),
        Err(Ok(Error::DeadlinePassed))
    );

    // Después del plazo, también falla.
    env.ledger().set_timestamp(START_TS + DEADLINE_SECS + 1);
    assert_eq!(
        ctx.c
            .try_release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env)),
        Err(Ok(Error::DeadlinePassed))
    );

    assert_eq!(saldos(&ctx), antes);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Funded);

    // Tras el plazo el árbitro ya no puede pagar; el reembolso sí funciona.
    ctx.c.timeout_refund(&id);
    assert_eq!(saldos(&ctx), (MINT, 0, 0, 7));
}

// release un segundo antes del plazo funciona.
#[test]
fn test_release_un_segundo_antes_del_plazo_funciona() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "tarea-1");

    env.ledger().set_timestamp(START_TS + DEADLINE_SECS - 1);
    ctx.c
        .release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    assert_eq!(saldos(&ctx), (MINT - AMOUNT, 0, AMOUNT, 7));
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Released);
}

// client_release después del plazo funciona (el cliente renuncia al reembolso).
#[test]
fn test_client_release_despues_del_plazo_funciona() {
    let ctx = setup(Modo::Estricto);
    let id = deposit(&ctx, "tarea-1");

    ctx.env
        .ledger()
        .set_timestamp(START_TS + DEADLINE_SECS + 60);
    mock_client_release(&ctx, &ctx.client, &id);
    ctx.c.client_release(&id, &ctx.freelancer);

    assert_eq!(saldos(&ctx), (MINT - AMOUNT, 0, AMOUNT, 7));
    let t = ctx.c.get_task(&id);
    assert_eq!(t.status, TaskStatus::Released);
    assert_eq!(t.freelancer, Some(ctx.freelancer.clone()));

    // Y ya no se puede reembolsar.
    assert_eq!(ctx.c.try_timeout_refund(&id), Err(Ok(Error::NotFunded)));
}

// ===========================================================================
// Tests adicionales
// ===========================================================================

// initialize solo una vez.
#[test]
fn test_initialize_dos_veces_falla() {
    let ctx = setup(Modo::Libre);
    let res = ctx.c.try_initialize(&ctx.third, &ctx.token.address);
    assert_eq!(res, Err(Ok(Error::AlreadyInitialized)));
    let cfg = ctx.c.get_config();
    assert_eq!(cfg.arbiter, ctx.arbiter);
    assert_eq!(cfg.token, ctx.token.address);
}

// Sin initialize, deposit falla con NotInitialized.
#[test]
fn test_sin_initialize_falla() {
    let env = Env::default();
    env.mock_all_auths();
    let client = Address::generate(&env);
    let id = env.register(CumpleYCobraContract, ());
    let c = CumpleYCobraContractClient::new(&env, &id);
    let res = c.try_deposit(
        &client,
        &tid(&env, "x"),
        &AMOUNT,
        &DEADLINE_SECS,
        &rules_hash(&env),
    );
    assert_eq!(res, Err(Ok(Error::NotInitialized)));
    assert_eq!(c.try_get_config(), Err(Ok(Error::NotInitialized)));
}

// Montos de cero o negativos se rechazan.
#[test]
fn test_deposit_monto_invalido() {
    let ctx = setup(Modo::Libre);
    for amt in [0i128, -1, -AMOUNT] {
        let res = ctx.c.try_deposit(
            &ctx.client,
            &tid(&ctx.env, "tarea-1"),
            &amt,
            &DEADLINE_SECS,
            &rules_hash(&ctx.env),
        );
        assert_eq!(res, Err(Ok(Error::InvalidAmount)));
    }
    assert_eq!(saldos(&ctx), (MINT, 0, 0, 7));
}

// Plazo que desborda u64 (checked_add) o plazo de 0 segundos: InvalidDeadline.
#[test]
fn test_deposit_plazo_invalido() {
    let ctx = setup(Modo::Libre);

    let res = ctx.c.try_deposit(
        &ctx.client,
        &tid(&ctx.env, "tarea-1"),
        &AMOUNT,
        &0u64,
        &rules_hash(&ctx.env),
    );
    assert_eq!(res, Err(Ok(Error::InvalidDeadline)));

    let res = ctx.c.try_deposit(
        &ctx.client,
        &tid(&ctx.env, "tarea-1"),
        &AMOUNT,
        &(u64::MAX - START_TS + 1),
        &rules_hash(&ctx.env),
    );
    assert_eq!(res, Err(Ok(Error::InvalidDeadline)));

    // El límite exacto (sin desbordar) sí se acepta.
    ctx.c.deposit(
        &ctx.client,
        &tid(&ctx.env, "tarea-1"),
        &AMOUNT,
        &(u64::MAX - START_TS),
        &rules_hash(&ctx.env),
    );
    assert_eq!(ctx.c.get_task(&tid(&ctx.env, "tarea-1")).deadline, u64::MAX);
}

// Tareas que no existen: NotFound.
#[test]
fn test_tarea_inexistente() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = tid(env, "no-existe");
    assert_eq!(ctx.c.try_get_task(&id), Err(Ok(Error::NotFound)));
    assert_eq!(
        ctx.c
            .try_release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env)),
        Err(Ok(Error::NotFound))
    );
    assert_eq!(
        ctx.c.try_client_release(&id, &ctx.freelancer),
        Err(Ok(Error::NotFound))
    );
    assert_eq!(ctx.c.try_timeout_refund(&id), Err(Ok(Error::NotFound)));
}

// El evento de release lleva task_id (tópico), code_hash y verdict_hash.
#[test]
fn test_evento_release_con_hashes() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "tarea-1");
    ctx.c
        .release(&id, &ctx.freelancer, &code_hash(env), &verdict_hash(env));

    let esperado = ReleaseEvent {
        task_id: id.clone(),
        freelancer: ctx.freelancer.clone(),
        amount: AMOUNT,
        code_hash: code_hash(env),
        verdict_hash: verdict_hash(env),
    }
    .to_xdr(env, &ctx.contract_id);

    let eventos = env.events().all().filter_by_contract(&ctx.contract_id);
    assert!(eventos.events().contains(&esperado));
}

// Cada escritura deja extendido el TTL de la tarea y de la instancia.
#[test]
fn test_ttl_extendido_en_tarea_e_instancia() {
    let ctx = setup(Modo::Libre);
    let id = deposit(&ctx, "tarea-1");
    let env = &ctx.env;
    env.as_contract(&ctx.contract_id, || {
        assert_eq!(env.storage().instance().get_ttl(), TTL_EXTEND_TO);
        assert_eq!(
            env.storage().persistent().get_ttl(&DataKey::Task(id.clone())),
            TTL_EXTEND_TO
        );
    });
}
