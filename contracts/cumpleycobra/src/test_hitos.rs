#![cfg(test)]

// Pruebas del pago por hitos (v2, docs/hitos/diseno.md).
//
// Mismo esquema que `test.rs`:
// - `Modo::Libre` usa `mock_all_auths` para probar estados y saldos.
// - `Modo::Estricto` NUNCA llama `mock_all_auths`: cada firma es explícita.
//   Es el único modo válido para probar que alguien sin permiso es rechazado.

extern crate std;

use super::*;
use soroban_sdk::{
    testutils::{
        storage::{Instance as _, Persistent as _},
        Address as _, Events as _, Ledger as _, MockAuth, MockAuthInvoke,
    },
    token::{Client as TokenClient, StellarAssetClient},
    vec, Address, BytesN, Env, Event, IntoVal, String, Vec,
};

// 1 USDC = 10_000_000 unidades (7 decimales).
const UNIT: i128 = 10_000_000;
const MINT: i128 = 100 * UNIT;
// Proyecto de ejemplo: 3 hitos de 3, 5 y 2 USDC (total 10 USDC).
const H0: i128 = 3 * UNIT;
const H1: i128 = 5 * UNIT;
const H2: i128 = 2 * UNIT;
const TOTAL: i128 = H0 + H1 + H2;
// Plazos de los hitos, en segundos desde el depósito: 1, 2 y 3 días.
const DIA: u64 = 24 * 60 * 60;
const P0: u64 = DIA;
const P1: u64 = 2 * DIA;
const P2: u64 = 3 * DIA;
const START_TS: u64 = 1_000_000;

#[derive(PartialEq)]
enum Modo {
    Libre,
    Estricto,
}

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

fn hash(env: &Env, b: u8) -> BytesN<32> {
    BytesN::from_array(env, &[b; 32])
}
fn code_hash(env: &Env) -> BytesN<32> {
    hash(env, 2)
}
fn verdict_hash(env: &Env) -> BytesN<32> {
    hash(env, 3)
}
fn tid(env: &Env, s: &str) -> String {
    String::from_str(env, s)
}

// Prepara el entorno: token SAC, saldos iniciales y contrato inicializado.
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
    let sac = env.register_stellar_asset_contract_v2(token_admin.clone());
    let token_id = sac.address();
    let sac_admin = StellarAssetClient::new(&env, &token_id);

    // Al cliente 100 USDC y al tercero 7 unidades (para comprobar que no cambian).
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

// Listas del proyecto de ejemplo.
fn montos(env: &Env) -> Vec<i128> {
    vec![env, H0, H1, H2]
}
fn plazos(env: &Env) -> Vec<u64> {
    vec![env, P0, P1, P2]
}
fn hashes(env: &Env) -> Vec<BytesN<32>> {
    vec![env, hash(env, 10), hash(env, 11), hash(env, 12)]
}

// El cliente deposita el proyecto de 3 hitos. En modo estricto, su firma cubre
// exactamente `deposit_milestones` y la transferencia interna del total.
fn deposit(ctx: &Ctx, id: &str) -> String {
    let env = &ctx.env;
    let task_id = tid(env, id);
    if ctx.modo == Modo::Estricto {
        env.mock_auths(&[MockAuth {
            address: &ctx.client,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "deposit_milestones",
                args: (&ctx.client, task_id.clone(), montos(env), plazos(env), hashes(env))
                    .into_val(env),
                sub_invokes: &[MockAuthInvoke {
                    contract: &ctx.token.address,
                    fn_name: "transfer",
                    args: (&ctx.client, &ctx.contract_id, TOTAL).into_val(env),
                    sub_invokes: &[],
                }],
            },
        }]);
    }
    ctx.c.deposit_milestones(
        &ctx.client,
        &task_id,
        &montos(env),
        &plazos(env),
        &hashes(env),
    );
    task_id
}

fn release(ctx: &Ctx, id: &String, index: u32, to: &Address) {
    let env = &ctx.env;
    ctx.c
        .release_milestone(id, &index, to, &code_hash(env), &verdict_hash(env));
}

