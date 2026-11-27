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
pub(crate) fn firmas(ctx: &Ctx, quienes: &[&Address], fn_name: &'static str, args: Vec<Val>) {
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

// ---------------------------------------------------------------------------
// Lote 2: propina, TTL, estadísticas y depósito con programador registrado
// ---------------------------------------------------------------------------

#[test]
fn v6_tip_va_del_cliente_al_programador_solo_tras_el_pago() {
    let ctx = setup(Modo::Libre);
    let id = tarea_asignada(&ctx, "propina-1", 2 * UNIT);
    // Antes de pagar no hay propina (para eso existe el bono).
    assert_eq!(ctx.c.try_tip(&id, &UNIT), Err(Ok(Error::NotFunded)));
    ctx.c.client_release(&id, &ctx.freelancer);
    assert_eq!(ctx.c.try_tip(&id, &0), Err(Ok(Error::InvalidAmount)));

    let antes = ctx.c.get_stats();
    ctx.c.tip(&id, &UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 3 * UNIT);
    // La propina no pasa por el contrato: los totales no cambian.
    assert_eq!(ctx.c.get_stats(), antes);
    assert_eq!(
        ctx.c.try_tip(&String::from_str(&ctx.env, "nada"), &UNIT),
        Err(Ok(Error::NotFound))
    );

    // Estricto: solo el cliente de la tarea.
    let est = setup(Modo::Estricto);
    let eid = tarea_asignada_estricta(&est, "propina-estricto", 2 * UNIT);
    firmas(&est, &[&est.client], "client_release", (&eid, &est.freelancer).into_val(&est.env));
    est.c.client_release(&eid, &est.freelancer);
    firmas(&est, &[&est.third], "tip", (&eid, 5i128).into_val(&est.env));
    assert!(est.c.try_tip(&eid, &5).is_err());
}

#[test]
fn v6_bump_ttl_sin_permisos_y_solo_si_existe() {
    let ctx = setup(Modo::Estricto); // sin ninguna firma
    let id = deposit_simple(&ctx, "ttl-1", UNIT, DIA);
    ctx.c.bump_ttl(&id);
    assert_eq!(
        ctx.c.try_bump_ttl(&String::from_str(&ctx.env, "nada")),
        Err(Ok(Error::NotFound))
    );
    // Proyecto por hitos.
    let libre = setup(Modo::Libre);
    let pid = super::test_v4::deposit_two_milestones(&libre, "ttl-proyecto");
    libre.c.bump_ttl(&pid);
}

#[test]
fn v6_get_stats_cuadra_con_el_saldo_real_tras_todas_las_operaciones() {
    let ctx = setup(Modo::Libre);
    let (h1, h2) = (hash(&ctx.env, 1), hash(&ctx.env, 2));
    assert_eq!(ctx.c.get_stats(), Stats { deposited: 0, paid_out: 0, held: 0 });

    let a = tarea_asignada(&ctx, "stats-a", 5 * UNIT);
    ctx.c.top_up_task(&a, &UNIT);
    ctx.c.release_partial(&a, &(2 * UNIT), &h1, &h2);
    let b = deposit_simple(&ctx, "stats-b", 3 * UNIT, DIA);
    ctx.c.client_release_with_bonus(&b, &ctx.third, &UNIT); // el bono no pasa por el contrato
    let p = super::test_v4::deposit_two_milestones(&ctx, "stats-p");
    ctx.c.client_release_milestone(&p, &0, &ctx.freelancer);
    ctx.c.top_up_milestone(&p, &1, &UNIT);

    let st = ctx.c.get_stats();
    // Entró: 5 + 1 + 3 + 10 + 1 = 20. Salió: 2 + 3 + 4 = 9.
    assert_eq!(st, Stats { deposited: 20 * UNIT, paid_out: 9 * UNIT, held: 11 * UNIT });
    assert_eq!(st.held, ctx.token.balance(&ctx.contract_id));

    ctx.c.mutual_cancel(&a);
    ctx.env.ledger().set_timestamp(START_TS + 3 * DIA);
    ctx.c.timeout_refund_milestone(&p, &1);
    let fin = ctx.c.get_stats();
    assert_eq!(fin.held, 0);
    assert_eq!(fin.held, ctx.token.balance(&ctx.contract_id));
    assert_eq!(fin.deposited, fin.paid_out);
}

#[test]
fn v6_deposit_assigned_deposita_y_registra_en_una_sola_transaccion() {
    let ctx = setup(Modo::Libre);
    let id = String::from_str(&ctx.env, "dep-asig-1");
    ctx.c
        .deposit_assigned(&ctx.client, &id, &(2 * UNIT), &DIA, &hash(&ctx.env, 3), &ctx.freelancer);
    let t = ctx.c.get_task(&id);
    assert_eq!(t.freelancer, Some(ctx.freelancer.clone()));
    assert_eq!((t.amount, t.status), (2 * UNIT, TaskStatus::Funded));
    assert_eq!(ctx.token.balance(&ctx.contract_id), 2 * UNIT);
    // Ya registrado: el cliente no puede pagarse a sí mismo.
    assert_eq!(
        ctx.c.try_client_release(&id, &ctx.client),
        Err(Ok(Error::WrongFreelancer))
    );
    // Repetido, o el cliente como su propio programador.
    assert_eq!(
        ctx.c.try_deposit_assigned(&ctx.client, &id, &UNIT, &DIA, &hash(&ctx.env, 3), &ctx.freelancer),
        Err(Ok(Error::AlreadyExists))
    );
    let otro = String::from_str(&ctx.env, "dep-asig-2");
    assert_eq!(
        ctx.c.try_deposit_assigned(&ctx.client, &otro, &UNIT, &DIA, &hash(&ctx.env, 3), &ctx.client),
        Err(Ok(Error::NoChange))
    );
}

#[test]
fn v6_deposit_assigned_estricto_exige_cliente_y_programador() {
    let est = setup(Modo::Estricto);
    let id = String::from_str(&est.env, "dep-asig-estricto");
    let rh = hash(&est.env, 3);
    let args: Vec<Val> = (&est.client, &id, 2 * UNIT, DIA, &rh, &est.freelancer).into_val(&est.env);
    let token_id = est.token.address.clone();
    let transferencia = [MockAuthInvoke {
        contract: &token_id,
        fn_name: "transfer",
        args: (&est.client, &est.contract_id, 2 * UNIT).into_val(&est.env),
        sub_invokes: &[],
    }];
    let del_cliente = MockAuthInvoke {
        contract: &est.contract_id,
        fn_name: "deposit_assigned",
        args: args.clone(),
        sub_invokes: &transferencia,
    };
    let del_programador = MockAuthInvoke {
        contract: &est.contract_id,
        fn_name: "deposit_assigned",
        args,
        sub_invokes: &[],
    };
    // Solo el cliente: falta que el programador acepte.
    est.env.mock_auths(&[MockAuth { address: &est.client, invoke: &del_cliente }]);
    assert!(est.c.try_deposit_assigned(&est.client, &id, &(2 * UNIT), &DIA, &rh, &est.freelancer).is_err());
    est.env.mock_auths(&[
        MockAuth { address: &est.client, invoke: &del_cliente },
        MockAuth { address: &est.freelancer, invoke: &del_programador },
    ]);
    est.c.deposit_assigned(&est.client, &id, &(2 * UNIT), &DIA, &rh, &est.freelancer);
    assert_eq!(est.c.get_task(&id).freelancer, Some(est.freelancer.clone()));
}

// ---------------------------------------------------------------------------
// Lote 3: disputas y pausa de emergencia
// ---------------------------------------------------------------------------

#[test]
fn v6_open_dispute_solo_las_partes_antes_del_plazo_y_una_vez() {
    let ctx = setup(Modo::Libre);
    let sin_asignar = deposit_simple(&ctx, "disputa-0", UNIT, DIA);
    assert_eq!(
        ctx.c.try_open_dispute(&sin_asignar, &ctx.client),
        Err(Ok(Error::WrongFreelancer))
    );
    let id = tarea_asignada(&ctx, "disputa-1", 4 * UNIT);
    assert_eq!(
        ctx.c.try_open_dispute(&id, &ctx.third),
        Err(Ok(Error::NotParty))
    );
    assert_eq!(ctx.c.get_dispute(&id), None);
    ctx.c.open_dispute(&id, &ctx.freelancer);
    assert_eq!(ctx.c.get_dispute(&id), Some(ctx.freelancer.clone()));
    assert_eq!(
        ctx.c.try_open_dispute(&id, &ctx.client),
        Err(Ok(Error::DisputeOpen))
    );
    // Tras el plazo ya no se abre (para eso está el reembolso).
    let tarde = tarea_asignada(&ctx, "disputa-2", UNIT);
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(
        ctx.c.try_open_dispute(&tarde, &ctx.client),
        Err(Ok(Error::DeadlinePassed))
    );

    // Estricto: quien dice abrirla debe firmar.
    let est = setup(Modo::Estricto);
    let eid = tarea_asignada_estricta(&est, "disputa-estricto", UNIT);
    firmas(&est, &[&est.freelancer], "open_dispute", (&eid, &est.client).into_val(&est.env));
    assert!(est.c.try_open_dispute(&eid, &est.client).is_err());
    firmas(&est, &[&est.client], "open_dispute", (&eid, &est.client).into_val(&est.env));
    est.c.open_dispute(&eid, &est.client);
}

#[test]
fn v6_disputa_congela_el_reembolso_maximo_14_dias_tras_el_plazo() {
    let ctx = setup(Modo::Libre);
    let id = tarea_asignada(&ctx, "disputa-congela", 4 * UNIT);
    ctx.c.open_dispute(&id, &ctx.client);
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(ctx.c.try_timeout_refund(&id), Err(Ok(Error::DisputeOpen)));
    ctx.env.ledger().set_timestamp(START_TS + DIA + 14 * DIA - 1);
    assert_eq!(ctx.c.try_timeout_refund(&id), Err(Ok(Error::DisputeOpen)));
    // A los 14 días, si el árbitro no resolvió, el dinero vuelve al cliente.
    ctx.env.ledger().set_timestamp(START_TS + DIA + 14 * DIA);
    ctx.c.timeout_refund(&id);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);
}

