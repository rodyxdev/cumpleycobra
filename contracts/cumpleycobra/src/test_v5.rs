#![cfg(test)]

// Pruebas de v5: el contrato registra al programador antes de pagar
// (`assign_freelancer`, `assign_project_freelancer`) y, desde ahí, ningún pago
// del cliente puede ir a otra dirección. Más `extend_deadline`, `top_up_task`,
// `freelancer_refund` y la lectura por lote `get_tasks`.
//
// Mismo esquema que `test_v4.rs` (de donde se reutilizan `setup` y los
// depósitos): `Modo::Libre` usa `mock_all_auths`; `Modo::Estricto` nunca lo usa.

extern crate std;

use super::test_v4::{
    deposit_simple, deposit_two_milestones, hash, setup, tid, Ctx, Modo, DIA, MINT, START_TS, UNIT,
};
use super::*;
use soroban_sdk::{
    testutils::{Ledger as _, MockAuth, MockAuthInvoke},
    vec, Address, IntoVal, Val, Vec,
};

// Firma explícita de una sola dirección para una llamada al contrato (modo estricto).
fn firma(ctx: &Ctx, quien: &Address, fn_name: &'static str, args: Vec<Val>) {
    ctx.env.mock_auths(&[MockAuth {
        address: quien,
        invoke: &MockAuthInvoke {
            contract: &ctx.contract_id,
            fn_name,
            args,
            sub_invokes: &[],
        },
    }]);
}

// ---------------------------------------------------------------------------
// assign_freelancer
// ---------------------------------------------------------------------------

#[test]
fn v5_assign_freelancer_registra_es_idempotente_y_no_se_reemplaza() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "asig-1", 5 * UNIT, DIA);

    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    let t = ctx.c.get_task(&id);
    assert_eq!(t.freelancer, Some(ctx.freelancer.clone()));
    assert_eq!(t.status, TaskStatus::Funded); // registrar no paga

    // Repetir con la misma dirección no cambia nada.
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    // Otra dirección no puede ocupar su lugar.
    assert_eq!(
        ctx.c.try_assign_freelancer(&id, &ctx.third),
        Err(Ok(Error::AlreadyAssigned))
    );
    // Tarea inexistente y tarea ya pagada.
    assert_eq!(
        ctx.c.try_assign_freelancer(&tid(&ctx.env, "no-existe"), &ctx.freelancer),
        Err(Ok(Error::NotFound))
    );
    ctx.c.client_release(&id, &ctx.freelancer);
    assert_eq!(
        ctx.c.try_assign_freelancer(&id, &ctx.freelancer),
        Err(Ok(Error::NotFunded))
    );
}

#[test]
fn v5_con_programador_asignado_el_cliente_no_puede_pagarle_a_otro() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "asig-2", 5 * UNIT, DIA);
    ctx.c.assign_freelancer(&id, &ctx.freelancer);

    // El hueco que cierra v5: el cliente pagándose a sí mismo (o a un tercero).
    assert_eq!(
        ctx.c.try_client_release(&id, &ctx.client),
        Err(Ok(Error::WrongFreelancer))
    );
    assert_eq!(
        ctx.c.try_client_release_with_bonus(&id, &ctx.third, &UNIT),
        Err(Ok(Error::WrongFreelancer))
    );
    assert_eq!(
        ctx.c.try_mutual_split_task(&id, &ctx.third, &UNIT),
        Err(Ok(Error::WrongFreelancer))
    );
    assert_eq!(
        ctx.c.try_release(&id, &ctx.third, &hash(&ctx.env, 2), &hash(&ctx.env, 3)),
        Err(Ok(Error::WrongFreelancer))
    );
    // Ya asignada, no se puede cancelar como «sin asignar».
    assert_eq!(
        ctx.c.try_cancel_unassigned_task(&id),
        Err(Ok(Error::AlreadyAssigned))
    );
    // Nada se movió.
    assert_eq!(ctx.token.balance(&ctx.contract_id), 5 * UNIT);

    // Al programador asignado sí se le puede pagar.
    ctx.c.client_release(&id, &ctx.freelancer);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 5 * UNIT);
}

#[test]
fn v5_sin_asignacion_todo_funciona_igual_que_v4() {
    let ctx = setup(Modo::Libre);
    let a = deposit_simple(&ctx, "sin-asig-a", 2 * UNIT, DIA);
    let b = deposit_simple(&ctx, "sin-asig-b", 2 * UNIT, DIA);
    // client_release a cualquier dirección y cancelación siguen como antes.
    ctx.c.client_release(&a, &ctx.third);
    assert_eq!(ctx.token.balance(&ctx.third), 7 + 2 * UNIT);
    ctx.c.cancel_unassigned_task(&b);
    assert_eq!(ctx.c.get_task(&b).status, TaskStatus::Refunded);
}

