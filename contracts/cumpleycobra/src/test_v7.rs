#![cfg(test)]

// Pruebas de v7: acuerdos y disputas en proyectos por hitos, y operaciones por
// lote. Mismo esquema que `test_v4.rs` a `test_v6.rs`: `Modo::Libre` usa
// `mock_all_auths`; `Modo::Estricto` nunca lo usa y cada firma es explícita.

extern crate std;

use super::test_v4::{deposit_two_milestones, hash, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _},
    Address, IntoVal, Val, Vec,
};

// Proyecto de dos hitos (4 y 6 UNIT, vencen a 1 y 2 días) con programador fijado.
fn proyecto_asignado(ctx: &Ctx, nombre: &str) -> String {
    let id = deposit_two_milestones(ctx, nombre);
    if ctx.modo == Modo::Estricto {
        firmas(ctx, &[&ctx.arbiter], "assign_project_freelancer", (&id, &ctx.freelancer).into_val(&ctx.env));
    }
    ctx.c.assign_project_freelancer(&id, &ctx.freelancer);
    id
}

fn estado(ctx: &Ctx, id: &String, i: u32) -> Milestone {
    ctx.c.get_project(id).milestones.get(i).unwrap()
}

// ---------------------------------------------------------------------------
// Lote 1: acuerdos entre las dos partes en hitos
// ---------------------------------------------------------------------------

#[test]
fn v7_amend_milestone_rules_con_las_dos_firmas() {
    let ctx = setup(Modo::Libre);
    let sin_programador = deposit_two_milestones(&ctx, "amend-h-0");
    assert_eq!(
        ctx.c.try_amend_milestone_rules(&sin_programador, &0, &hash(&ctx.env, 9)),
        Err(Ok(Error::WrongFreelancer))
    );
    let id = proyecto_asignado(&ctx, "amend-h-1");
    ctx.c.amend_milestone_rules(&id, &1, &hash(&ctx.env, 9));
    assert_eq!(estado(&ctx, &id, 1).rules_hash, hash(&ctx.env, 9));
    assert_eq!(estado(&ctx, &id, 0).rules_hash, hash(&ctx.env, 10)); // el otro no cambia
    assert_eq!(
        ctx.c.try_amend_milestone_rules(&id, &1, &hash(&ctx.env, 9)),
        Err(Ok(Error::NoChange))
    );
    assert_eq!(
        ctx.c.try_amend_milestone_rules(&id, &5, &hash(&ctx.env, 8)),
        Err(Ok(Error::MilestoneNotFound))
    );

    let est = setup(Modo::Estricto);
    let eid = proyecto_asignado(&est, "amend-h-estricto");
    let args: Vec<Val> = (&eid, 0u32, hash(&est.env, 7)).into_val(&est.env);
    firmas(&est, &[&est.client], "amend_milestone_rules", args.clone());
    assert!(est.c.try_amend_milestone_rules(&eid, &0, &hash(&est.env, 7)).is_err());
    firmas(&est, &[&est.client, &est.freelancer], "amend_milestone_rules", args);
    est.c.amend_milestone_rules(&eid, &0, &hash(&est.env, 7));
}

#[test]
fn v7_release_milestone_partial_paga_una_parte_del_hito() {
    let ctx = setup(Modo::Libre);
    let (h1, h2) = (hash(&ctx.env, 1), hash(&ctx.env, 2));
    let id = proyecto_asignado(&ctx, "parcial-h-1");
    assert_eq!(ctx.c.release_milestone_partial(&id, &1, &(2 * UNIT), &h1, &h2), 4 * UNIT);
    let m = estado(&ctx, &id, 1);
    assert_eq!((m.amount, m.status), (4 * UNIT, MilestoneStatus::Funded));
    assert_eq!(ctx.token.balance(&ctx.freelancer), 2 * UNIT);
    for malo in [0, -1, 4 * UNIT] {
        assert_eq!(
            ctx.c.try_release_milestone_partial(&id, &1, &malo, &h1, &h2),
            Err(Ok(Error::InvalidAmount))
        );
    }
    // Pasado el plazo del hito 0, ese hito ya no se paga en partes.
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(
        ctx.c.try_release_milestone_partial(&id, &0, &UNIT, &h1, &h2),
        Err(Ok(Error::DeadlinePassed))
    );
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));

    let est = setup(Modo::Estricto);
    let eid = proyecto_asignado(&est, "parcial-h-estricto");
    let (h1, h2) = (hash(&est.env, 1), hash(&est.env, 2));
    let args: Vec<Val> = (&eid, 0u32, UNIT, &h1, &h2).into_val(&est.env);
    firmas(&est, &[&est.client], "release_milestone_partial", args.clone());
    assert!(est.c.try_release_milestone_partial(&eid, &0, &UNIT, &h1, &h2).is_err());
    firmas(&est, &[&est.arbiter], "release_milestone_partial", args);
    est.c.release_milestone_partial(&eid, &0, &UNIT, &h1, &h2);
}