#[test]
fn v6_resolve_dispute_reparte_y_cierra() {
    let ctx = setup(Modo::Libre);
    let sin_disputa = tarea_asignada(&ctx, "resuelve-0", UNIT);
    assert_eq!(
        ctx.c.try_resolve_dispute(&sin_disputa, &0),
        Err(Ok(Error::NoDispute))
    );

    // Reparto 3 / 1 después del plazo.
    let id = tarea_asignada(&ctx, "resuelve-1", 4 * UNIT);
    ctx.c.open_dispute(&id, &ctx.freelancer);
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    for malo in [-1, 5 * UNIT] {
        assert_eq!(ctx.c.try_resolve_dispute(&id, &malo), Err(Ok(Error::InvalidAmount)));
    }
    ctx.c.resolve_dispute(&id, &(3 * UNIT));
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Released);
    assert_eq!(ctx.c.get_dispute(&id), None);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT);

    // Todo al cliente: la tarea queda Refunded.
    let id2 = deposit_simple(&ctx, "resuelve-2", 2 * UNIT, DIA);
    ctx.c.assign_freelancer(&id2, &ctx.freelancer);
    ctx.c.open_dispute(&id2, &ctx.client);
    ctx.c.resolve_dispute(&id2, &0);
    assert_eq!(ctx.c.get_task(&id2).status, TaskStatus::Refunded);
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));

    // Estricto: solo el árbitro resuelve.
    let est = setup(Modo::Estricto);
    let eid = tarea_asignada_estricta(&est, "resuelve-estricto", 2 * UNIT);
    firmas(&est, &[&est.client], "open_dispute", (&eid, &est.client).into_val(&est.env));
    est.c.open_dispute(&eid, &est.client);
    let args: Vec<Val> = (&eid, 0i128).into_val(&est.env);
    firmas(&est, &[&est.client], "resolve_dispute", args.clone());
    assert!(est.c.try_resolve_dispute(&eid, &0).is_err());
    firmas(&est, &[&est.arbiter], "resolve_dispute", args);
    est.c.resolve_dispute(&eid, &0);
    assert_eq!(est.token.balance(&est.client), MINT);
}

