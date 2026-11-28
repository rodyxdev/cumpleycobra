#![cfg(test)]

// Pruebas de v9: top_up_stream, reassign_stream, slash_bond_partial y
// release_with_fee. Mismo esquema que las versiones anteriores: `Modo::Libre`
// usa `mock_all_auths`; `Modo::Estricto` nunca lo usa.

extern crate std;

use super::test_v4::{deposit_simple, hash, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _},
    Address, IntoVal, Val, Vec,
};

fn sid(ctx: &Ctx, s: &str) -> String {
    String::from_str(&ctx.env, s)
}

// Pago por tiempo de 10 UNIT durante 10 días (1 UNIT por día).
fn stream(ctx: &Ctx, nombre: &str) -> String {
    let id = sid(ctx, nombre);
    ctx.c
        .deposit_stream(&ctx.client, &id, &ctx.freelancer, &(10 * UNIT), &(10 * DIA));
    id
}

// ---------------------------------------------------------------------------
// top_up_stream
// ---------------------------------------------------------------------------

#[test]
fn v9_top_up_stream_conserva_la_tarifa_y_recorre_el_final() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "s-recarga");
    ctx.env.ledger().set_timestamp(START_TS + 4 * DIA);
    // 5 UNIT más a 1 UNIT por día: el final se recorre 5 días.
    assert_eq!(ctx.c.top_up_stream(&id, &(5 * UNIT)), START_TS + 15 * DIA);
    let s = ctx.c.get_stream(&id);
    assert_eq!((s.amount, s.end), (15 * UNIT, START_TS + 15 * DIA));
    // Lo liberado hasta ahora no cambió (4 días = 4 UNIT).
    assert_eq!(ctx.c.withdraw_stream(&id), 4 * UNIT);
    // Al final nuevo se libera todo, incluida la recarga.
    ctx.env.ledger().set_timestamp(START_TS + 15 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&id), 11 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    // Terminado: ya no se recarga.
    assert_eq!(ctx.c.try_top_up_stream(&id, &UNIT), Err(Ok(Error::NotFunded)));
}

#[test]
fn v9_top_up_stream_valida_monto_tope_y_firma() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "s-recarga-v");
    assert_eq!(ctx.c.try_top_up_stream(&id, &0), Err(Ok(Error::InvalidAmount)));
    // 30 UNIT más serían 30 días extra: rebasa los 28 días desde ahora.
    assert_eq!(ctx.c.try_top_up_stream(&id, &(30 * UNIT)), Err(Ok(Error::InvalidDeadline)));
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    ctx.c.cancel_stream(&id);
    assert_eq!(ctx.c.try_top_up_stream(&id, &UNIT), Err(Ok(Error::NotFunded)));

    // Estricto: el programador no puede recargar por el cliente.
    let est = setup(Modo::Estricto);
    let eid = sid(&est, "s-recarga-e");
    est.env.mock_all_auths();
    est.c
        .deposit_stream(&est.client, &eid, &est.freelancer, &(10 * UNIT), &(10 * DIA));
    firmas(&est, &[&est.freelancer], "top_up_stream", (&eid, UNIT).into_val(&est.env));
    assert!(est.c.try_top_up_stream(&eid, &UNIT).is_err());
}

// ---------------------------------------------------------------------------
// reassign_stream
// ---------------------------------------------------------------------------

#[test]
fn v9_reassign_stream_paga_lo_ganado_y_el_resto_sigue_al_nuevo() {
    let ctx = setup(Modo::Libre);
    let nuevo = Address::generate(&ctx.env);
    let id = stream(&ctx, "s-reasigna");
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    ctx.c.withdraw_stream(&id); // 2 UNIT
    ctx.env.ledger().set_timestamp(START_TS + 5 * DIA);
    // El actual cobra los 3 UNIT ganados y no retirados.
    assert_eq!(ctx.c.reassign_stream(&id, &nuevo), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    let s = ctx.c.get_stream(&id);
    assert_eq!((s.freelancer.clone(), s.amount, s.withdrawn, s.start), (nuevo.clone(), 5 * UNIT, 0, START_TS + 5 * DIA));
    // Los 5 UNIT restantes fluyen al nuevo en los 5 días que quedan.
    ctx.env.ledger().set_timestamp(START_TS + 10 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&id), 5 * UNIT);
    assert_eq!(ctx.token.balance(&nuevo), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 10 * UNIT);
}