#[test]
fn v5_assign_freelancer_estricto_solo_el_arbitro() {
    let ctx = setup(Modo::Estricto);
    let id = deposit_simple(&ctx, "asig-estricto", 3 * UNIT, DIA);
    let args: Vec<Val> = (&id, &ctx.freelancer).into_val(&ctx.env);

    // Ni el cliente ni el propio programador pueden registrarse.
    firma(&ctx, &ctx.client, "assign_freelancer", args.clone());
    assert!(ctx.c.try_assign_freelancer(&id, &ctx.freelancer).is_err());
    firma(&ctx, &ctx.freelancer, "assign_freelancer", args.clone());
    assert!(ctx.c.try_assign_freelancer(&id, &ctx.freelancer).is_err());
    assert_eq!(ctx.c.get_task(&id).freelancer, None);

    firma(&ctx, &ctx.arbiter, "assign_freelancer", args);
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    assert_eq!(ctx.c.get_task(&id).freelancer, Some(ctx.freelancer.clone()));
}

// ---------------------------------------------------------------------------
// assign_project_freelancer
// ---------------------------------------------------------------------------

#[test]
fn v5_assign_project_freelancer_fija_al_programador_antes_del_primer_pago() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "proy-asig");

    ctx.c.assign_project_freelancer(&id, &ctx.freelancer);
    assert_eq!(ctx.c.get_project(&id).freelancer, Some(ctx.freelancer.clone()));
    ctx.c.assign_project_freelancer(&id, &ctx.freelancer); // idempotente
    assert_eq!(
        ctx.c.try_assign_project_freelancer(&id, &ctx.third),
        Err(Ok(Error::AlreadyAssigned))
    );

    // Ningún hito se puede pagar a otra dirección, tampoco por el cliente.
    assert_eq!(
        ctx.c.try_client_release_milestone(&id, &0, &ctx.client),
        Err(Ok(Error::WrongFreelancer))
    );
    // Ni cancelar el proyecto como no asignado.
    assert_eq!(
        ctx.c.try_cancel_unassigned_project(&id),
        Err(Ok(Error::AlreadyAssigned))
    );
    ctx.c.client_release_milestone(&id, &0, &ctx.freelancer);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);

    // Proyecto inexistente.
    assert_eq!(
        ctx.c.try_assign_project_freelancer(&tid(&ctx.env, "nada"), &ctx.freelancer),
        Err(Ok(Error::NotFound))
    );
}

#[test]
fn v5_assign_project_freelancer_rechaza_proyecto_sin_hitos_con_dinero() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "proy-cerrado");
    ctx.c.cancel_unassigned_project(&id);
    assert_eq!(
        ctx.c.try_assign_project_freelancer(&id, &ctx.freelancer),
        Err(Ok(Error::NotFunded))
    );
}

#[test]
fn v5_assign_project_freelancer_estricto_solo_el_arbitro() {
    let ctx = setup(Modo::Estricto);
    let id = deposit_two_milestones(&ctx, "proy-estricto");
    let args: Vec<Val> = (&id, &ctx.freelancer).into_val(&ctx.env);
    firma(&ctx, &ctx.client, "assign_project_freelancer", args.clone());
    assert!(ctx.c.try_assign_project_freelancer(&id, &ctx.freelancer).is_err());
    firma(&ctx, &ctx.arbiter, "assign_project_freelancer", args);
    ctx.c.assign_project_freelancer(&id, &ctx.freelancer);
    assert_eq!(ctx.c.get_project(&id).freelancer, Some(ctx.freelancer.clone()));
}

// ---------------------------------------------------------------------------
// extend_deadline
// ---------------------------------------------------------------------------

#[test]
fn v5_extend_deadline_solo_crece_y_respeta_el_tope_de_28_dias() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "plazo-1", 3 * UNIT, DIA);

    assert_eq!(ctx.c.extend_deadline(&id, &DIA), START_TS + 2 * DIA);
    assert_eq!(ctx.c.get_task(&id).deadline, START_TS + 2 * DIA);

    assert_eq!(
        ctx.c.try_extend_deadline(&id, &0),
        Err(Ok(Error::InvalidDeadline))
    );
    // Más de 28 días desde ahora: rechazado (TTL de 30 días).
    assert_eq!(
        ctx.c.try_extend_deadline(&id, &(27 * DIA)),
        Err(Ok(Error::InvalidDeadline))
    );
    assert_eq!(
        ctx.c.try_extend_deadline(&id, &u64::MAX),
        Err(Ok(Error::InvalidDeadline))
    );
    // Exactamente 28 días desde ahora sí cabe.
    ctx.c.extend_deadline(&id, &(26 * DIA));
    assert_eq!(ctx.c.get_task(&id).deadline, START_TS + 28 * DIA);
}