#[test]
fn v6_pausa_detiene_depositos_pero_nunca_pagos_ni_reembolsos() {
    let ctx = setup(Modo::Libre);
    let (h1, h2) = (hash(&ctx.env, 1), hash(&ctx.env, 2));
    let a = tarea_asignada(&ctx, "pausa-a", 2 * UNIT);
    let b = deposit_simple(&ctx, "pausa-b", UNIT, 100);

    assert_eq!(ctx.c.try_unpause(), Err(Ok(Error::NoChange)));
    ctx.c.pause();
    assert_eq!(ctx.c.try_pause(), Err(Ok(Error::NoChange)));

    // Dinero nuevo: bloqueado.
    let nueva = String::from_str(&ctx.env, "pausa-c");
    assert_eq!(
        ctx.c.try_deposit(&ctx.client, &nueva, &UNIT, &DIA, &h1),
        Err(Ok(Error::Paused))
    );
    assert_eq!(
        ctx.c.try_deposit_assigned(&ctx.client, &nueva, &UNIT, &DIA, &h1, &ctx.freelancer),
        Err(Ok(Error::Paused))
    );
    assert_eq!(ctx.c.try_top_up_task(&a, &UNIT), Err(Ok(Error::Paused)));

    // Dinero que sale: sigue funcionando.
    ctx.c.release(&a, &ctx.freelancer, &h1, &h2);
    ctx.env.ledger().set_timestamp(START_TS + 100);
    ctx.c.timeout_refund(&b);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);

    ctx.c.unpause();
    ctx.c.deposit(&ctx.client, &nueva, &UNIT, &DIA, &h1);
}

#[test]
fn v6_pausa_estricto_solo_el_arbitro() {
    let est = setup(Modo::Estricto);
    let sin_args: Vec<Val> = Vec::new(&est.env);
    firmas(&est, &[&est.client], "pause", sin_args.clone());
    assert!(est.c.try_pause().is_err());
    firmas(&est, &[&est.arbiter], "pause", sin_args.clone());
    est.c.pause();
    firmas(&est, &[&est.third], "unpause", sin_args.clone());
    assert!(est.c.try_unpause().is_err());
    firmas(&est, &[&est.arbiter], "unpause", sin_args);
    est.c.unpause();
}
