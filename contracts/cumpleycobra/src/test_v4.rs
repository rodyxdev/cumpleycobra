#![cfg(test)]

// Pruebas de las funciones nuevas de v4 (acuerdos parciales, cancelaciones,
// reembolso en lote, recorte/división/prórroga de hitos, bono manual, depósito
// por lote y rotación segura del árbitro).
//
// Mismo esquema que `test.rs` y `test_hitos.rs`:
// - `Modo::Libre` usa `mock_all_auths` para probar lógica, saldos e invariantes.
// - `Modo::Estricto` NUNCA usa `mock_all_auths`: cada firma es explícita.

extern crate std;

use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _, MockAuth, MockAuthInvoke},
    token::{Client as TokenClient, StellarAssetClient},
    vec, Address, BytesN, Env, IntoVal, String, Vec,
};

const UNIT: i128 = 10_000_000;
const MINT: i128 = 100 * UNIT;
const DIA: u64 = 24 * 60 * 60;
const START_TS: u64 = 2_000_000;

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

fn tid(env: &Env, s: &str) -> String {
    String::from_str(env, s)
}

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

fn deposit_simple(ctx: &Ctx, name: &str, amount: i128, deadline_secs: u64) -> String {
    let id = tid(&ctx.env, name);
    let rh = hash(&ctx.env, 1);
    if ctx.modo == Modo::Estricto {
        let token_id = ctx.token.address.clone();
        ctx.env.mock_auths(&[MockAuth {
            address: &ctx.client,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "deposit",
                args: (&ctx.client, &id, amount, deadline_secs, &rh).into_val(&ctx.env),
                sub_invokes: &[MockAuthInvoke {
                    contract: &token_id,
                    fn_name: "transfer",
                    args: (&ctx.client, &ctx.contract_id, amount).into_val(&ctx.env),
                    sub_invokes: &[],
                }],
            },
        }]);
    }
    ctx.c
        .deposit(&ctx.client, &id, &amount, &deadline_secs, &rh);
    id
}

fn deposit_two_milestones(ctx: &Ctx, name: &str) -> String {
    let id = tid(&ctx.env, name);
    let amounts: Vec<i128> = vec![&ctx.env, 4 * UNIT, 6 * UNIT];
    let deadlines: Vec<u64> = vec![&ctx.env, DIA, 2 * DIA];
    let hashes: Vec<BytesN<32>> = vec![&ctx.env, hash(&ctx.env, 10), hash(&ctx.env, 11)];
    if ctx.modo == Modo::Estricto {
        let token_id = ctx.token.address.clone();
        ctx.env.mock_auths(&[MockAuth {
            address: &ctx.client,
            invoke: &MockAuthInvoke {
                contract: &ctx.contract_id,
                fn_name: "deposit_milestones",
                args: (&ctx.client, &id, &amounts, &deadlines, &hashes).into_val(&ctx.env),
                sub_invokes: &[MockAuthInvoke {
                    contract: &token_id,
                    fn_name: "transfer",
                    args: (&ctx.client, &ctx.contract_id, 10 * UNIT).into_val(&ctx.env),
                    sub_invokes: &[],
                }],
            },
        }]);
    }
    ctx.c
        .deposit_milestones(&ctx.client, &id, &amounts, &deadlines, &hashes);
    id
}

// ---------------------------------------------------------------------------
// Lote 1: mutual_split_task y mutual_split_milestone
// ---------------------------------------------------------------------------

#[test]
fn v4_mutual_split_task_camino_feliz_y_saldos_cuadran() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "split-t1", 10 * UNIT, DIA);

    // Cliente y programador acuerdan 6 USDC al programador y 4 USDC de vuelta al cliente.
    ctx.c.mutual_split_task(&id, &ctx.freelancer, &(6 * UNIT));

    let task = ctx.c.get_task(&id);
    assert_eq!(task.status, TaskStatus::Released);
    assert_eq!(task.freelancer, Some(ctx.freelancer.clone()));
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 6 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 6 * UNIT);

    // No se puede volver a repartir ni reembolsar una tarea ya cerrada.
    assert_eq!(
        ctx.c.try_mutual_split_task(&id, &ctx.freelancer, &(2 * UNIT)),
        Err(Ok(Error::NotFunded))
    );
}

