#![cfg(test)]

// Pruebas de v12: aprobación manual parcial, garantía de proyecto y retiro de
// varios pagos por tiempo. `Modo::Libre` usa `mock_all_auths`.

extern crate std;

use super::test_v4::{deposit_simple, deposit_two_milestones, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{testutils::Ledger as _, IntoVal, Val, Vec};

fn cuadra(ctx: &Ctx) {
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
}

#[test]
fn v12_client_release_partial_paga_una_parte_y_el_resto_sigue() {
    let ctx = setup(Modo::Libre);
    let id = deposit_simple(&ctx, "crp", 4 * UNIT, DIA);
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    assert_eq!(ctx.c.try_client_release_partial(&id, &ctx.third, &UNIT), Err(Ok(Error::WrongFreelancer)));
    for malo in [0, 4 * UNIT] {
        assert_eq!(ctx.c.try_client_release_partial(&id, &ctx.freelancer, &malo), Err(Ok(Error::InvalidAmount)));
    }
    assert_eq!(ctx.c.client_release_partial(&id, &ctx.freelancer, &UNIT), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), UNIT);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Funded);
    // El resto vuelve al cliente al vencer.
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    ctx.c.timeout_refund(&id);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - UNIT);
    cuadra(&ctx);

    let est = setup(Modo::Estricto);
    let eid = deposit_simple(&est, "crp-e", 4 * UNIT, DIA);
    firmas(&est, &[&est.freelancer], "client_release_partial", (&eid, &est.freelancer, UNIT).into_val(&est.env));
    assert!(est.c.try_client_release_partial(&eid, &est.freelancer, &UNIT).is_err());
}

#[test]
fn v12_client_release_milestone_partial() {
    let ctx = setup(Modo::Libre);
    let id = deposit_two_milestones(&ctx, "crmp");
    assert_eq!(ctx.c.client_release_milestone_partial(&id, &1, &ctx.freelancer, &(2 * UNIT)), 4 * UNIT);
    assert_eq!(ctx.c.get_project(&id).freelancer, Some(ctx.freelancer.clone()));
    assert_eq!(
        ctx.c.try_client_release_milestone_partial(&id, &0, &ctx.third, &UNIT),
        Err(Ok(Error::WrongFreelancer))
    );
    assert_eq!(
        ctx.c.try_client_release_milestone_partial(&id, &1, &ctx.freelancer, &(4 * UNIT)),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(ctx.token.balance(&ctx.freelancer), 2 * UNIT);
    cuadra(&ctx);
}

fn proyecto_con_garantia(ctx: &Ctx, nombre: &str) -> String {
    ctx.token.transfer(&ctx.client, &ctx.freelancer, &(3 * UNIT));
    let id = deposit_two_milestones(ctx, nombre);
    if ctx.modo == Modo::Estricto {
        // El depósito deja firmas explícitas; la preparación no es lo que se prueba.
        ctx.env.mock_all_auths();
    }
    ctx.c.assign_project_freelancer(&id, &ctx.freelancer);
    ctx.c.post_project_bond(&id, &(2 * UNIT));
    id
}

#[test]
fn v12_garantia_de_proyecto_se_recupera_si_se_pago() {
    let ctx = setup(Modo::Libre);
    let sin = deposit_two_milestones(&ctx, "pb-0");
    assert_eq!(ctx.c.try_post_project_bond(&sin, &UNIT), Err(Ok(Error::WrongFreelancer)));
    let id = proyecto_con_garantia(&ctx, "pb-1");
    assert_eq!(ctx.c.try_post_project_bond(&id, &UNIT), Err(Ok(Error::AlreadyExists)));
    assert_eq!(ctx.c.try_reclaim_project_bond(&id), Err(Ok(Error::NotFunded)));
    ctx.c.client_release_milestone(&id, &0, &ctx.freelancer);
    ctx.c.client_release_milestone(&id, &1, &ctx.freelancer);
    assert_eq!(ctx.c.try_slash_project_bond(&id, &UNIT), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.c.reclaim_project_bond(&id), 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT + 10 * UNIT);
    cuadra(&ctx);
}

#[test]
fn v12_garantia_de_proyecto_se_reparte_si_hubo_reembolso() {
    let ctx = setup(Modo::Libre);
    let id = proyecto_con_garantia(&ctx, "pb-2");
    ctx.c.client_release_milestone(&id, &0, &ctx.freelancer);
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    ctx.c.timeout_refund_milestone(&id, &1);
    // Un hito pagado y otro reembolsado: el proyecto está cerrado y la garantía vuelve.
    assert_eq!(ctx.c.reclaim_project_bond(&id), 2 * UNIT);
    let est_id = proyecto_con_garantia(&ctx, "pb-3");
    ctx.env.ledger().set_timestamp(START_TS + 5 * DIA);
    ctx.c.refund_all_expired_milestones(&est_id);
    assert_eq!(ctx.c.try_slash_project_bond(&est_id, &(3 * UNIT)), Err(Ok(Error::InvalidAmount)));
    let cliente_antes = ctx.token.balance(&ctx.client);
    ctx.c.slash_project_bond(&est_id, &UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), cliente_antes + UNIT);
    assert_eq!(ctx.c.try_slash_project_bond(&est_id, &UNIT), Err(Ok(Error::NotFound)));
    cuadra(&ctx);

    let est = setup(Modo::Estricto);
    est.env.mock_all_auths();
    let eid = proyecto_con_garantia(&est, "pb-e");
    est.env.ledger().set_timestamp(START_TS + 5 * DIA);
    est.c.refund_all_expired_milestones(&eid);
    let args: Vec<Val> = (&eid, UNIT).into_val(&est.env);
    firmas(&est, &[&est.client], "slash_project_bond", args);
    assert!(est.c.try_slash_project_bond(&eid, &UNIT).is_err());
}

#[test]
fn v12_withdraw_stream_batch_retira_de_varios_pagos() {
    let ctx = setup(Modo::Libre);
    let a = String::from_str(&ctx.env, "wa");
    let b = String::from_str(&ctx.env, "wb");
    let c = String::from_str(&ctx.env, "wc");
    ctx.c.deposit_stream(&ctx.client, &a, &ctx.freelancer, &(10 * UNIT), &(10 * DIA));
    ctx.c.deposit_stream(&ctx.client, &b, &ctx.freelancer, &(5 * UNIT), &(5 * DIA));
    ctx.c.deposit_stream(&ctx.client, &c, &ctx.third, &(5 * UNIT), &(5 * DIA));
    let ids: Vec<String> = Vec::from_array(&ctx.env, [a.clone(), b.clone(), c.clone()]);
    assert_eq!(ctx.c.try_withdraw_stream_batch(&ctx.freelancer, &ids), Err(Ok(Error::NothingToWithdraw)));
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    // 2 de a + 2 de b; c es de otro programador y se omite.
    assert_eq!(ctx.c.withdraw_stream_batch(&ctx.freelancer, &ids), 4 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);
    assert_eq!(ctx.c.get_stream(&c).withdrawn, 0);
    cuadra(&ctx);
}