// Saldos (cliente, contrato, programador, tercero).
fn saldos(ctx: &Ctx) -> (i128, i128, i128, i128) {
    (
        ctx.token.balance(&ctx.client),
        ctx.token.balance(&ctx.contract_id),
        ctx.token.balance(&ctx.freelancer),
        ctx.token.balance(&ctx.third),
    )
}

fn estados(ctx: &Ctx, id: &String) -> std::vec::Vec<MilestoneStatus> {
    ctx.c
        .get_project(id)
        .milestones
        .iter()
        .map(|m| m.status)
        .collect()
}

// ===========================================================================
// Tests obligatorios (docs/hitos/diseno.md)
// ===========================================================================

// Camino feliz de 3 hitos: saldos finales correctos y el programador fijo.
#[test]
fn test_hitos_flujo_feliz_saldos_finales() {
    let ctx = setup(Modo::Libre);
    let id = deposit(&ctx, "proyecto-1");

    // Tras el depósito: el total está en el contrato y los 3 hitos en Funded.
    assert_eq!(saldos(&ctx), (MINT - TOTAL, TOTAL, 0, 7));
    let p = ctx.c.get_project(&id);
    assert_eq!(p.client, ctx.client);
    assert_eq!(p.freelancer, None);
    assert_eq!(p.milestones.len(), 3);
    let h1 = p.milestones.get(1).unwrap();
    assert_eq!(h1.amount, H1);
    assert_eq!(h1.deadline, START_TS + P1);
    assert_eq!(h1.rules_hash, hash(&ctx.env, 11));

    // Cada hito paga solo su parte.
    release(&ctx, &id, 0, &ctx.freelancer);
    assert_eq!(saldos(&ctx), (MINT - TOTAL, H1 + H2, H0, 7));
    assert_eq!(ctx.c.get_project(&id).freelancer, Some(ctx.freelancer.clone()));
    release(&ctx, &id, 1, &ctx.freelancer);
    release(&ctx, &id, 2, &ctx.freelancer);

    // Al final: cliente -10, contrato 0, programador +10.
    assert_eq!(saldos(&ctx), (MINT - TOTAL, 0, TOTAL, 7));
    assert_eq!(
        estados(&ctx, &id),
        std::vec![MilestoneStatus::Released, MilestoneStatus::Released, MilestoneStatus::Released]
    );
}

// Un hito pagado dos veces falla con NotFunded y no mueve fondos.
#[test]
fn test_hito_doble_pago_falla_sin_mover_fondos() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");
    release(&ctx, &id, 0, &ctx.freelancer);
    let antes = saldos(&ctx);

    let res = ctx.c.try_release_milestone(
        &id,
        &0,
        &ctx.freelancer,
        &code_hash(env),
        &verdict_hash(env),
    );
    assert_eq!(res, Err(Ok(Error::NotFunded)));
    assert_eq!(
        ctx.c.try_client_release_milestone(&id, &0, &ctx.freelancer),
        Err(Ok(Error::NotFunded))
    );
    assert_eq!(saldos(&ctx), antes);
}

// release_milestone firmado por un árbitro falso falla (sin mock_all_auths).
#[test]
fn test_hito_arbitro_falso_falla() {
    let ctx = setup(Modo::Estricto);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");
    let antes = saldos(&ctx);

    let firma = |quien: &Address| {
        env.mock_auths(&[MockAuth {
            address: quien,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "release_milestone",
                args: (id.clone(), 0u32, &ctx.freelancer, code_hash(env), verdict_hash(env))
                    .into_val(env),
                sub_invokes: &[],
            },
        }]);
    };

    // El tercero y el propio programador no pueden firmar como árbitro.
    for falso in [&ctx.third, &ctx.freelancer, &ctx.client] {
        firma(falso);
        let res = ctx.c.try_release_milestone(
            &id,
            &0,
            &ctx.freelancer,
            &code_hash(env),
            &verdict_hash(env),
        );
        // No es un error del contrato: es un fallo de autorización del host.
        assert!(matches!(res, Err(Err(_))));
    }
    assert_eq!(saldos(&ctx), antes);

    // Control: con la firma del árbitro verdadero sí funciona.
    firma(&ctx.arbiter);
    ctx.c
        .release_milestone(&id, &0, &ctx.freelancer, &code_hash(env), &verdict_hash(env));
    assert_eq!(saldos(&ctx), (MINT - TOTAL, H1 + H2, H0, 7));
}

