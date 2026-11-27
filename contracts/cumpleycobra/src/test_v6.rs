#![cfg(test)]

// Pruebas de v6. Mismo esquema que `test_v4.rs` y `test_v5.rs`: `Modo::Libre`
// usa `mock_all_auths`; `Modo::Estricto` nunca lo usa y cada firma es explícita.

extern crate std;

use super::test_v4::{deposit_simple, hash, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _, MockAuth, MockAuthInvoke},
    Address, IntoVal, Val, Vec,
};

// Varias firmas explícitas para una misma llamada (modo estricto).
fn firmas(ctx: &Ctx, quienes: &[&Address], fn_name: &'static str, args: Vec<Val>) {
    let invoke = MockAuthInvoke {
        contract: &ctx.contract_id,
        fn_name,
        args,
        sub_invokes: &[],
    };
    let auths: std::vec::Vec<MockAuth> = quienes
        .iter()
        .map(|a| MockAuth {
            address: a,
            invoke: &invoke,
        })
        .collect();
    ctx.env.mock_auths(&auths);
}

// Tarea simple ya depositada y con el programador registrado (modo libre).
fn tarea_asignada(ctx: &Ctx, nombre: &str, monto: i128) -> String {
    let id = deposit_simple(ctx, nombre, monto, DIA);
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    id
}

// Tarea depositada y asignada en modo estricto (con la firma del árbitro).
fn tarea_asignada_estricta(ctx: &Ctx, nombre: &str, monto: i128) -> String {
    let id = deposit_simple(ctx, nombre, monto, DIA);
    firmas(ctx, &[&ctx.arbiter], "assign_freelancer", (&id, &ctx.freelancer).into_val(&ctx.env));
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    id
}

// ---------------------------------------------------------------------------
// Lote 1: acuerdos entre las dos partes
// ---------------------------------------------------------------------------

#[test]
fn v6_amend_rules_cambia_el_hash_con_las_dos_firmas() {
    let ctx = setup(Modo::Libre);
    let sin_asignar = deposit_simple(&ctx, "amend-0", UNIT, DIA);
    assert_eq!(
        ctx.c.try_amend_rules(&sin_asignar, &hash(&ctx.env, 9)),
        Err(Ok(Error::WrongFreelancer))
    );

    let id = tarea_asignada(&ctx, "amend-1", UNIT);
    ctx.c.amend_rules(&id, &hash(&ctx.env, 9));
    assert_eq!(ctx.c.get_task(&id).rules_hash, hash(&ctx.env, 9));
    assert_eq!(
        ctx.c.try_amend_rules(&id, &hash(&ctx.env, 9)),
        Err(Ok(Error::NoChange))
    );

    // Estricto: el cliente solo no puede cambiar los criterios.
    let est = setup(Modo::Estricto);
    let eid = tarea_asignada_estricta(&est, "amend-estricto", UNIT);
    let args: Vec<Val> = (&eid, hash(&est.env, 8)).into_val(&est.env);
    firmas(&est, &[&est.client], "amend_rules", args.clone());
    assert!(est.c.try_amend_rules(&eid, &hash(&est.env, 8)).is_err());
    firmas(&est, &[&est.freelancer], "amend_rules", args.clone());
    assert!(est.c.try_amend_rules(&eid, &hash(&est.env, 8)).is_err());
    firmas(&est, &[&est.client, &est.freelancer], "amend_rules", args);
    est.c.amend_rules(&eid, &hash(&est.env, 8));
    assert_eq!(est.c.get_task(&eid).rules_hash, hash(&est.env, 8));
}

#[test]
fn v6_release_partial_paga_una_parte_y_el_resto_sigue_depositado() {
    let ctx = setup(Modo::Libre);
    let (h1, h2) = (hash(&ctx.env, 1), hash(&ctx.env, 2));
    let sin_asignar = deposit_simple(&ctx, "parcial-0", 4 * UNIT, DIA);
    assert_eq!(
        ctx.c.try_release_partial(&sin_asignar, &UNIT, &h1, &h2),
        Err(Ok(Error::WrongFreelancer))
    );

    let id = tarea_asignada(&ctx, "parcial-1", 4 * UNIT);
    assert_eq!(ctx.c.release_partial(&id, &UNIT, &h1, &h2), 3 * UNIT);
    let t = ctx.c.get_task(&id);
    assert_eq!((t.amount, t.status), (3 * UNIT, TaskStatus::Funded));
    assert_eq!(ctx.token.balance(&ctx.freelancer), UNIT);

    // Ni 0, ni negativo, ni todo lo que queda (para eso existe release).
    for malo in [0, -1, 3 * UNIT, 5 * UNIT] {
        assert_eq!(
            ctx.c.try_release_partial(&id, &malo, &h1, &h2),
            Err(Ok(Error::InvalidAmount))
        );
    }
    // El resto se paga con release.
    ctx.c.release(&id, &ctx.freelancer, &h1, &h2);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);
    // En el contrato solo queda la tarea sin asignar (parcial-0).
    assert_eq!(ctx.token.balance(&ctx.contract_id), 4 * UNIT);

    // Después del plazo ya no se paga en partes.
    let tarde = tarea_asignada(&ctx, "parcial-2", 4 * UNIT);
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(
        ctx.c.try_release_partial(&tarde, &UNIT, &h1, &h2),
        Err(Ok(Error::DeadlinePassed))
    );
}