#[test]
fn v7_mutual_cancel_project_devuelve_solo_lo_pendiente() {
    let ctx = setup(Modo::Libre);
    let id = proyecto_asignado(&ctx, "cancela-p-1");
    ctx.c.client_release_milestone(&id, &0, &ctx.freelancer);
    assert_eq!(ctx.c.mutual_cancel_project(&id), 1);
    assert_eq!(estado(&ctx, &id, 0).status, MilestoneStatus::Released);
    assert_eq!(estado(&ctx, &id, 1).status, MilestoneStatus::Refunded);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 4 * UNIT);
    assert_eq!(ctx.c.try_mutual_cancel_project(&id), Err(Ok(Error::NotFunded)));

    let est = setup(Modo::Estricto);
    let eid = proyecto_asignado(&est, "cancela-p-estricto");
    let args: Vec<Val> = (&eid,).into_val(&est.env);
    firmas(&est, &[&est.freelancer], "mutual_cancel_project", args.clone());
    assert!(est.c.try_mutual_cancel_project(&eid).is_err());
    firmas(&est, &[&est.client, &est.freelancer], "mutual_cancel_project", args);
    est.c.mutual_cancel_project(&eid);
    assert_eq!(est.token.balance(&est.client), MINT);
}

#[test]
fn v7_reassign_project_freelancer_exige_las_tres_firmas() {
    let ctx = setup(Modo::Libre);
    let id = proyecto_asignado(&ctx, "reasigna-p-1");
    assert_eq!(
        ctx.c.try_reassign_project_freelancer(&id, &ctx.freelancer),
        Err(Ok(Error::NoChange))
    );
    ctx.c.reassign_project_freelancer(&id, &ctx.third);
    assert_eq!(
        ctx.c.try_client_release_milestone(&id, &0, &ctx.freelancer),
        Err(Ok(Error::WrongFreelancer))
    );
    ctx.c.client_release_milestone(&id, &0, &ctx.third);
    assert_eq!(ctx.token.balance(&ctx.third), 7 + 4 * UNIT);

    let est = setup(Modo::Estricto);
    let eid = proyecto_asignado(&est, "reasigna-p-estricto");
    let args: Vec<Val> = (&eid, &est.third).into_val(&est.env);
    for faltan in [
        [&est.client, &est.freelancer],
        [&est.client, &est.third],
        [&est.freelancer, &est.third],
    ] {
        firmas(&est, &faltan, "reassign_project_freelancer", args.clone());
        assert!(est.c.try_reassign_project_freelancer(&eid, &est.third).is_err());
    }
    firmas(&est, &[&est.client, &est.freelancer, &est.third], "reassign_project_freelancer", args);
    est.c.reassign_project_freelancer(&eid, &est.third);
    assert_eq!(est.c.get_project(&eid).freelancer, Some(est.third.clone()));
}

#[test]
fn v7_transfer_project_client_cambia_quien_recibe_los_reembolsos() {
    let ctx = setup(Modo::Libre);
    let nuevo = Address::generate(&ctx.env);
    let id = deposit_two_milestones(&ctx, "transfiere-p-1");
    assert_eq!(
        ctx.c.try_transfer_project_client(&id, &ctx.client),
        Err(Ok(Error::NoChange))
    );
    ctx.c.transfer_project_client(&id, &nuevo);
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    ctx.c.refund_all_expired_milestones(&id);
    assert_eq!(ctx.token.balance(&nuevo), 10 * UNIT);
    // Proyecto cerrado: ya no se transfiere.
    assert_eq!(
        ctx.c.try_transfer_project_client(&id, &ctx.client),
        Err(Ok(Error::NotFunded))
    );

    let est = setup(Modo::Estricto);
    let empresa = Address::generate(&est.env);
    let eid = proyecto_asignado(&est, "transfiere-p-estricto");
    let args: Vec<Val> = (&eid, &empresa).into_val(&est.env);
    firmas(&est, &[&est.client, &empresa], "transfer_project_client", args.clone());
    assert!(est.c.try_transfer_project_client(&eid, &empresa).is_err());
    firmas(&est, &[&est.client, &empresa, &est.freelancer], "transfer_project_client", args);
    est.c.transfer_project_client(&eid, &empresa);
    assert_eq!(est.c.get_project(&eid).client, empresa);
}