// Ya fijado el programador, ningún hito le puede pagar a otra dirección.
#[test]
fn test_hito_a_otro_programador_falla() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");
    release(&ctx, &id, 0, &ctx.freelancer);
    let antes = saldos(&ctx);

    assert_eq!(
        ctx.c.try_release_milestone(&id, &1, &ctx.third, &code_hash(env), &verdict_hash(env)),
        Err(Ok(Error::WrongFreelancer))
    );
    assert_eq!(
        ctx.c.try_client_release_milestone(&id, &1, &ctx.third),
        Err(Ok(Error::WrongFreelancer))
    );
    assert_eq!(saldos(&ctx), antes);
    assert_eq!(estados(&ctx, &id)[1], MilestoneStatus::Funded);
}

// client_release_milestone firmado por alguien que no es el cliente falla.
#[test]
fn test_hito_aprobacion_manual_no_cliente_falla() {
    let ctx = setup(Modo::Estricto);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");
    let antes = saldos(&ctx);

    let firma = |quien: &Address| {
        env.mock_auths(&[MockAuth {
            address: quien,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "client_release_milestone",
                args: (id.clone(), 1u32, &ctx.freelancer).into_val(env),
                sub_invokes: &[],
            },
        }]);
    };

    for falso in [&ctx.third, &ctx.freelancer, &ctx.arbiter] {
        firma(falso);
        let res = ctx.c.try_client_release_milestone(&id, &1, &ctx.freelancer);
        assert!(matches!(res, Err(Err(_))));
    }
    assert_eq!(saldos(&ctx), antes);

    // Control: el cliente sí puede.
    firma(&ctx.client);
    ctx.c.client_release_milestone(&id, &1, &ctx.freelancer);
    assert_eq!(saldos(&ctx), (MINT - TOTAL, H0 + H2, H1, 7));
}

// Reembolso de un hito: antes de su plazo falla; justo en el plazo funciona,
// lo puede disparar un tercero y el dinero solo vuelve al cliente.
#[test]
fn test_hito_reembolso_por_plazo() {
    let ctx = setup(Modo::Libre);
    let id = deposit(&ctx, "proyecto-1");

    ctx.env.ledger().set_timestamp(START_TS + P0 - 1);
    assert_eq!(
        ctx.c.try_timeout_refund_milestone(&id, &0),
        Err(Ok(Error::DeadlineNotReached))
    );

    // Justo en el plazo del hito 0 (el 1 y el 2 todavía no vencen).
    ctx.env.ledger().set_timestamp(START_TS + P0);
    ctx.c.timeout_refund_milestone(&id, &0);
    assert_eq!(saldos(&ctx), (MINT - TOTAL + H0, H1 + H2, 0, 7));
    assert_eq!(
        ctx.c.try_timeout_refund_milestone(&id, &1),
        Err(Ok(Error::DeadlineNotReached))
    );
    assert_eq!(
        estados(&ctx, &id),
        std::vec![MilestoneStatus::Refunded, MilestoneStatus::Funded, MilestoneStatus::Funded]
    );
}

// Un hito pagado no se reembolsa, y uno reembolsado no se paga.
#[test]
fn test_hito_pago_y_reembolso_son_excluyentes() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");
    release(&ctx, &id, 0, &ctx.freelancer);

    env.ledger().set_timestamp(START_TS + P1);
    assert_eq!(ctx.c.try_timeout_refund_milestone(&id, &0), Err(Ok(Error::NotFunded)));
    ctx.c.timeout_refund_milestone(&id, &1);
    let antes = saldos(&ctx);
    assert_eq!(
        ctx.c.try_client_release_milestone(&id, &1, &ctx.freelancer),
        Err(Ok(Error::NotFunded))
    );
    assert_eq!(saldos(&ctx), antes);
}