#[test]
fn v6_release_partial_estricto_solo_el_arbitro() {
    let est = setup(Modo::Estricto);
    let id = tarea_asignada_estricta(&est, "parcial-estricto", 4 * UNIT);
    let (h1, h2) = (hash(&est.env, 1), hash(&est.env, 2));
    let args: Vec<Val> = (&id, UNIT, &h1, &h2).into_val(&est.env);
    firmas(&est, &[&est.client], "release_partial", args.clone());
    assert!(est.c.try_release_partial(&id, &UNIT, &h1, &h2).is_err());
    firmas(&est, &[&est.arbiter], "release_partial", args);
    est.c.release_partial(&id, &UNIT, &h1, &h2);
    assert_eq!(est.token.balance(&est.freelancer), UNIT);
}

#[test]
fn v6_mutual_cancel_devuelve_todo_con_las_dos_firmas() {
    let ctx = setup(Modo::Libre);
    let id = tarea_asignada(&ctx, "cancela-1", 3 * UNIT);
    // También después del plazo: es un acuerdo, no un reembolso por tiempo.
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    ctx.c.mutual_cancel(&id);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Refunded);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);
    assert_eq!(ctx.c.try_mutual_cancel(&id), Err(Ok(Error::NotFunded)));

    let est = setup(Modo::Estricto);
    let eid = tarea_asignada_estricta(&est, "cancela-estricto", 3 * UNIT);
    let args: Vec<Val> = (&eid,).into_val(&est.env);
    firmas(&est, &[&est.client], "mutual_cancel", args.clone());
    assert!(est.c.try_mutual_cancel(&eid).is_err());
    firmas(&est, &[&est.client, &est.freelancer], "mutual_cancel", args);
    est.c.mutual_cancel(&eid);
    assert_eq!(est.token.balance(&est.client), MINT);
}

#[test]
fn v6_reassign_freelancer_exige_cliente_programador_actual_y_nuevo() {
    let ctx = setup(Modo::Libre);
    let id = tarea_asignada(&ctx, "reasigna-1", 3 * UNIT);
    assert_eq!(
        ctx.c.try_reassign_freelancer(&id, &ctx.freelancer),
        Err(Ok(Error::NoChange))
    );
    ctx.c.reassign_freelancer(&id, &ctx.third);
    assert_eq!(ctx.c.get_task(&id).freelancer, Some(ctx.third.clone()));
    // Desde ahí, el anterior ya no puede cobrar.
    assert_eq!(
        ctx.c.try_client_release(&id, &ctx.freelancer),
        Err(Ok(Error::WrongFreelancer))
    );
    ctx.c.client_release(&id, &ctx.third);
    assert_eq!(ctx.token.balance(&ctx.third), 7 + 3 * UNIT);

    let est = setup(Modo::Estricto);
    let eid = tarea_asignada_estricta(&est, "reasigna-estricto", 3 * UNIT);
    let args: Vec<Val> = (&eid, &est.third).into_val(&est.env);
    // Faltando cualquiera de las tres firmas, falla.
    for faltan in [
        [&est.client, &est.freelancer],
        [&est.client, &est.third],
        [&est.freelancer, &est.third],
    ] {
        firmas(&est, &faltan, "reassign_freelancer", args.clone());
        assert!(est.c.try_reassign_freelancer(&eid, &est.third).is_err());
    }
    firmas(&est, &[&est.client, &est.freelancer, &est.third], "reassign_freelancer", args);
    est.c.reassign_freelancer(&eid, &est.third);
    assert_eq!(est.c.get_task(&eid).freelancer, Some(est.third.clone()));
}

#[test]
fn v6_transfer_client_cambia_quien_recibe_el_reembolso() {
    let ctx = setup(Modo::Libre);
    let nuevo = Address::generate(&ctx.env);
    let id = deposit_simple(&ctx, "transfiere-1", 3 * UNIT, 100);
    assert_eq!(
        ctx.c.try_transfer_client(&id, &ctx.client),
        Err(Ok(Error::NoChange))
    );
    ctx.c.transfer_client(&id, &nuevo);
    assert_eq!(ctx.c.get_task(&id).client, nuevo);
    ctx.env.ledger().set_timestamp(START_TS + 100);
    ctx.c.timeout_refund(&id);
    assert_eq!(ctx.token.balance(&nuevo), 3 * UNIT);

    // Estricto, con programador registrado: firman los tres.
    let est = setup(Modo::Estricto);
    let empresa = Address::generate(&est.env);
    let eid = tarea_asignada_estricta(&est, "transfiere-estricto", 3 * UNIT);
    let args: Vec<Val> = (&eid, &empresa).into_val(&est.env);
    firmas(&est, &[&est.client, &empresa], "transfer_client", args.clone());
    assert!(est.c.try_transfer_client(&eid, &empresa).is_err());
    firmas(&est, &[&est.client, &est.freelancer], "transfer_client", args.clone());
    assert!(est.c.try_transfer_client(&eid, &empresa).is_err());
    firmas(&est, &[&est.client, &empresa, &est.freelancer], "transfer_client", args);
    est.c.transfer_client(&eid, &empresa);
    assert_eq!(est.c.get_task(&eid).client, empresa);
}