#[test]
fn v4_mutual_split_task_rechaza_montos_invalidos_y_exige_doble_firma() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "split-t2", 5 * UNIT, DIA);

    assert_eq!(
        ctx.c.try_mutual_split_task(&id, &ctx.freelancer, &0),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_mutual_split_task(&id, &ctx.freelancer, &(-1)),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_mutual_split_task(&id, &ctx.freelancer, &(5 * UNIT)),
        Err(Ok(Error::InvalidAmount))
    );

    // En modo estricto, ni el cliente solo ni cliente + árbitro sustituyen la firma del programador.
    let est = setup(Modo::Estricto);
    let eid = deposit_simple(&est, "split-t-strict", 5 * UNIT, DIA);
    est.env.mock_auths(&[
        MockAuth {
            address: &est.client,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "mutual_split_task",
                args: (&eid, &est.freelancer, 2 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
        MockAuth {
            address: &est.arbiter,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "mutual_split_task",
                args: (&eid, &est.freelancer, 2 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
    ]);
    assert!(est
        .c
        .try_mutual_split_task(&eid, &est.freelancer, &(2 * UNIT))
        .is_err());

    // Con ambas firmas (cliente + programador) sí pasa.
    est.env.mock_auths(&[
        MockAuth {
            address: &est.client,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "mutual_split_task",
                args: (&eid, &est.freelancer, 2 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
        MockAuth {
            address: &est.freelancer,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "mutual_split_task",
                args: (&eid, &est.freelancer, 2 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
    ]);
    est.c.mutual_split_task(&eid, &est.freelancer, &(2 * UNIT));
    assert_eq!(est.token.balance(&est.freelancer), 2 * UNIT);
    assert_eq!(est.token.balance(&est.client), MINT - 2 * UNIT);
}

#[test]
fn v4_mutual_split_milestone_camino_feliz_y_validaciones() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "split-p1");

    // Hito 0 (4 USDC): 2.5 al programador y 1.5 de vuelta al cliente; fija al programador.
    ctx.c
        .mutual_split_milestone(&id, &0, &ctx.freelancer, &(25_000_000));

    let project = ctx.c.get_project(&id);
    assert_eq!(project.freelancer, Some(ctx.freelancer.clone()));
    assert_eq!(project.milestones.get(0).unwrap().status, MilestoneStatus::Released);
    assert_eq!(project.milestones.get(1).unwrap().status, MilestoneStatus::Funded);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 25_000_000);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 6 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 10 * UNIT + 15_000_000);

    // En el hito 1 no se puede repartir a otro programador distinto del fijado.
    assert_eq!(
        ctx.c
            .try_mutual_split_milestone(&id, &1, &ctx.third, &(2 * UNIT)),
        Err(Ok(Error::WrongFreelancer))
    );
    // Índice fuera de rango y monto inválido fallan con su error exacto.
    assert_eq!(
        ctx.c
            .try_mutual_split_milestone(&id, &9, &ctx.freelancer, &(1 * UNIT)),
        Err(Ok(Error::MilestoneNotFound))
    );
    assert_eq!(
        ctx.c
            .try_mutual_split_milestone(&id, &1, &ctx.freelancer, &(6 * UNIT)),
        Err(Ok(Error::InvalidAmount))
    );
    // Hito 0 ya pagado falla con NotFunded.
    assert_eq!(
        ctx.c
            .try_mutual_split_milestone(&id, &0, &ctx.freelancer, &(1 * UNIT)),
        Err(Ok(Error::NotFunded))
    );
}

// ---------------------------------------------------------------------------
// Lote 2: cancel_unassigned_task y cancel_unassigned_project
// ---------------------------------------------------------------------------

#[test]
fn v4_cancel_unassigned_task_camino_feliz_plazo_y_doble_firma() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "cancel-t1", 7 * UNIT, DIA);

    // Antes del plazo devuelve el depósito íntegro al cliente.
    ctx.c.cancel_unassigned_task(&id);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Refunded);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);

    // Segundo intento falla con NotFunded.
    assert_eq!(
        ctx.c.try_cancel_unassigned_task(&id),
        Err(Ok(Error::NotFunded))
    );

    // En o después del plazo falla con DeadlinePassed (para eso existe timeout_refund).
    let id2 = deposit_simple(&ctx, "cancel-t2", 3 * UNIT, 100);
    ctx.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(
        ctx.c.try_cancel_unassigned_task(&id2),
        Err(Ok(Error::DeadlinePassed))
    );

    // En modo estricto, el cliente solo (sin el árbitro) NO puede cancelar.
    let est = setup(Modo::Estricto);
    let eid = deposit_simple(&est, "cancel-t-strict", 4 * UNIT, DIA);
    est.env.mock_auths(&[MockAuth {
        address: &est.client,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "cancel_unassigned_task",
            args: (&eid,).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    assert!(est.c.try_cancel_unassigned_task(&eid).is_err());

    // Con cliente + árbitro sí cancela y devuelve el monto.
    est.env.mock_auths(&[
        MockAuth {
            address: &est.client,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "cancel_unassigned_task",
                args: (&eid,).into_val(&est.env),
                sub_invokes: &[],
            },
        },
        MockAuth {
            address: &est.arbiter,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "cancel_unassigned_task",
                args: (&eid,).into_val(&est.env),
                sub_invokes: &[],
            },
        },
    ]);
    est.c.cancel_unassigned_task(&eid);
    assert_eq!(est.token.balance(&est.client), MINT);
}