// Proyecto mixto: hito 0 pagado por el árbitro, hito 1 aprobado a mano DESPUÉS
// de su plazo y hito 2 reembolsado. Los saldos cuadran con el total depositado.
#[test]
fn test_hitos_mixtos_cuadran_con_el_total() {
    let ctx = setup(Modo::Libre);
    let id = deposit(&ctx, "proyecto-1");
    release(&ctx, &id, 0, &ctx.freelancer);

    ctx.env.ledger().set_timestamp(START_TS + P2);
    ctx.c.client_release_milestone(&id, &1, &ctx.freelancer);
    ctx.c.timeout_refund_milestone(&id, &2);

    let (cliente, contrato, programador, tercero) = saldos(&ctx);
    assert_eq!(contrato, 0);
    assert_eq!(programador, H0 + H1);
    assert_eq!(cliente, MINT - TOTAL + H2);
    assert_eq!(tercero, 7);
    assert_eq!(cliente + programador, MINT);
    assert_eq!(
        estados(&ctx, &id),
        std::vec![MilestoneStatus::Released, MilestoneStatus::Released, MilestoneStatus::Refunded]
    );
}

// release_milestone exactamente en el plazo del hito falla; un segundo antes funciona.
#[test]
fn test_hito_release_en_el_plazo() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");

    env.ledger().set_timestamp(START_TS + P0);
    assert_eq!(
        ctx.c.try_release_milestone(&id, &0, &ctx.freelancer, &code_hash(env), &verdict_hash(env)),
        Err(Ok(Error::DeadlinePassed))
    );
    assert_eq!(saldos(&ctx), (MINT - TOTAL, TOTAL, 0, 7));

    // El hito 1 vence después: un segundo antes de su plazo todavía se paga.
    env.ledger().set_timestamp(START_TS + P1 - 1);
    release(&ctx, &id, 1, &ctx.freelancer);
    assert_eq!(saldos(&ctx), (MINT - TOTAL, H0 + H2, H1, 7));
}

// deposit_milestones rechaza listas mal formadas, montos y plazos inválidos.
#[test]
fn test_hitos_deposito_invalido() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = tid(env, "proyecto-x");
    let h = |n: u32| -> Vec<BytesN<32>> {
        let mut v = Vec::new(env);
        for _ in 0..n {
            v.push_back(hash(env, 9));
        }
        v
    };
    let rep = |n: u32, monto: i128, plazo: u64| -> (Vec<i128>, Vec<u64>) {
        let (mut m, mut p) = (Vec::new(env), Vec::new(env));
        for _ in 0..n {
            m.push_back(monto);
            p.push_back(plazo);
        }
        (m, p)
    };
    let intenta = |m: &Vec<i128>, p: &Vec<u64>, r: &Vec<BytesN<32>>| {
        ctx.c.try_deposit_milestones(&ctx.client, &id, m, p, r)
    };

    // Listas de distinto largo.
    assert_eq!(
        intenta(&vec![env, H0, H1], &vec![env, P0, P1, P2], &h(2)),
        Err(Ok(Error::InvalidMilestones))
    );
    assert_eq!(
        intenta(&vec![env, H0, H1], &vec![env, P0, P1], &h(3)),
        Err(Ok(Error::InvalidMilestones))
    );
    // 1 hito (para eso está la tarea simple) y 11 hitos.
    let (m1, p1) = rep(1, H0, P0);
    assert_eq!(intenta(&m1, &p1, &h(1)), Err(Ok(Error::InvalidMilestones)));
    let (m11, p11) = rep(11, UNIT, P0);
    assert_eq!(intenta(&m11, &p11, &h(11)), Err(Ok(Error::InvalidMilestones)));
    // Un monto 0 o negativo.
    assert_eq!(
        intenta(&vec![env, H0, 0], &vec![env, P0, P1], &h(2)),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        intenta(&vec![env, H0, -1], &vec![env, P0, P1], &h(2)),
        Err(Ok(Error::InvalidAmount))
    );
    // Plazos que bajan, plazo 0 y plazo de más de 28 días.
    assert_eq!(
        intenta(&vec![env, H0, H1], &vec![env, P1, P0], &h(2)),
        Err(Ok(Error::InvalidMilestones))
    );
    assert_eq!(
        intenta(&vec![env, H0, H1], &vec![env, 0, P1], &h(2)),
        Err(Ok(Error::InvalidDeadline))
    );
    assert_eq!(
        intenta(&vec![env, H0, H1], &vec![env, P0, 28 * DIA + 1], &h(2)),
        Err(Ok(Error::InvalidDeadline))
    );
    // Con 10 hitos y 28 días exactos sí se acepta.
    let (m10, p10) = rep(10, UNIT, 28 * DIA);
    ctx.c.deposit_milestones(&ctx.client, &id, &m10, &p10, &h(10));
    assert_eq!(ctx.token.balance(&ctx.contract_id), 10 * UNIT);
}