#[test]
fn v5_extend_deadline_tras_vencer_reabre_el_pago_del_arbitro() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "plazo-2", 3 * UNIT, 100);
    ctx.env.ledger().set_timestamp(START_TS + 100);
    let (h1, h2) = (hash(&ctx.env, 4), hash(&ctx.env, 5));
    assert_eq!(
        ctx.c.try_release(&id, &ctx.freelancer, &h1, &h2),
        Err(Ok(Error::DeadlinePassed))
    );
    // El cliente decide dar más tiempo: el reembolso por plazo ya no procede.
    ctx.c.extend_deadline(&id, &DIA);
    assert_eq!(
        ctx.c.try_timeout_refund(&id),
        Err(Ok(Error::DeadlineNotReached))
    );
    ctx.c.release(&id, &ctx.freelancer, &h1, &h2);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT);
    // Una tarea pagada ya no se prorroga.
    assert_eq!(
        ctx.c.try_extend_deadline(&id, &DIA),
        Err(Ok(Error::NotFunded))
    );
}

#[test]
fn v5_extend_deadline_estricto_solo_el_cliente() {
    let ctx = setup(Modo::Estricto);
    let id = deposit_simple(&ctx, "plazo-estricto", 3 * UNIT, DIA);
    let args: Vec<Val> = (&id, DIA).into_val(&ctx.env);
    firma(&ctx, &ctx.arbiter, "extend_deadline", args.clone());
    assert!(ctx.c.try_extend_deadline(&id, &DIA).is_err());
    firma(&ctx, &ctx.client, "extend_deadline", args);
    ctx.c.extend_deadline(&id, &DIA);
    assert_eq!(ctx.c.get_task(&id).deadline, START_TS + 2 * DIA);
}

// ---------------------------------------------------------------------------
// top_up_task
// ---------------------------------------------------------------------------

#[test]
fn v5_top_up_task_suma_al_deposito_y_el_pago_incluye_el_extra() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "recarga-1", 3 * UNIT, DIA);

    assert_eq!(ctx.c.top_up_task(&id, &(2 * UNIT)), 5 * UNIT);
    assert_eq!(ctx.c.get_task(&id).amount, 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 5 * UNIT);

    assert_eq!(ctx.c.try_top_up_task(&id, &0), Err(Ok(Error::InvalidAmount)));
    assert_eq!(ctx.c.try_top_up_task(&id, &-1), Err(Ok(Error::InvalidAmount)));

    ctx.c.release(&id, &ctx.freelancer, &hash(&ctx.env, 6), &hash(&ctx.env, 7));
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.c.try_top_up_task(&id, &UNIT), Err(Ok(Error::NotFunded)));
}

#[test]
fn v5_top_up_task_no_despues_del_plazo_y_estricto() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "recarga-2", 3 * UNIT, 100);
    ctx.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(ctx.c.try_top_up_task(&id, &UNIT), Err(Ok(Error::DeadlinePassed)));

    let est = setup(Modo::Estricto);
    let eid = deposit_simple(&est, "recarga-estricto", 3 * UNIT, DIA);
    // Firma del cliente sin autorizar la transferencia del token: falla.
    firma(&est, &est.client, "top_up_task", (&eid, UNIT).into_val(&est.env));
    assert!(est.c.try_top_up_task(&eid, &UNIT).is_err());
    // Con la transferencia autorizada como subinvocación: pasa.
    let token_id = est.token.address.clone();
    est.env.mock_auths(&[MockAuth {
        address: &est.client,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "top_up_task",
            args: (&eid, UNIT).into_val(&est.env),
            sub_invokes: &[MockAuthInvoke {
                contract: &token_id,
                fn_name: "transfer",
                args: (&est.client, &est.contract_id, UNIT).into_val(&est.env),
                sub_invokes: &[],
            }],
        },
    }]);
    est.c.top_up_task(&eid, &UNIT);
    assert_eq!(est.c.get_task(&eid).amount, 4 * UNIT);
}

// ---------------------------------------------------------------------------
// freelancer_refund
// ---------------------------------------------------------------------------