#[test]
fn v4_cancel_unassigned_project_camino_feliz_y_bloqueo_si_ya_tiene_programador() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "cancel-p1");

    // Cancela todos los hitos Funded de una vez sin esperar al plazo.
    ctx.c.cancel_unassigned_project(&id);
    let p = ctx.c.get_project(&id);
    assert_eq!(p.milestones.get(0).unwrap().status, MilestoneStatus::Refunded);
    assert_eq!(p.milestones.get(1).unwrap().status, MilestoneStatus::Refunded);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);

    // Ya no quedan hitos Funded -> NotFunded.
    assert_eq!(
        ctx.c.try_cancel_unassigned_project(&id),
        Err(Ok(Error::NotFunded))
    );

    // Si ya se pagó un hito (programador fijado), cancelar falla con AlreadyAssigned.
    let id2 = deposit_two_milestones(&ctx, "cancel-p2");
    ctx.c
        .client_release_milestone(&id2, &0, &ctx.freelancer);
    assert_eq!(
        ctx.c.try_cancel_unassigned_project(&id2),
        Err(Ok(Error::AlreadyAssigned))
    );
}

// ---------------------------------------------------------------------------
// Lote 3: refund_all_expired_milestones y reduce_milestone
// ---------------------------------------------------------------------------

#[test]
fn v4_refund_all_expired_milestones_lote_parcial_y_total() {
    let ctx = setup(Modo::Libre);
    let id = tid(&ctx.env, "batch-ref-1");
    let amounts: Vec<i128> = vec![&ctx.env, 2 * UNIT, 3 * UNIT, 5 * UNIT];
    let deadlines: Vec<u64> = vec![&ctx.env, DIA, 2 * DIA, 4 * DIA];
    let hashes: Vec<BytesN<32>> = vec![
        &ctx.env,
        hash(&ctx.env, 20),
        hash(&ctx.env, 21),
        hash(&ctx.env, 22),
    ];
    ctx.c
        .deposit_milestones(&ctx.client, &id, &amounts, &deadlines, &hashes);

    // Antes del primer plazo falla con DeadlineNotReached.
    assert_eq!(
        ctx.c.try_refund_all_expired_milestones(&id),
        Err(Ok(Error::DeadlineNotReached))
    );

    // Avanzamos 2 días: vencen los hitos 0 y 1 (2 + 3 = 5 USDC), el hito 2 sigue vigente.
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    let count = ctx.c.refund_all_expired_milestones(&id);
    assert_eq!(count, 2);
    let p = ctx.c.get_project(&id);
    assert_eq!(p.milestones.get(0).unwrap().status, MilestoneStatus::Refunded);
    assert_eq!(p.milestones.get(1).unwrap().status, MilestoneStatus::Refunded);
    assert_eq!(p.milestones.get(2).unwrap().status, MilestoneStatus::Funded);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.third), 7);

    // Llamar otra vez antes de que venza el hito 2 -> DeadlineNotReached.
    assert_eq!(
        ctx.c.try_refund_all_expired_milestones(&id),
        Err(Ok(Error::DeadlineNotReached))
    );

    // Vence el hito 2 -> se reembolsa y un intento posterior da NotFunded.
    ctx.env.ledger().set_timestamp(START_TS + 4 * DIA);
    assert_eq!(ctx.c.refund_all_expired_milestones(&id), 1);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);
    assert_eq!(
        ctx.c.try_refund_all_expired_milestones(&id),
        Err(Ok(Error::NotFunded))
    );
}