// Un task_id no se repite: ni entre proyectos ni entre proyecto y tarea simple.
#[test]
fn test_hitos_task_id_repetido_falla() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "repetido");

    assert_eq!(
        ctx.c
            .try_deposit_milestones(&ctx.client, &id, &montos(env), &plazos(env), &hashes(env)),
        Err(Ok(Error::AlreadyExists))
    );
    // Una tarea simple con el id de un proyecto.
    assert_eq!(
        ctx.c.try_deposit(&ctx.client, &id, &UNIT, &600, &hash(env, 1)),
        Err(Ok(Error::AlreadyExists))
    );
    // Un proyecto con el id de una tarea simple.
    let tarea = tid(env, "tarea-simple");
    ctx.c.deposit(&ctx.client, &tarea, &UNIT, &600, &hash(env, 1));
    assert_eq!(
        ctx.c
            .try_deposit_milestones(&ctx.client, &tarea, &montos(env), &plazos(env), &hashes(env)),
        Err(Ok(Error::AlreadyExists))
    );
}

// Índice fuera de rango y proyecto inexistente.
#[test]
fn test_hito_inexistente() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");
    assert_eq!(
        ctx.c.try_release_milestone(&id, &3, &ctx.freelancer, &code_hash(env), &verdict_hash(env)),
        Err(Ok(Error::MilestoneNotFound))
    );
    assert_eq!(
        ctx.c.try_client_release_milestone(&id, &7, &ctx.freelancer),
        Err(Ok(Error::MilestoneNotFound))
    );
    assert_eq!(ctx.c.try_timeout_refund_milestone(&id, &3), Err(Ok(Error::MilestoneNotFound)));

    let otro = tid(env, "no-existe");
    assert_eq!(ctx.c.try_get_project(&otro), Err(Ok(Error::NotFound)));
    assert_eq!(ctx.c.try_timeout_refund_milestone(&otro, &0), Err(Ok(Error::NotFound)));
}

// El evento del pago de un hito lleva el índice, el monto y los dos hashes.
#[test]
fn test_hito_evento_con_hashes() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-1");
    release(&ctx, &id, 1, &ctx.freelancer);

    let esperado = MilestoneReleaseEvent {
        task_id: id.clone(),
        index: 1,
        freelancer: ctx.freelancer.clone(),
        amount: H1,
        code_hash: code_hash(env),
        verdict_hash: verdict_hash(env),
    }
    .to_xdr(env, &ctx.contract_id);
    let eventos = env.events().all().filter_by_contract(&ctx.contract_id);
    assert!(eventos.events().contains(&esperado));
}

// Cada escritura deja extendido el TTL del proyecto y de la instancia.
#[test]
fn test_hitos_ttl_extendido() {
    let ctx = setup(Modo::Libre);
    let id = deposit(&ctx, "proyecto-1");
    let env = &ctx.env;
    env.as_contract(&ctx.contract_id, || {
        assert_eq!(env.storage().instance().get_ttl(), TTL_EXTEND_TO);
        assert_eq!(
            env.storage().persistent().get_ttl(&DataKey::Project(id.clone())),
            TTL_EXTEND_TO
        );
    });
}

// ===========================================================================
// Tests v3: add_milestone y top_up_milestone
// ===========================================================================

