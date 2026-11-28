#![cfg(test)]

// Pruebas de v13. `Modo::Libre` usa `mock_all_auths`; las estrictas fijan firmas.

extern crate std;

use super::test_v4::{deposit_simple, deposit_two_milestones, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _},
    Address, IntoVal, Vec,
};

fn cuadra(ctx: &Ctx) {
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
}

#[test]
fn v13_aprobacion_manual_con_comision_en_tarea_y_hito() {
    let ctx = setup(Modo::Libre);
    let plataforma = Address::generate(&ctx.env);
    let t = deposit_simple(&ctx, "cf", 10 * UNIT, DIA);
    assert_eq!(ctx.c.try_client_release_with_fee(&t, &ctx.freelancer, &plataforma, &0), Err(Ok(Error::InvalidAmount)));
    assert_eq!(ctx.c.try_client_release_with_fee(&t, &ctx.freelancer, &ctx.client, &500), Err(Ok(Error::NoChange)));
    assert_eq!(ctx.c.client_release_with_fee(&t, &ctx.freelancer, &plataforma, &500), 10 * UNIT - UNIT / 2);
    assert_eq!(ctx.token.balance(&plataforma), UNIT / 2);
    let p = deposit_two_milestones(&ctx, "cmf");
    assert_eq!(ctx.c.client_release_milestone_fee(&p, &0, &ctx.freelancer, &plataforma, &1000), 4 * UNIT - 4 * UNIT / 10);
    assert_eq!(
        ctx.c.try_client_release_milestone_fee(&p, &1, &ctx.third, &plataforma, &1000),
        Err(Ok(Error::WrongFreelancer))
    );
    cuadra(&ctx);

    let est = setup(Modo::Estricto);
    let pl = Address::generate(&est.env);
    let et = deposit_simple(&est, "cf-e", UNIT, DIA);
    firmas(&est, &[&est.freelancer], "client_release_with_fee", (&et, &est.freelancer, &pl, 500u32).into_val(&est.env));
    assert!(est.c.try_client_release_with_fee(&et, &est.freelancer, &pl, &500).is_err());
}

#[test]
fn v13_patrocinio_de_tarea_hito_y_pago_por_tiempo() {
    let ctx = setup(Modo::Libre);
    let t = deposit_simple(&ctx, "ct", 2 * UNIT, 100);
    assert_eq!(ctx.c.try_contribute_task(&ctx.client, &t, &UNIT), Err(Ok(Error::NoChange)));
    assert_eq!(ctx.c.contribute_task(&ctx.third, &t, &5), 2 * UNIT + 5);
    // Si se reembolsa, todo vuelve al cliente (también el aporte).
    ctx.env.ledger().set_timestamp(START_TS + 100);
    ctx.c.timeout_refund(&t);
    assert_eq!(ctx.token.balance(&ctx.client), MINT + 5);
    assert_eq!(ctx.token.balance(&ctx.third), 2);

    let ctx = setup(Modo::Libre);
    let p = deposit_two_milestones(&ctx, "cm");
    assert_eq!(ctx.c.contribute_milestone(&ctx.third, &p, &1, &5), 6 * UNIT + 5);
    ctx.c.client_release_milestone(&p, &1, &ctx.freelancer);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 6 * UNIT + 5);

    let s = String::from_str(&ctx.env, "cs");
    ctx.c.deposit_stream(&ctx.client, &s, &ctx.freelancer, &(10 * UNIT), &(10 * DIA));
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    // Cobra 2 ganados; quedan 8 + 0.0000002 de patrocinio en 8 días.
    assert_eq!(ctx.c.contribute_stream(&ctx.third, &s, &2), 8 * UNIT + 2);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 6 * UNIT + 5 + 2 * UNIT);
    ctx.env.ledger().set_timestamp(START_TS + 10 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&s), 8 * UNIT + 2);
    cuadra(&ctx);
}

#[test]
fn v13_garantia_y_plazos_de_proyecto() {
    let ctx = setup(Modo::Libre);
    ctx.token.transfer(&ctx.client, &ctx.freelancer, &(3 * UNIT));
    let p = deposit_two_milestones(&ctx, "gp");
    ctx.c.assign_project_freelancer(&p, &ctx.freelancer);
    assert_eq!(ctx.c.try_top_up_project_bond(&p, &UNIT), Err(Ok(Error::NotFound)));
    ctx.c.post_project_bond(&p, &UNIT);
    assert_eq!(ctx.c.top_up_project_bond(&p, &UNIT), 2 * UNIT);
    assert_eq!(ctx.c.extend_project_deadlines(&p, &DIA), 2);
    let pr = ctx.c.get_project(&p);
    assert_eq!(pr.milestones.get(0).unwrap().deadline, START_TS + 2 * DIA);
    assert_eq!(pr.milestones.get(1).unwrap().deadline, START_TS + 3 * DIA);
    assert_eq!(ctx.c.try_extend_project_deadlines(&p, &(30 * DIA)), Err(Ok(Error::InvalidDeadline)));
    assert_eq!(ctx.c.try_extend_project_deadlines(&p, &0), Err(Ok(Error::InvalidDeadline)));
    cuadra(&ctx);
}

#[test]
fn v13_withdraw_stream_to_y_reparto_de_proyecto() {
    let ctx = setup(Modo::Libre);
    let otra = Address::generate(&ctx.env);
    let s = String::from_str(&ctx.env, "wt");
    ctx.c.deposit_stream(&ctx.client, &s, &ctx.freelancer, &(10 * UNIT), &(10 * DIA));
    assert_eq!(ctx.c.try_withdraw_stream_to(&s, &otra), Err(Ok(Error::NothingToWithdraw)));
    ctx.env.ledger().set_timestamp(START_TS + 3 * DIA);
    assert_eq!(ctx.c.try_withdraw_stream_to(&s, &ctx.freelancer), Err(Ok(Error::NoChange)));
    assert_eq!(ctx.c.withdraw_stream_to(&s, &otra), 3 * UNIT);
    assert_eq!(ctx.token.balance(&otra), 3 * UNIT);

    let p = deposit_two_milestones(&ctx, "sp");
    assert_eq!(ctx.c.try_mutual_split_project(&p, &UNIT), Err(Ok(Error::WrongFreelancer)));
    ctx.c.assign_project_freelancer(&p, &ctx.freelancer);
    assert_eq!(ctx.c.try_mutual_split_project(&p, &(10 * UNIT)), Err(Ok(Error::InvalidAmount)));
    ctx.c.mutual_split_project(&p, &(7 * UNIT));
    assert_eq!(ctx.token.balance(&ctx.freelancer), 7 * UNIT);
    assert_eq!(ctx.c.try_mutual_split_project(&p, &UNIT), Err(Ok(Error::NotFunded)));
    cuadra(&ctx);
}

#[test]
fn v13_refund_expired_projects_batch() {
    let ctx = setup(Modo::Libre);
    let a = deposit_two_milestones(&ctx, "ra");
    let b = deposit_two_milestones(&ctx, "rb");
    let ids: Vec<String> = Vec::from_array(&ctx.env, [a.clone(), b.clone(), String::from_str(&ctx.env, "nada")]);
    assert_eq!(ctx.c.try_refund_expired_projects_batch(&ids), Err(Ok(Error::DeadlineNotReached)));
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(ctx.c.refund_expired_projects_batch(&ids), 2); // el hito 0 de cada uno
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    assert_eq!(ctx.c.refund_expired_projects_batch(&ids), 2);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);
    cuadra(&ctx);
}
