#![cfg(test)]

// Pruebas de v10: top_up_bond, release_milestone_with_fee y
// transfer_stream_client. `Modo::Libre` usa `mock_all_auths`; las pruebas
// estrictas fijan cada firma con `firmas`.

extern crate std;

use super::test_v4::{deposit_simple, deposit_two_milestones, hash, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _},
    Address, IntoVal, Val, Vec,
};

fn tarea_con_garantia(ctx: &Ctx, nombre: &str) -> String {
    if ctx.modo == Modo::Estricto {
        // La preparación no es lo que se prueba: firmas libres hasta el depósito.
        ctx.env.mock_all_auths();
    }
    ctx.token.transfer(&ctx.client, &ctx.freelancer, &(5 * UNIT));
    let id = deposit_simple(ctx, nombre, 4 * UNIT, DIA);
    if ctx.modo == Modo::Estricto {
        ctx.env.mock_all_auths();
    }
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    ctx.c.post_bond(&id, &UNIT);
    id
}

#[test]
fn v10_top_up_bond_aumenta_la_garantia_y_se_recupera_completa() {
    let ctx = setup(Modo::Libre);
    let sin = deposit_simple(&ctx, "tb-0", UNIT, DIA);
    assert_eq!(ctx.c.try_top_up_bond(&sin, &UNIT), Err(Ok(Error::NotFound)));
    let id = tarea_con_garantia(&ctx, "tb-1");
    assert_eq!(ctx.c.top_up_bond(&id, &(2 * UNIT)), 3 * UNIT);
    assert_eq!(ctx.c.get_bond(&id).unwrap().amount, 3 * UNIT);
    assert_eq!(ctx.c.try_top_up_bond(&id, &0), Err(Ok(Error::InvalidAmount)));
    ctx.c.client_release(&id, &ctx.freelancer);
    // Pagada: ya no se aumenta, y se recupera completa.
    assert_eq!(ctx.c.try_top_up_bond(&id, &UNIT), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.c.reclaim_bond(&id), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT + 4 * UNIT);
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));

    let tarde = tarea_con_garantia(&ctx, "tb-2");
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(ctx.c.try_top_up_bond(&tarde, &UNIT), Err(Ok(Error::DeadlinePassed)));
}

#[test]
fn v10_top_up_bond_estricto_solo_el_programador() {
    let est = setup(Modo::Estricto);
    let id = tarea_con_garantia(&est, "tb-e");
    let args: Vec<Val> = (&id, UNIT).into_val(&est.env);
    firmas(&est, &[&est.client], "top_up_bond", args);
    assert!(est.c.try_top_up_bond(&id, &UNIT).is_err());
}

#[test]
fn v10_release_milestone_with_fee_descuenta_la_comision() {
    let ctx = setup(Modo::Libre);
    let plataforma = Address::generate(&ctx.env);
    let (h1, h2) = (hash(&ctx.env, 1), hash(&ctx.env, 2));
    let id = deposit_two_milestones(&ctx, "hf-1");
    for malo in [0u32, 1001] {
        assert_eq!(
            ctx.c.try_release_milestone_with_fee(&id, &0, &ctx.freelancer, &h1, &h2, &plataforma, &malo),
            Err(Ok(Error::InvalidAmount))
        );
    }
    assert_eq!(
        ctx.c.try_release_milestone_with_fee(&id, &0, &ctx.freelancer, &h1, &h2, &ctx.client, &500),
        Err(Ok(Error::NoChange))
    );
    // Hito 0 = 4 UNIT; 10% = 0.4 para la plataforma.
    assert_eq!(
        ctx.c.release_milestone_with_fee(&id, &0, &ctx.freelancer, &h1, &h2, &plataforma, &1000),
        4 * UNIT - 4 * UNIT / 10
    );
    assert_eq!(ctx.token.balance(&plataforma), 4 * UNIT / 10);
    assert_eq!(ctx.c.get_project(&id).freelancer, Some(ctx.freelancer.clone()));
    // El programador queda fijo: otro no puede cobrar el hito 1.
    assert_eq!(
        ctx.c.try_release_milestone_with_fee(&id, &1, &ctx.third, &h1, &h2, &plataforma, &500),
        Err(Ok(Error::WrongFreelancer))
    );
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    assert_eq!(
        ctx.c.try_release_milestone_with_fee(&id, &1, &ctx.freelancer, &h1, &h2, &plataforma, &500),
        Err(Ok(Error::DeadlinePassed))
    );
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 10 * UNIT);
}

#[test]
fn v10_release_milestone_with_fee_estricto_solo_el_arbitro() {
    let est = setup(Modo::Estricto);
    let id = deposit_two_milestones(&est, "hf-e");
    let plataforma = Address::generate(&est.env);
    let (h1, h2) = (hash(&est.env, 1), hash(&est.env, 2));
    let args: Vec<Val> = (&id, 0u32, &est.freelancer, &h1, &h2, &plataforma, 500u32).into_val(&est.env);
    firmas(&est, &[&est.client], "release_milestone_with_fee", args.clone());
    assert!(est.c.try_release_milestone_with_fee(&id, &0, &est.freelancer, &h1, &h2, &plataforma, &500).is_err());
    firmas(&est, &[&est.arbiter], "release_milestone_with_fee", args);
    est.c.release_milestone_with_fee(&id, &0, &est.freelancer, &h1, &h2, &plataforma, &500);
}

#[test]
fn v10_transfer_stream_client_cambia_quien_recibe_lo_no_liberado() {
    let ctx = setup(Modo::Libre);
    let empresa = Address::generate(&ctx.env);
    let id = String::from_str(&ctx.env, "ts-1");
    ctx.c.deposit_stream(&ctx.client, &id, &ctx.freelancer, &(10 * UNIT), &(10 * DIA));
    assert_eq!(ctx.c.try_transfer_stream_client(&id, &ctx.client), Err(Ok(Error::NoChange)));
    assert_eq!(ctx.c.try_transfer_stream_client(&id, &ctx.freelancer), Err(Ok(Error::NoChange)));
    ctx.c.transfer_stream_client(&id, &empresa);
    assert_eq!(ctx.c.get_stream(&id).client, empresa);
    // Al cancelar, lo no liberado va al cliente nuevo.
    ctx.env.ledger().set_timestamp(START_TS + 4 * DIA);
    ctx.c.cancel_stream(&id);
    assert_eq!(ctx.token.balance(&empresa), 6 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);
    assert_eq!(ctx.c.try_transfer_stream_client(&id, &ctx.third), Err(Ok(Error::NotFunded)));
}

#[test]
fn v10_transfer_stream_client_exige_las_tres_firmas() {
    let est = setup(Modo::Estricto);
    est.env.mock_all_auths();
    let id = String::from_str(&est.env, "ts-e");
    est.c.deposit_stream(&est.client, &id, &est.freelancer, &(10 * UNIT), &(10 * DIA));
    let empresa = Address::generate(&est.env);
    let args: Vec<Val> = (&id, &empresa).into_val(&est.env);
    for faltan in [
        [&est.client, &empresa],
        [&est.client, &est.freelancer],
        [&empresa, &est.freelancer],
    ] {
        firmas(&est, &faltan, "transfer_stream_client", args.clone());
        assert!(est.c.try_transfer_stream_client(&id, &empresa).is_err());
    }
    firmas(&est, &[&est.client, &empresa, &est.freelancer], "transfer_stream_client", args);
    est.c.transfer_stream_client(&id, &empresa);
    assert_eq!(est.c.get_stream(&id).client, empresa);
}