#[test]
fn v9_reassign_stream_valida_y_exige_las_tres_firmas() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "s-reasigna-v");
    assert_eq!(ctx.c.try_reassign_stream(&id, &ctx.freelancer), Err(Ok(Error::NoChange)));
    assert_eq!(ctx.c.try_reassign_stream(&id, &ctx.client), Err(Ok(Error::NoChange)));
    ctx.env.ledger().set_timestamp(START_TS + 10 * DIA);
    assert_eq!(ctx.c.try_reassign_stream(&id, &ctx.third), Err(Ok(Error::NotFunded)));

    let est = setup(Modo::Estricto);
    let eid = sid(&est, "s-reasigna-e");
    est.env.mock_all_auths();
    est.c
        .deposit_stream(&est.client, &eid, &est.freelancer, &(10 * UNIT), &(10 * DIA));
    est.env.ledger().set_timestamp(START_TS + DIA);
    let args: Vec<Val> = (&eid, &est.third).into_val(&est.env);
    for faltan in [
        [&est.client, &est.freelancer],
        [&est.client, &est.third],
        [&est.freelancer, &est.third],
    ] {
        firmas(&est, &faltan, "reassign_stream", args.clone());
        assert!(est.c.try_reassign_stream(&eid, &est.third).is_err());
    }
    firmas(&est, &[&est.client, &est.freelancer, &est.third], "reassign_stream", args);
    assert_eq!(est.c.reassign_stream(&eid, &est.third), UNIT);
}

// ---------------------------------------------------------------------------
// slash_bond_partial
// ---------------------------------------------------------------------------

fn tarea_con_garantia(ctx: &Ctx, nombre: &str) -> String {
    ctx.token.transfer(&ctx.client, &ctx.freelancer, &(3 * UNIT));
    let id = deposit_simple(ctx, nombre, 4 * UNIT, 100);
    if ctx.modo == Modo::Estricto {
        // deposit_simple deja firmas explícitas; el resto de la preparación no es lo que se prueba.
        ctx.env.mock_all_auths();
    }
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    ctx.c.post_bond(&id, &(2 * UNIT));
    id
}

#[test]
fn v9_slash_bond_partial_reparte_la_garantia() {
    let ctx = setup(Modo::Libre);
    let id = tarea_con_garantia(&ctx, "g-parcial");
    // Con la tarea abierta no se reparte.
    assert_eq!(ctx.c.try_slash_bond_partial(&id, &UNIT), Err(Ok(Error::NotFunded)));
    ctx.env.ledger().set_timestamp(START_TS + 100);
    ctx.c.timeout_refund(&id);
    for malo in [0, -1, 2 * UNIT, 3 * UNIT] {
        assert_eq!(ctx.c.try_slash_bond_partial(&id, &malo), Err(Ok(Error::InvalidAmount)));
    }
    ctx.c.slash_bond_partial(&id, &(UNIT / 2));
    // Cliente: MINT − 3 (fondeo) − 4 (depósito) + 4 (reembolso) + 0.5 (garantía).
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 3 * UNIT + UNIT / 2);
    // Programador: 3 − 2 (garantía) + 1.5 (lo que le vuelve).
    assert_eq!(ctx.token.balance(&ctx.freelancer), UNIT + 3 * UNIT / 2);
    assert_eq!(ctx.c.get_bond(&id), None);
    assert_eq!(ctx.c.get_stats().held, 0);

    // Estricto: solo el árbitro.
    let est = setup(Modo::Estricto);
    est.env.mock_all_auths();
    let eid = tarea_con_garantia(&est, "g-parcial-e");
    est.env.ledger().set_timestamp(START_TS + 100);
    est.c.timeout_refund(&eid);
    let args: Vec<Val> = (&eid, UNIT).into_val(&est.env);
    firmas(&est, &[&est.client], "slash_bond_partial", args.clone());
    assert!(est.c.try_slash_bond_partial(&eid, &UNIT).is_err());
    firmas(&est, &[&est.arbiter], "slash_bond_partial", args);
    est.c.slash_bond_partial(&eid, &UNIT);
}