// Camino feliz v3: agregar un 4.º hito y aumentar el hito 1; saldos y eventos
// correctos; al pagar todos los hitos, el contrato queda en 0.
#[test]
fn test_v3_flujo_feliz_agregar_y_aumentar_hitos() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-v3");
    let h3 = 4 * UNIT;
    let p3 = 4 * DIA;
    let r3 = hash(env, 13);
    let aumento = 2 * UNIT;

    // Agregar el 4.º hito (índice 3) y comprobar su evento antes de otra llamada.
    ctx.c.add_milestone(&id, &h3, &p3, &r3);
    let evento_add = AddMilestoneEvent {
        task_id: id.clone(),
        index: 3,
        amount: h3,
        deadline: START_TS + p3,
    }
    .to_xdr(env, &ctx.contract_id);
    assert!(env
        .events()
        .all()
        .filter_by_contract(&ctx.contract_id)
        .events()
        .contains(&evento_add));

    assert_eq!(saldos(&ctx), (MINT - TOTAL - h3, TOTAL + h3, 0, 7));
    let p = ctx.c.get_project(&id);
    assert_eq!(p.milestones.len(), 4);
    let nuevo = p.milestones.get(3).unwrap();
    assert_eq!(nuevo.amount, h3);
    assert_eq!(nuevo.deadline, START_TS + p3);
    assert_eq!(nuevo.rules_hash, r3);
    assert_eq!(nuevo.status, MilestoneStatus::Funded);

    // Aumentar el hito 1 (+2 USDC) y comprobar su evento.
    ctx.c.top_up_milestone(&id, &1, &aumento);
    let evento_top_up = TopUpMilestoneEvent {
        task_id: id.clone(),
        index: 1,
        amount: aumento,
        new_amount: H1 + aumento,
    }
    .to_xdr(env, &ctx.contract_id);
    assert!(env
        .events()
        .all()
        .filter_by_contract(&ctx.contract_id)
        .events()
        .contains(&evento_top_up));

    let total_final = TOTAL + h3 + aumento;
    assert_eq!(saldos(&ctx), (MINT - total_final, total_final, 0, 7));
    assert_eq!(ctx.c.get_project(&id).milestones.get(1).unwrap().amount, H1 + aumento);

    // Pagar todos los hitos y comprobar que el contrato queda en 0.
    for i in 0..4u32 {
        release(&ctx, &id, i, &ctx.freelancer);
    }
    assert_eq!(saldos(&ctx), (MINT - total_final, 0, total_final, 7));
    assert_eq!(
        estados(&ctx, &id),
        std::vec![
            MilestoneStatus::Released,
            MilestoneStatus::Released,
            MilestoneStatus::Released,
            MilestoneStatus::Released,
        ]
    );
}

// add_milestone firmado por alguien que no es el cliente falla (sin mock_all_auths).
#[test]
fn test_v3_add_milestone_no_cliente_falla() {
    let ctx = setup(Modo::Estricto);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-v3");
    let antes = saldos(&ctx);
    let extra = 2 * UNIT;
    let p3 = 4 * DIA;
    let r3 = hash(env, 13);

    let firma = |quien: &Address| {
        env.mock_auths(&[MockAuth {
            address: quien,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "add_milestone",
                args: (id.clone(), extra, p3, r3.clone()).into_val(env),
                sub_invokes: &[MockAuthInvoke {
                    contract: &ctx.token.address,
                    fn_name: "transfer",
                    args: (quien, &ctx.contract_id, extra).into_val(env),
                    sub_invokes: &[],
                }],
            },
        }]);
    };

    for falso in [&ctx.third, &ctx.freelancer, &ctx.arbiter] {
        firma(falso);
        let res = ctx.c.try_add_milestone(&id, &extra, &p3, &r3);
        assert!(matches!(res, Err(Err(_))));
    }
    assert_eq!(saldos(&ctx), antes);
    assert_eq!(ctx.c.get_project(&id).milestones.len(), 3);

    // Control: el cliente del proyecto sí puede agregar el hito.
    firma(&ctx.client);
    ctx.c.add_milestone(&id, &extra, &p3, &r3);
    assert_eq!(saldos(&ctx), (MINT - TOTAL - extra, TOTAL + extra, 0, 7));
    assert_eq!(ctx.c.get_project(&id).milestones.len(), 4);
}