#[test]
fn v5_freelancer_refund_devuelve_todo_al_cliente() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "renuncia-1", 4 * UNIT, DIA);

    // Sin programador asignado no hay renuncia posible.
    assert_eq!(
        ctx.c.try_freelancer_refund(&id),
        Err(Ok(Error::WrongFreelancer))
    );

    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    ctx.c.freelancer_refund(&id);
    let t = ctx.c.get_task(&id);
    assert_eq!(t.status, TaskStatus::Refunded);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 0);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.c.try_freelancer_refund(&id), Err(Ok(Error::NotFunded)));
}

#[test]
fn v5_freelancer_refund_estricto_solo_el_programador_asignado() {
    let ctx = setup(Modo::Estricto);
    let id = deposit_simple(&ctx, "renuncia-estricto", 4 * UNIT, DIA);
    firma(&ctx, &ctx.arbiter, "assign_freelancer", (&id, &ctx.freelancer).into_val(&ctx.env));
    ctx.c.assign_freelancer(&id, &ctx.freelancer);

    let args: Vec<Val> = (&id,).into_val(&ctx.env);
    // Ni el cliente ni un tercero pueden forzar la renuncia.
    firma(&ctx, &ctx.client, "freelancer_refund", args.clone());
    assert!(ctx.c.try_freelancer_refund(&id).is_err());
    firma(&ctx, &ctx.third, "freelancer_refund", args.clone());
    assert!(ctx.c.try_freelancer_refund(&id).is_err());
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Funded);

    firma(&ctx, &ctx.freelancer, "freelancer_refund", args);
    ctx.c.freelancer_refund(&id);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);
}

// ---------------------------------------------------------------------------
// get_tasks
// ---------------------------------------------------------------------------

#[test]
fn v5_get_tasks_lee_por_lote_en_orden_con_huecos() {
    let ctx = setup(Modo::Libre);
    let a = deposit_simple(&ctx, "lote-a", UNIT, DIA);
    let b = deposit_simple(&ctx, "lote-b", 2 * UNIT, DIA);
    let nada = tid(&ctx.env, "no-existe");

    let out = ctx.c.get_tasks(&vec![&ctx.env, b.clone(), nada, a.clone()]);
    assert_eq!(out.len(), 3);
    assert_eq!(out.get(0).unwrap().unwrap().amount, 2 * UNIT);
    assert_eq!(out.get(1).unwrap(), None);
    assert_eq!(out.get(2).unwrap().unwrap().task_id, a);

    let vacio: Vec<String> = Vec::new(&ctx.env);
    assert_eq!(ctx.c.try_get_tasks(&vacio), Err(Ok(Error::TooManyItems)));
    let mut muchos: Vec<String> = Vec::new(&ctx.env);
    for _ in 0..21 {
        muchos.push_back(a.clone());
    }
    assert_eq!(ctx.c.try_get_tasks(&muchos), Err(Ok(Error::TooManyItems)));
}

// ---------------------------------------------------------------------------
// Invariante contable de v5
// ---------------------------------------------------------------------------

#[test]
fn v5_invariante_contable_con_todas_las_funciones_nuevas() {
    let ctx = setup(Modo::Libre);
    let pagada = deposit_simple(&ctx, "inv-pagada", 3 * UNIT, DIA);
    let renunciada = deposit_simple(&ctx, "inv-renuncia", 2 * UNIT, DIA);
    let abierta = deposit_simple(&ctx, "inv-abierta", UNIT, DIA);

    ctx.c.assign_freelancer(&pagada, &ctx.freelancer);
    ctx.c.top_up_task(&pagada, &UNIT);
    ctx.c.extend_deadline(&pagada, &DIA);
    ctx.c.client_release(&pagada, &ctx.freelancer);

    ctx.c.assign_freelancer(&renunciada, &ctx.freelancer);
    ctx.c.freelancer_refund(&renunciada);

    ctx.c.top_up_task(&abierta, &UNIT);

    // Lo que hay en el contrato es exactamente lo que siguen debiendo las tareas Funded.
    let leidas = ctx.c.get_tasks(&vec![&ctx.env, pagada, renunciada, abierta]);
    let mut pendiente: i128 = 0;
    for t in leidas.iter() {
        let t = t.unwrap();
        if t.status == TaskStatus::Funded {
            pendiente += t.amount;
        }
    }
    assert_eq!(pendiente, 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), pendiente);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);
    // Nada se crea ni se pierde: cliente + contrato + programador = lo acuñado.
    assert_eq!(
        ctx.token.balance(&ctx.client) + ctx.token.balance(&ctx.contract_id) + ctx.token.balance(&ctx.freelancer),
        MINT
    );
}