// ---------------------------------------------------------------------------
// release_with_fee
// ---------------------------------------------------------------------------

#[test]
fn v9_release_with_fee_descuenta_la_comision_hasta_10_por_ciento() {
    let ctx = setup(Modo::Libre);
    let plataforma = Address::generate(&ctx.env);
    let (h1, h2) = (hash(&ctx.env, 1), hash(&ctx.env, 2));
    let id = deposit_simple(&ctx, "fee-1", 10 * UNIT, DIA);
    for malo in [0u32, 1001] {
        assert_eq!(
            ctx.c.try_release_with_fee(&id, &ctx.freelancer, &h1, &h2, &plataforma, &malo),
            Err(Ok(Error::InvalidAmount))
        );
    }
    assert_eq!(
        ctx.c.try_release_with_fee(&id, &ctx.freelancer, &h1, &h2, &ctx.freelancer, &500),
        Err(Ok(Error::NoChange))
    );
    // 5% de 10 UNIT = 0.5 UNIT para la plataforma.
    assert_eq!(ctx.c.release_with_fee(&id, &ctx.freelancer, &h1, &h2, &plataforma, &500), 10 * UNIT - UNIT / 2);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 10 * UNIT - UNIT / 2);
    assert_eq!(ctx.token.balance(&plataforma), UNIT / 2);
    assert_eq!(ctx.c.get_task(&id).status, TaskStatus::Released);
    assert_eq!(
        ctx.c.try_release_with_fee(&id, &ctx.freelancer, &h1, &h2, &plataforma, &500),
        Err(Ok(Error::NotFunded))
    );

    // Con programador registrado, solo a él; y nunca tras el plazo.
    let otra = deposit_simple(&ctx, "fee-2", UNIT, 100);
    ctx.c.assign_freelancer(&otra, &ctx.freelancer);
    assert_eq!(
        ctx.c.try_release_with_fee(&otra, &ctx.third, &h1, &h2, &plataforma, &500),
        Err(Ok(Error::WrongFreelancer))
    );
    ctx.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(
        ctx.c.try_release_with_fee(&otra, &ctx.freelancer, &h1, &h2, &plataforma, &500),
        Err(Ok(Error::DeadlinePassed))
    );
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
}

#[test]
fn v9_release_with_fee_estricto_solo_el_arbitro() {
    let est = setup(Modo::Estricto);
    est.env.mock_all_auths();
    let plataforma = Address::generate(&est.env);
    let id = deposit_simple(&est, "fee-e", UNIT, DIA);
    let (h1, h2) = (hash(&est.env, 1), hash(&est.env, 2));
    let args: Vec<Val> = (&id, &est.freelancer, &h1, &h2, &plataforma, 1000u32).into_val(&est.env);
    firmas(&est, &[&est.client], "release_with_fee", args.clone());
    assert!(est.c.try_release_with_fee(&id, &est.freelancer, &h1, &h2, &plataforma, &1000).is_err());
    firmas(&est, &[&est.arbiter], "release_with_fee", args);
    est.c.release_with_fee(&id, &est.freelancer, &h1, &h2, &plataforma, &1000);
    assert_eq!(est.token.balance(&plataforma), UNIT / 10);
}