// top_up_milestone firmado por alguien que no es el cliente falla (sin mock_all_auths).
#[test]
fn test_v3_top_up_milestone_no_cliente_falla() {
    let ctx = setup(Modo::Estricto);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-v3");
    let antes = saldos(&ctx);
    let aumento = UNIT;

    let firma = |quien: &Address| {
        env.mock_auths(&[MockAuth {
            address: quien,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "top_up_milestone",
                args: (id.clone(), 1u32, aumento).into_val(env),
                sub_invokes: &[MockAuthInvoke {
                    contract: &ctx.token.address,
                    fn_name: "transfer",
                    args: (quien, &ctx.contract_id, aumento).into_val(env),
                    sub_invokes: &[],
                }],
            },
        }]);
    };

    for falso in [&ctx.third, &ctx.freelancer, &ctx.arbiter] {
        firma(falso);
        let res = ctx.c.try_top_up_milestone(&id, &1, &aumento);
        assert!(matches!(res, Err(Err(_))));
    }
    assert_eq!(saldos(&ctx), antes);
    assert_eq!(ctx.c.get_project(&id).milestones.get(1).unwrap().amount, H1);

    // Control: el cliente del proyecto sí puede aumentar el hito.
    firma(&ctx.client);
    ctx.c.top_up_milestone(&id, &1, &aumento);
    assert_eq!(saldos(&ctx), (MINT - TOTAL - aumento, TOTAL + aumento, 0, 7));
    assert_eq!(ctx.c.get_project(&id).milestones.get(1).unwrap().amount, H1 + aumento);
}

// Validaciones de add_milestone: proyecto inexistente, monto 0/negativo, plazo
// 0 o mayor a 28 días, plazo anterior al último hito y límite de 10 hitos.
#[test]
fn test_v3_add_milestone_validaciones() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-v3");
    let r = hash(env, 20);
    let antes = saldos(&ctx);

    // Proyecto que no existe.
    assert_eq!(
        ctx.c.try_add_milestone(&tid(env, "no-existe"), &UNIT, &P2, &r),
        Err(Ok(Error::NotFound))
    );
    // Monto 0 o negativo.
    assert_eq!(
        ctx.c.try_add_milestone(&id, &0, &P2, &r),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_add_milestone(&id, &-1, &P2, &r),
        Err(Ok(Error::InvalidAmount))
    );
    // Plazo 0 o mayor a 28 días.
    assert_eq!(
        ctx.c.try_add_milestone(&id, &UNIT, &0, &r),
        Err(Ok(Error::InvalidDeadline))
    );
    assert_eq!(
        ctx.c.try_add_milestone(&id, &UNIT, &(28 * DIA + 1), &r),
        Err(Ok(Error::InvalidDeadline))
    );
    // Plazo absoluto menor al del último hito (START_TS + P2).
    assert_eq!(
        ctx.c.try_add_milestone(&id, &UNIT, &(P2 - 1), &r),
        Err(Ok(Error::InvalidMilestones))
    );
    assert_eq!(saldos(&ctx), antes);

    // Plazo igual al del último hito sí se acepta.
    ctx.c.add_milestone(&id, &UNIT, &P2, &r);
    assert_eq!(ctx.c.get_project(&id).milestones.len(), 4);

    // En un proyecto que ya tiene 10 hitos, agregar el 11.º falla.
    let lleno = tid(env, "proyecto-lleno");
    let (mut m10, mut p10, mut h10) = (Vec::new(env), Vec::new(env), Vec::new(env));
    for _ in 0..MAX_MILESTONES {
        m10.push_back(UNIT);
        p10.push_back(DIA);
        h10.push_back(hash(env, 9));
    }
    ctx.c.deposit_milestones(&ctx.client, &lleno, &m10, &p10, &h10);
    let antes_lleno = saldos(&ctx);
    assert_eq!(
        ctx.c.try_add_milestone(&lleno, &UNIT, &(2 * DIA), &r),
        Err(Ok(Error::InvalidMilestones))
    );
    assert_eq!(saldos(&ctx), antes_lleno);
    assert_eq!(ctx.c.get_project(&lleno).milestones.len(), MAX_MILESTONES);
}

