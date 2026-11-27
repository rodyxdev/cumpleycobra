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

// ---------------------------------------------------------------------------
// Lote 2: disputas por hito y retiro de disputas
// ---------------------------------------------------------------------------

#[test]
fn v7_disputa_de_hito_solo_las_partes_y_congela_solo_ese_hito() {
    let ctx = setup(Modo::Libre);
    let sin_programador = deposit_two_milestones(&ctx, "disp-h-0");
    assert_eq!(
        ctx.c.try_open_milestone_dispute(&sin_programador, &0, &ctx.client),
        Err(Ok(Error::WrongFreelancer))
    );
    let id = proyecto_asignado(&ctx, "disp-h-1");
    assert_eq!(
        ctx.c.try_open_milestone_dispute(&id, &0, &ctx.third),
        Err(Ok(Error::NotParty))
    );
    ctx.c.open_milestone_dispute(&id, &0, &ctx.client);
    assert_eq!(ctx.c.get_milestone_dispute(&id, &0), Some(ctx.client.clone()));
    assert_eq!(ctx.c.get_milestone_dispute(&id, &1), None);
    assert_eq!(
        ctx.c.try_open_milestone_dispute(&id, &0, &ctx.freelancer),
        Err(Ok(Error::DisputeOpen))
    );

    // Vencidos los dos hitos: el 0 está congelado, el 1 se reembolsa.
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    assert_eq!(
        ctx.c.try_timeout_refund_milestone(&id, &0),
        Err(Ok(Error::DisputeOpen))
    );
    assert_eq!(ctx.c.refund_all_expired_milestones(&id), 1);
    assert_eq!(estado(&ctx, &id, 0).status, MilestoneStatus::Funded);
    assert_eq!(estado(&ctx, &id, 1).status, MilestoneStatus::Refunded);
    // Solo queda el congelado: nada que reembolsar todavía.
    assert_eq!(
        ctx.c.try_refund_all_expired_milestones(&id),
        Err(Ok(Error::DeadlineNotReached))
    );
    // A los 14 días del plazo del hito 0, vuelve a poder reembolsarse.
    ctx.env.ledger().set_timestamp(START_TS + DIA + 14 * DIA);
    ctx.c.timeout_refund_milestone(&id, &0);
    // El proyecto sin programador (disp-h-0) sigue depositado: 10 UNIT.
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 10 * UNIT);
}

#[test]
fn v7_resolve_milestone_dispute_reparte_el_hito() {
    let ctx = setup(Modo::Libre);
    let id = proyecto_asignado(&ctx, "resuelve-h-1");
    assert_eq!(
        ctx.c.try_resolve_milestone_dispute(&id, &1, &0),
        Err(Ok(Error::NoDispute))
    );
    ctx.c.open_milestone_dispute(&id, &1, &ctx.freelancer);
    ctx.env.ledger().set_timestamp(START_TS + 3 * DIA); // también tras el plazo
    assert_eq!(
        ctx.c.try_resolve_milestone_dispute(&id, &1, &(7 * UNIT)),
        Err(Ok(Error::InvalidAmount))
    );
    ctx.c.resolve_milestone_dispute(&id, &1, &(5 * UNIT));
    assert_eq!(estado(&ctx, &id, 1).status, MilestoneStatus::Released);
    assert_eq!(ctx.c.get_milestone_dispute(&id, &1), None);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));

    let est = setup(Modo::Estricto);
    let eid = proyecto_asignado(&est, "resuelve-h-estricto");
    firmas(&est, &[&est.client], "open_milestone_dispute", (&eid, 0u32, &est.client).into_val(&est.env));
    est.c.open_milestone_dispute(&eid, &0, &est.client);
    let args: Vec<Val> = (&eid, 0u32, 0i128).into_val(&est.env);
    firmas(&est, &[&est.client], "resolve_milestone_dispute", args.clone());
    assert!(est.c.try_resolve_milestone_dispute(&eid, &0, &0).is_err());
    firmas(&est, &[&est.arbiter], "resolve_milestone_dispute", args);
    est.c.resolve_milestone_dispute(&eid, &0, &0);
    assert_eq!(est.c.get_project(&eid).milestones.get(0).unwrap().status, MilestoneStatus::Refunded);
}