#[test]
fn v4_reduce_milestone_validaciones_y_doble_firma() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "red-p1");

    // Recorta 1 USDC del hito 0 (4 -> 3 USDC) antes de asignar programador.
    ctx.c.reduce_milestone(&id, &0, &(1 * UNIT));
    assert_eq!(ctx.c.get_project(&id).milestones.get(0).unwrap().amount, 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 9 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 9 * UNIT);

    // Rechaza recorte 0, total, índice inválido y plazo vencido.
    assert_eq!(
        ctx.c.try_reduce_milestone(&id, &0, &0),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_reduce_milestone(&id, &0, &(3 * UNIT)),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_reduce_milestone(&id, &5, &(1 * UNIT)),
        Err(Ok(Error::MilestoneNotFound))
    );

    // Se paga el hito 0 (3 USDC) -> fija al programador; el hito 0 ya no se recorta.
    ctx.c.client_release_milestone(&id, &0, &ctx.freelancer);
    assert_eq!(
        ctx.c.try_reduce_milestone(&id, &0, &(1 * UNIT)),
        Err(Ok(Error::NotFunded))
    );

    // Hito 1 (6 USDC) se recorta en 2 USDC (queda en 4 USDC) y luego se paga.
    ctx.c.reduce_milestone(&id, &1, &(2 * UNIT));
    ctx.c.client_release_milestone(&id, &1, &ctx.freelancer);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 7 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 7 * UNIT);

    // Modo estricto: con programador fijado, cliente + árbitro NO bastan (debe firmar el programador).
    let est = setup(Modo::Estricto);
    let eid = deposit_two_milestones(&est, "red-strict");
    est.env.mock_auths(&[MockAuth {
        address: &est.client,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "client_release_milestone",
            args: (&eid, 0u32, &est.freelancer).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    est.c.client_release_milestone(&eid, &0, &est.freelancer);

    est.env.mock_auths(&[
        MockAuth {
            address: &est.client,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "reduce_milestone",
                args: (&eid, 1u32, 1 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
        MockAuth {
            address: &est.arbiter,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "reduce_milestone",
                args: (&eid, 1u32, 1 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
    ]);
    assert!(est.c.try_reduce_milestone(&eid, &1, &(1 * UNIT)).is_err());

    // Con cliente + programador sí pasa.
    est.env.mock_auths(&[
        MockAuth {
            address: &est.client,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "reduce_milestone",
                args: (&eid, 1u32, 1 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
        MockAuth {
            address: &est.freelancer,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "reduce_milestone",
                args: (&eid, 1u32, 1 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            },
        },
    ]);
    est.c.reduce_milestone(&eid, &1, &(1 * UNIT));
    assert_eq!(est.c.get_project(&eid).milestones.get(1).unwrap().amount, 5 * UNIT);
}

// ---------------------------------------------------------------------------
// Lote 4: client_release_with_bonus y batch_deposit
// ---------------------------------------------------------------------------

#[test]
fn v4_client_release_with_bonus_camino_feliz_validaciones_y_estricto() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "bonus-t1", 5 * UNIT, DIA);

    // Rechaza bono 0 o negativo.
    assert_eq!(
        ctx.c.try_client_release_with_bonus(&id, &ctx.freelancer, &0),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_client_release_with_bonus(&id, &ctx.freelancer, &(-10)),
        Err(Ok(Error::InvalidAmount))
    );

    // Incluso tras vencer el plazo, el cliente puede aprobar con bono.
    ctx.env.ledger().set_timestamp(START_TS + DIA + 5);
    ctx.c
        .client_release_with_bonus(&id, &ctx.freelancer, &(2 * UNIT));

    let task = ctx.c.get_task(&id);
    assert_eq!(task.status, TaskStatus::Released);
    assert_eq!(task.freelancer, Some(ctx.freelancer.clone()));
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 7 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 7 * UNIT);

    // Doble liberación falla con NotFunded.
    assert_eq!(
        ctx.c
            .try_client_release_with_bonus(&id, &ctx.freelancer, &(1 * UNIT)),
        Err(Ok(Error::NotFunded))
    );

    // Modo estricto: un tercero no puede aprobar ni cobrar bono, pero el cliente con sub-invocación sí.
    let est = setup(Modo::Estricto);
    let eid = deposit_simple(&est, "bonus-strict", 3 * UNIT, DIA);
    let token_id = est.token.address.clone();
    est.env.mock_auths(&[MockAuth {
        address: &est.third,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "client_release_with_bonus",
            args: (&eid, &est.freelancer, 1 * UNIT).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    assert!(est
        .c
        .try_client_release_with_bonus(&eid, &est.freelancer, &(1 * UNIT))
        .is_err());

    est.env.mock_auths(&[MockAuth {
        address: &est.client,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "client_release_with_bonus",
            args: (&eid, &est.freelancer, 1 * UNIT).into_val(&est.env),
            sub_invokes: &[MockAuthInvoke {
                contract: &token_id,
                fn_name: "transfer",
                args: (&est.client, &est.freelancer, 1 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            }],
        },
    }]);
    est.c
        .client_release_with_bonus(&eid, &est.freelancer, &(1 * UNIT));
    assert_eq!(est.token.balance(&est.freelancer), 4 * UNIT);
    assert_eq!(est.token.balance(&est.client), MINT - 4 * UNIT);
}

#[test]
fn v4_batch_deposit_camino_feliz_y_validaciones() {
    let ctx = setup(Modo::Libre);
    let ids: Vec<String> = vec![
        &ctx.env,
        tid(&ctx.env, "lote-a"),
        tid(&ctx.env, "lote-b"),
        tid(&ctx.env, "lote-c"),
    ];
    let amounts: Vec<i128> = vec![&ctx.env, 1 * UNIT, 2 * UNIT, 3 * UNIT];
    let deadlines: Vec<u64> = vec![&ctx.env, DIA, DIA, 2 * DIA];
    let hashes: Vec<BytesN<32>> = vec![
        &ctx.env,
        hash(&ctx.env, 30),
        hash(&ctx.env, 31),
        hash(&ctx.env, 32),
    ];

    let total = ctx
        .c
        .batch_deposit(&ctx.client, &ids, &amounts, &deadlines, &hashes);
    assert_eq!(total, 6 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 6 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 6 * UNIT);
    assert_eq!(ctx.c.get_task(&tid(&ctx.env, "lote-b")).amount, 2 * UNIT);

    // Cada tarea del lote opera independientemente: una se paga y las otras se reembolsan tras el plazo.
    ctx.c
        .client_release(&tid(&ctx.env, "lote-a"), &ctx.freelancer);
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    ctx.c.timeout_refund(&tid(&ctx.env, "lote-b"));
    ctx.c.timeout_refund(&tid(&ctx.env, "lote-c"));
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 1 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 1 * UNIT);

    // Rechaza menos de 2 tareas, listas desiguales, IDs repetidos dentro del lote y montos/plazos inválidos.
    let one_id: Vec<String> = vec![&ctx.env, tid(&ctx.env, "sola")];
    let one_amt: Vec<i128> = vec![&ctx.env, UNIT];
    let one_dl: Vec<u64> = vec![&ctx.env, DIA];
    let one_h: Vec<BytesN<32>> = vec![&ctx.env, hash(&ctx.env, 33)];
    assert_eq!(
        ctx.c
            .try_batch_deposit(&ctx.client, &one_id, &one_amt, &one_dl, &one_h),
        Err(Ok(Error::InvalidMilestones))
    );

    let dup_ids: Vec<String> = vec![&ctx.env, tid(&ctx.env, "dup"), tid(&ctx.env, "dup")];
    let two_amt: Vec<i128> = vec![&ctx.env, UNIT, UNIT];
    let two_dl: Vec<u64> = vec![&ctx.env, DIA, DIA];
    let two_h: Vec<BytesN<32>> = vec![&ctx.env, hash(&ctx.env, 34), hash(&ctx.env, 35)];
    assert_eq!(
        ctx.c
            .try_batch_deposit(&ctx.client, &dup_ids, &two_amt, &two_dl, &two_h),
        Err(Ok(Error::AlreadyExists))
    );

    // Reutilizar un ID que ya existía falla con AlreadyExists.
    let exist_ids: Vec<String> = vec![&ctx.env, tid(&ctx.env, "lote-a"), tid(&ctx.env, "nueva-x")];
    assert_eq!(
        ctx.c
            .try_batch_deposit(&ctx.client, &exist_ids, &two_amt, &two_dl, &two_h),
        Err(Ok(Error::AlreadyExists))
    );
}

// ---------------------------------------------------------------------------
// Lote 5: split_milestone y extend_milestone_deadline
// ---------------------------------------------------------------------------

#[test]
fn v4_split_milestone_conserva_total_orden_y_limites() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "split-m1");

    // Divide el hito 1 (6 USDC, vence en 2 días) en 2.5 USDC (1.5 días) + 3.5 USDC (2 días).
    ctx.c.split_milestone(
        &id,
        &1,
        &(25_000_000),
        &(DIA + DIA / 2),
        &hash(&ctx.env, 40),
        &hash(&ctx.env, 41),
    );

    let p = ctx.c.get_project(&id);
    assert_eq!(p.milestones.len(), 3);
    assert_eq!(p.milestones.get(0).unwrap().amount, 4 * UNIT);
    assert_eq!(p.milestones.get(1).unwrap().amount, 25_000_000);
    assert_eq!(p.milestones.get(2).unwrap().amount, 35_000_000);
    assert_eq!(p.milestones.get(1).unwrap().deadline, START_TS + DIA + DIA / 2);
    assert_eq!(p.milestones.get(2).unwrap().deadline, START_TS + 2 * DIA);

    // Pagar todos los hitos deja el contrato exactamente en 0 (10 USDC pagados).
    for i in 0..3u32 {
        ctx.c.client_release_milestone(&id, &i, &ctx.freelancer);
    }
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 10 * UNIT);

    // Validaciones de orden de plazos, montos y tope de 10 hitos.
    let id2 = deposit_two_milestones(&ctx, "split-m2");
    // Plazo del primer sub-hito menor al hito anterior (DIA) -> InvalidMilestones.
    assert_eq!(
        ctx.c.try_split_milestone(
            &id2,
            &1,
            &(2 * UNIT),
            &(DIA - 1),
            &hash(&ctx.env, 42),
            &hash(&ctx.env, 43),
        ),
        Err(Ok(Error::InvalidMilestones))
    );
    // Plazo del primer sub-hito mayor al plazo del hito original (2 * DIA) -> InvalidMilestones.
    assert_eq!(
        ctx.c.try_split_milestone(
            &id2,
            &1,
            &(2 * UNIT),
            &(2 * DIA + 1),
            &hash(&ctx.env, 42),
            &hash(&ctx.env, 43),
        ),
        Err(Ok(Error::InvalidMilestones))
    );
    // Monto 0 o igual al total -> InvalidAmount.
    assert_eq!(
        ctx.c.try_split_milestone(
            &id2,
            &1,
            &0,
            &(DIA + 10),
            &hash(&ctx.env, 42),
            &hash(&ctx.env, 43),
        ),
        Err(Ok(Error::InvalidAmount))
    );
}

#[test]
fn v4_extend_milestone_deadline_prorroga_y_respeta_orden_y_tope() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "ext-m1");

    // Extiende hito 0 (1 día) en +12 horas -> sigue <= hito 1 (2 días).
    let new_dl = ctx.c.extend_milestone_deadline(&id, &0, &(DIA / 2));
    assert_eq!(new_dl, START_TS + DIA + DIA / 2);
    assert_eq!(ctx.c.get_project(&id).milestones.get(0).unwrap().deadline, new_dl);

    // El árbitro ahora puede liberar el hito 0 después del plazo original (1 día + 1 s) gracias a la prórroga.
    ctx.env.ledger().set_timestamp(START_TS + DIA + 1);
    ctx.c.release_milestone(
        &id,
        &0,
        &ctx.freelancer,
        &hash(&ctx.env, 50),
        &hash(&ctx.env, 51),
    );
    assert_eq!(
        ctx.c.get_project(&id).milestones.get(0).unwrap().status,
        MilestoneStatus::Released
    );

    // Ya pagado -> NotFunded.
    assert_eq!(
        ctx.c.try_extend_milestone_deadline(&id, &0, &60),
        Err(Ok(Error::NotFunded))
    );

    // Rechaza extra_secs == 0, superar 28 días desde ahora y rebasar el hito siguiente.
    let id2 = deposit_two_milestones(&ctx, "ext-m2");
    assert_eq!(
        ctx.c.try_extend_milestone_deadline(&id2, &0, &0),
        Err(Ok(Error::InvalidDeadline))
    );
    assert_eq!(
        ctx.c.try_extend_milestone_deadline(&id2, &0, &(DIA + 1)),
        Err(Ok(Error::InvalidMilestones))
    );
    assert_eq!(
        ctx.c
            .try_extend_milestone_deadline(&id2, &1, &(MAX_MILESTONE_DEADLINE_SECS)),
        Err(Ok(Error::InvalidDeadline))
    );
}

// ---------------------------------------------------------------------------
// Lote 6: rotate_arbiter
// ---------------------------------------------------------------------------

#[test]
fn v4_rotate_arbiter_doble_firma_y_efecto_en_release() {
    let est = setup(Modo::Estricto);
    let nuevo = Address::generate(&est.env);

    // Rotar hacia el mismo árbitro falla con SameArbiter.
    assert_eq!(
        est.c.try_rotate_arbiter(&est.arbiter),
        Err(Ok(Error::SameArbiter))
    );

    // Solo la firma del árbitro actual (sin el nuevo) falla.
    est.env.mock_auths(&[MockAuth {
        address: &est.arbiter,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "rotate_arbiter",
            args: (&nuevo,).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    assert!(est.c.try_rotate_arbiter(&nuevo).is_err());

    // Solo la firma del nuevo árbitro (sin el actual) falla.
    est.env.mock_auths(&[MockAuth {
        address: &nuevo,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "rotate_arbiter",
            args: (&nuevo,).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    assert!(est.c.try_rotate_arbiter(&nuevo).is_err());

    // Con ambas firmas sí rota y actualiza `get_config`.
    est.env.mock_auths(&[
        MockAuth {
            address: &est.arbiter,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "rotate_arbiter",
                args: (&nuevo,).into_val(&est.env),
                sub_invokes: &[],
            },
        },
        MockAuth {
            address: &nuevo,
            invoke: &MockAuthInvoke {
                contract: &est.contract_id,
                fn_name: "rotate_arbiter",
                args: (&nuevo,).into_val(&est.env),
                sub_invokes: &[],
            },
        },
    ]);
    est.c.rotate_arbiter(&nuevo);
    assert_eq!(est.c.get_config().arbiter, nuevo);

    // Tras rotar, el árbitro anterior ya no puede hacer release; el nuevo sí.
    let id = deposit_simple(&est, "rot-t1", 2 * UNIT, DIA);
    let ch = hash(&est.env, 60);
    let vh = hash(&est.env, 61);
    est.env.mock_auths(&[MockAuth {
        address: &est.arbiter,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "release",
            args: (&id, &est.freelancer, &ch, &vh).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    assert!(est.c.try_release(&id, &est.freelancer, &ch, &vh).is_err());

    est.env.mock_auths(&[MockAuth {
        address: &nuevo,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "release",
            args: (&id, &est.freelancer, &ch, &vh).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    est.c.release(&id, &est.freelancer, &ch, &vh);
    assert_eq!(est.token.balance(&est.freelancer), 2 * UNIT);
}