// Validaciones de top_up_milestone: proyecto o índice inexistente, monto
// inválido/desborde, hito pagado o reembolsado y plazo vencido.
#[test]
fn test_v3_top_up_milestone_validaciones() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-v3");

    // Proyecto inexistente e índice fuera de rango.
    assert_eq!(
        ctx.c.try_top_up_milestone(&tid(env, "no-existe"), &0, &UNIT),
        Err(Ok(Error::NotFound))
    );
    assert_eq!(
        ctx.c.try_top_up_milestone(&id, &3, &UNIT),
        Err(Ok(Error::MilestoneNotFound))
    );
    // Monto 0, negativo y desborde con checked_add.
    assert_eq!(
        ctx.c.try_top_up_milestone(&id, &0, &0),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_top_up_milestone(&id, &0, &-1),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_top_up_milestone(&id, &0, &i128::MAX),
        Err(Ok(Error::InvalidAmount))
    );

    // Hito pagado falla con NotFunded.
    release(&ctx, &id, 0, &ctx.freelancer);
    assert_eq!(
        ctx.c.try_top_up_milestone(&id, &0, &UNIT),
        Err(Ok(Error::NotFunded))
    );

    // Exactamente en el plazo del hito 1 falla con DeadlinePassed.
    env.ledger().set_timestamp(START_TS + P1);
    assert_eq!(
        ctx.c.try_top_up_milestone(&id, &1, &UNIT),
        Err(Ok(Error::DeadlinePassed))
    );

    // Tras reembolsar el hito 1, falla con NotFunded.
    ctx.c.timeout_refund_milestone(&id, &1);
    assert_eq!(
        ctx.c.try_top_up_milestone(&id, &1, &UNIT),
        Err(Ok(Error::NotFunded))
    );

    // Un segundo antes del plazo del hito 2 todavía se puede aumentar.
    env.ledger().set_timestamp(START_TS + P2 - 1);
    ctx.c.top_up_milestone(&id, &2, &UNIT);
    assert_eq!(ctx.c.get_project(&id).milestones.get(2).unwrap().amount, H2 + UNIT);
}

// Invariante contable con v3: depositado = pagado + reembolsado + pendiente,
// y TTL extendido tras add_milestone y top_up_milestone.
#[test]
fn test_v3_total_cuadra_y_ttl_extendido() {
    let ctx = setup(Modo::Libre);
    let env = &ctx.env;
    let id = deposit(&ctx, "proyecto-mixto-v3");
    let h3 = 4 * UNIT;
    let a1 = 2 * UNIT;
    let a2 = UNIT;

    // Agregar 4.º hito y aumentar hitos 1 y 2.
    ctx.c.add_milestone(&id, &h3, &(4 * DIA), &hash(env, 13));
    env.as_contract(&ctx.contract_id, || {
        assert_eq!(env.storage().instance().get_ttl(), TTL_EXTEND_TO);
        assert_eq!(
            env.storage().persistent().get_ttl(&DataKey::Project(id.clone())),
            TTL_EXTEND_TO
        );
    });

    ctx.c.top_up_milestone(&id, &1, &a1);
    ctx.c.top_up_milestone(&id, &2, &a2);
    env.as_contract(&ctx.contract_id, || {
        assert_eq!(env.storage().instance().get_ttl(), TTL_EXTEND_TO);
        assert_eq!(
            env.storage().persistent().get_ttl(&DataKey::Project(id.clone())),
            TTL_EXTEND_TO
        );
    });

    // Hito 0 pagado por el árbitro; hito 1 aprobado a mano después de su plazo
    // (con su aumento); hito 2 reembolsado (con su aumento); hito 3 pendiente.
    release(&ctx, &id, 0, &ctx.freelancer);
    env.ledger().set_timestamp(START_TS + P2);
    ctx.c.client_release_milestone(&id, &1, &ctx.freelancer);
    ctx.c.timeout_refund_milestone(&id, &2);

    let depositado = TOTAL + h3 + a1 + a2;
    let pagado = H0 + (H1 + a1);
    let reembolsado = H2 + a2;
    let pendiente = h3;
    assert_eq!(depositado, pagado + reembolsado + pendiente);

    let (cliente, contrato, programador, tercero) = saldos(&ctx);
    assert_eq!(contrato, pendiente);
    assert_eq!(programador, pagado);
    assert_eq!(cliente, MINT - depositado + reembolsado);
    assert_eq!(tercero, 7);
    assert_eq!(cliente + contrato + programador, MINT);
    assert_eq!(
        estados(&ctx, &id),
        std::vec![
            MilestoneStatus::Released,
            MilestoneStatus::Released,
            MilestoneStatus::Refunded,
            MilestoneStatus::Funded,
        ]
    );
}