#[test]
fn v7_cancel_dispute_lo_retira_quien_lo_abrio() {
    let ctx = setup(Modo::Libre);
    let id = super::test_v4::deposit_simple(&ctx, "retira-1", 2 * UNIT, DIA);
    assert_eq!(ctx.c.try_cancel_dispute(&id), Err(Ok(Error::NoDispute)));
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    ctx.c.open_dispute(&id, &ctx.client);
    ctx.c.cancel_dispute(&id);
    assert_eq!(ctx.c.get_dispute(&id), None);
    // Sin disputa, el reembolso por plazo funciona en cuanto vence.
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    ctx.c.timeout_refund(&id);

    // Limpia la disputa de una tarea que se cerró por otra vía (límite de v6).
    let id2 = super::test_v4::deposit_simple(&ctx, "retira-2", UNIT, 10 * DIA);
    ctx.c.assign_freelancer(&id2, &ctx.freelancer);
    ctx.c.open_dispute(&id2, &ctx.freelancer);
    ctx.c.client_release(&id2, &ctx.freelancer);
    assert_eq!(ctx.c.get_dispute(&id2), Some(ctx.freelancer.clone()));
    ctx.c.cancel_dispute(&id2);
    assert_eq!(ctx.c.get_dispute(&id2), None);

    // Estricto: solo quien la abrió.
    let est = setup(Modo::Estricto);
    let eid = super::test_v4::deposit_simple(&est, "retira-estricto", UNIT, DIA);
    firmas(&est, &[&est.arbiter], "assign_freelancer", (&eid, &est.freelancer).into_val(&est.env));
    est.c.assign_freelancer(&eid, &est.freelancer);
    firmas(&est, &[&est.freelancer], "open_dispute", (&eid, &est.freelancer).into_val(&est.env));
    est.c.open_dispute(&eid, &est.freelancer);
    let args: Vec<Val> = (&eid,).into_val(&est.env);
    firmas(&est, &[&est.client], "cancel_dispute", args.clone());
    assert!(est.c.try_cancel_dispute(&eid).is_err());
    firmas(&est, &[&est.freelancer], "cancel_dispute", args);
    est.c.cancel_dispute(&eid);
}

#[test]
fn v7_cancel_milestone_dispute_lo_retira_quien_lo_abrio() {
    let ctx = setup(Modo::Libre);
    let id = proyecto_asignado(&ctx, "retira-h-1");
    assert_eq!(
        ctx.c.try_cancel_milestone_dispute(&id, &0),
        Err(Ok(Error::NoDispute))
    );
    ctx.c.open_milestone_dispute(&id, &0, &ctx.freelancer);
    ctx.c.cancel_milestone_dispute(&id, &0);
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    ctx.c.timeout_refund_milestone(&id, &0);

    let est = setup(Modo::Estricto);
    let eid = proyecto_asignado(&est, "retira-h-estricto");
    firmas(&est, &[&est.client], "open_milestone_dispute", (&eid, 1u32, &est.client).into_val(&est.env));
    est.c.open_milestone_dispute(&eid, &1, &est.client);
    let args: Vec<Val> = (&eid, 1u32).into_val(&est.env);
    firmas(&est, &[&est.freelancer], "cancel_milestone_dispute", args.clone());
    assert!(est.c.try_cancel_milestone_dispute(&eid, &1).is_err());
    firmas(&est, &[&est.client], "cancel_milestone_dispute", args);
    est.c.cancel_milestone_dispute(&eid, &1);
    assert_eq!(est.c.get_milestone_dispute(&eid, &1), None);
}

// ---------------------------------------------------------------------------
// Lote 3: operaciones por lote
// ---------------------------------------------------------------------------

fn tarea(ctx: &Ctx, nombre: &str, monto: i128, plazo: u64, asignar: bool) -> String {
    let id = super::test_v4::deposit_simple(ctx, nombre, monto, plazo);
    if asignar {
        ctx.c.assign_freelancer(&id, &ctx.freelancer);
    }
    id
}

