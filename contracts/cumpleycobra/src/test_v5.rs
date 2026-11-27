#![cfg(test)]

// Pruebas de v5: el contrato registra al programador antes de pagar
// (`assign_freelancer`, `assign_project_freelancer`) y, desde ahí, ningún pago
// del cliente puede ir a otra dirección.
//
// Mismo esquema que `test_v4.rs` (de donde se reutilizan `setup` y los
// depósitos): `Modo::Libre` usa `mock_all_auths`; `Modo::Estricto` nunca lo usa.

extern crate std;

use super::test_v4::{
    deposit_simple, deposit_two_milestones, hash, setup, tid, Ctx, Modo, DIA, MINT, UNIT,
};
use super::*;
use soroban_sdk::{
    testutils::{MockAuth, MockAuthInvoke},
    Address, IntoVal, Val, Vec,
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