#[test]
fn v7_release_batch_paga_varias_al_programador_registrado() {
    let ctx = setup(Modo::Libre);
    let a = tarea(&ctx, "lote-pago-a", 2 * UNIT, DIA, true);
    let b = tarea(&ctx, "lote-pago-b", 3 * UNIT, DIA, true);
    let hs: Vec<BytesN<32>> = Vec::from_array(&ctx.env, [hash(&ctx.env, 1), hash(&ctx.env, 2)]);
    let ids: Vec<String> = Vec::from_array(&ctx.env, [a.clone(), b.clone()]);
    assert_eq!(ctx.c.release_batch(&ids, &hs, &hs), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    assert_eq!(ctx.c.get_task(&a).status, TaskStatus::Released);
    assert_eq!(ctx.c.get_task(&b).status, TaskStatus::Released);

    // Ya pagadas: el lote completo falla y no se mueve nada.
    assert_eq!(ctx.c.try_release_batch(&ids, &hs, &hs), Err(Ok(Error::NotFunded)));

    // Una sin programador registrado revierte todo el lote.
    let c = tarea(&ctx, "lote-pago-c", UNIT, DIA, true);
    let d = tarea(&ctx, "lote-pago-d", UNIT, DIA, false);
    let ids2: Vec<String> = Vec::from_array(&ctx.env, [c.clone(), d]);
    assert_eq!(ctx.c.try_release_batch(&ids2, &hs, &hs), Err(Ok(Error::WrongFreelancer)));
    assert_eq!(ctx.c.get_task(&c).status, TaskStatus::Funded);

    // Un id repetido no paga dos veces.
    let rep: Vec<String> = Vec::from_array(&ctx.env, [c.clone(), c.clone()]);
    assert_eq!(ctx.c.try_release_batch(&rep, &hs, &hs), Err(Ok(Error::NotFunded)));

    // Tamaños.
    let uno: Vec<String> = Vec::from_array(&ctx.env, [c.clone()]);
    let h1: Vec<BytesN<32>> = Vec::from_array(&ctx.env, [hash(&ctx.env, 1)]);
    assert_eq!(ctx.c.try_release_batch(&uno, &h1, &h1), Err(Ok(Error::TooManyItems)));
    let e = tarea(&ctx, "lote-pago-e", UNIT, DIA, true);
    let dos: Vec<String> = Vec::from_array(&ctx.env, [c, e]);
    assert_eq!(ctx.c.try_release_batch(&dos, &hs, &h1), Err(Ok(Error::LengthMismatch)));
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
}

#[test]
fn v7_release_batch_estricto_solo_el_arbitro_y_no_tras_el_plazo() {
    let est = setup(Modo::Estricto);
    let a = super::test_v4::deposit_simple(&est, "lote-est-a", UNIT, 100);
    let b = super::test_v4::deposit_simple(&est, "lote-est-b", UNIT, DIA);
    for id in [&a, &b] {
        firmas(&est, &[&est.arbiter], "assign_freelancer", (id, &est.freelancer).into_val(&est.env));
        est.c.assign_freelancer(id, &est.freelancer);
    }
    let ids: Vec<String> = Vec::from_array(&est.env, [a, b]);
    let hs: Vec<BytesN<32>> = Vec::from_array(&est.env, [hash(&est.env, 1), hash(&est.env, 2)]);
    let args: Vec<Val> = (&ids, &hs, &hs).into_val(&est.env);
    firmas(&est, &[&est.client], "release_batch", args.clone());
    assert!(est.c.try_release_batch(&ids, &hs, &hs).is_err());
    est.env.ledger().set_timestamp(START_TS + 100);
    firmas(&est, &[&est.arbiter], "release_batch", args);
    assert_eq!(est.c.try_release_batch(&ids, &hs, &hs), Err(Ok(Error::DeadlinePassed)));
}

#[test]
fn v7_refund_batch_reembolsa_solo_las_que_proceden_sin_permisos() {
    let ctx = setup(Modo::Libre);
    let vencida = tarea(&ctx, "lote-ref-a", 2 * UNIT, 100, false);
    let otra = tarea(&ctx, "lote-ref-b", UNIT, 100, false);
    let vigente = tarea(&ctx, "lote-ref-c", UNIT, DIA, false);
    let disputada = tarea(&ctx, "lote-ref-d", UNIT, 100, true);
    ctx.c.open_dispute(&disputada, &ctx.freelancer);
    let pagada = tarea(&ctx, "lote-ref-e", UNIT, 100, true);
    ctx.c.client_release(&pagada, &ctx.freelancer);

    let ids: Vec<String> = Vec::from_array(
        &ctx.env,
        [
            vencida.clone(),
            otra.clone(),
            vigente.clone(),
            disputada.clone(),
            pagada,
            String::from_str(&ctx.env, "no-existe"),
        ],
    );
    assert_eq!(ctx.c.try_refund_batch(&ids), Err(Ok(Error::DeadlineNotReached)));
    ctx.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(ctx.c.refund_batch(&ids), 2);
    assert_eq!(ctx.c.get_task(&vencida).status, TaskStatus::Refunded);
    assert_eq!(ctx.c.get_task(&otra).status, TaskStatus::Refunded);
    assert_eq!(ctx.c.get_task(&vigente).status, TaskStatus::Funded);
    assert_eq!(ctx.c.get_task(&disputada).status, TaskStatus::Funded);
    // Segunda pasada: ya no queda nada que proceda.
    assert_eq!(ctx.c.try_refund_batch(&ids), Err(Ok(Error::DeadlineNotReached)));
    let vacio: Vec<String> = Vec::new(&ctx.env);
    assert_eq!(ctx.c.try_refund_batch(&vacio), Err(Ok(Error::TooManyItems)));
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));

    // Sin ninguna firma (modo estricto): cualquiera lo dispara.
    let est = setup(Modo::Estricto);
    let eid = super::test_v4::deposit_simple(&est, "lote-ref-estricto", UNIT, 100);
    est.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(est.c.refund_batch(&Vec::from_array(&est.env, [eid])), 1);
    assert_eq!(est.token.balance(&est.client), MINT);
}

#[test]
fn v7_get_projects_lee_por_lote() {
    let ctx = setup(Modo::Libre);
    let a = deposit_two_milestones(&ctx, "lote-proy-a");
    let b = proyecto_asignado(&ctx, "lote-proy-b");
    let ids: Vec<String> = Vec::from_array(
        &ctx.env,
        [b.clone(), String::from_str(&ctx.env, "nada"), a.clone()],
    );
    let out = ctx.c.get_projects(&ids);
    assert_eq!(out.len(), 3);
    assert_eq!(out.get(0).unwrap().unwrap().freelancer, Some(ctx.freelancer.clone()));
    assert_eq!(out.get(1).unwrap(), None);
    assert_eq!(out.get(2).unwrap().unwrap().milestones.len(), 2);
    let vacio: Vec<String> = Vec::new(&ctx.env);
    assert_eq!(ctx.c.try_get_projects(&vacio), Err(Ok(Error::TooManyItems)));
}
