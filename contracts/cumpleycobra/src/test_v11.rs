#![cfg(test)]

// Pruebas de v11: acuerdos y disputa sobre pagos por tiempo, lotes y propina
// de proyecto. `Modo::Libre` usa `mock_all_auths`; las estrictas fijan firmas.

extern crate std;

use super::test_v4::{deposit_two_milestones, hash, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _},
    Address, IntoVal, Val, Vec,
};

fn sid(ctx: &Ctx, s: &str) -> String {
    String::from_str(&ctx.env, s)
}

// 10 UNIT en 10 días (1 UNIT por día).
fn stream(ctx: &Ctx, nombre: &str) -> String {
    let id = sid(ctx, nombre);
    if ctx.modo == Modo::Estricto {
        ctx.env.mock_all_auths();
    }
    ctx.c.deposit_stream(&ctx.client, &id, &ctx.freelancer, &(10 * UNIT), &(10 * DIA));
    id
}

fn cuadra(ctx: &Ctx) {
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
}

#[test]
fn v11_extend_stream_paga_lo_ganado_y_reparte_el_resto_en_mas_tiempo() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "ext");
    ctx.env.ledger().set_timestamp(START_TS + 4 * DIA);
    // Cobra 4 ganados; los 6 restantes se liberan en 12 días (hasta el día 16).
    assert_eq!(ctx.c.extend_stream(&id, &(6 * DIA)), START_TS + 16 * DIA);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);
    ctx.env.ledger().set_timestamp(START_TS + 10 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&id), 3 * UNIT);
    ctx.env.ledger().set_timestamp(START_TS + 16 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&id), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 10 * UNIT);
    assert_eq!(ctx.c.try_extend_stream(&id, &DIA), Err(Ok(Error::NotFunded)));
    cuadra(&ctx);
    let otro = stream(&ctx, "ext-2");
    assert_eq!(ctx.c.try_extend_stream(&otro, &0), Err(Ok(Error::InvalidDeadline)));
    assert_eq!(ctx.c.try_extend_stream(&otro, &(30 * DIA)), Err(Ok(Error::InvalidDeadline)));
}

#[test]
fn v11_reduce_stream_devuelve_parte_de_lo_pendiente() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "red");
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    for malo in [0, 8 * UNIT, 9 * UNIT] {
        assert_eq!(ctx.c.try_reduce_stream(&id, &malo), Err(Ok(Error::InvalidAmount)));
    }
    // Cobra 2; de los 8 pendientes, 4 vuelven al cliente y 4 siguen fluyendo.
    assert_eq!(ctx.c.reduce_stream(&id, &(4 * UNIT)), 4 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 10 * UNIT + 4 * UNIT);
    ctx.env.ledger().set_timestamp(START_TS + 10 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&id), 4 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    cuadra(&ctx);
}

#[test]
fn v11_mutual_split_stream_cierra_con_reparto() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "split");
    ctx.env.ledger().set_timestamp(START_TS + 3 * DIA);
    assert_eq!(ctx.c.try_mutual_split_stream(&id, &(7 * UNIT)), Err(Ok(Error::InvalidAmount)));
    // 3 ganados + 2 de lo pendiente al programador; 5 al cliente.
    ctx.c.mutual_split_stream(&id, &(2 * UNIT));
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 5 * UNIT);
    assert_eq!(ctx.c.get_stream(&id).status, StreamStatus::Canceled);
    assert_eq!(ctx.c.try_withdraw_stream(&id), Err(Ok(Error::NothingToWithdraw)));
    cuadra(&ctx);
}

#[test]
fn v11_acuerdos_de_stream_estricto_exigen_las_dos_firmas() {
    let est = setup(Modo::Estricto);
    let id = stream(&est, "est");
    est.env.ledger().set_timestamp(START_TS + DIA);
    let args: Vec<Val> = (&id, DIA).into_val(&est.env);
    firmas(&est, &[&est.client], "extend_stream", args.clone());
    assert!(est.c.try_extend_stream(&id, &DIA).is_err());
    let args_r: Vec<Val> = (&id, UNIT).into_val(&est.env);
    firmas(&est, &[&est.freelancer], "reduce_stream", args_r);
    assert!(est.c.try_reduce_stream(&id, &UNIT).is_err());
    firmas(&est, &[&est.client], "mutual_split_stream", (&id, UNIT).into_val(&est.env));
    assert!(est.c.try_mutual_split_stream(&id, &UNIT).is_err());
    firmas(&est, &[&est.client, &est.freelancer], "extend_stream", args);
    est.c.extend_stream(&id, &DIA);
}

#[test]
fn v11_tip_stream_solo_cuando_ya_gano_algo() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "tip");
    assert_eq!(ctx.c.try_tip_stream(&id, &UNIT), Err(Ok(Error::NothingToWithdraw)));
    ctx.env.ledger().set_timestamp(START_TS + DIA);
    assert_eq!(ctx.c.try_tip_stream(&id, &0), Err(Ok(Error::InvalidAmount)));
    let antes = ctx.c.get_stats();
    ctx.c.tip_stream(&id, &UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), UNIT);
    assert_eq!(ctx.c.get_stats(), antes); // no pasa por el contrato
}

#[test]
fn v11_disputa_de_stream_bloquea_la_cancelacion_y_el_arbitro_reparte() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "disp");
    assert_eq!(ctx.c.try_open_stream_dispute(&id, &ctx.third), Err(Ok(Error::NotParty)));
    assert_eq!(ctx.c.try_resolve_stream_dispute(&id, &0), Err(Ok(Error::NoDispute)));
    ctx.c.open_stream_dispute(&id, &ctx.freelancer);
    assert_eq!(ctx.c.try_open_stream_dispute(&id, &ctx.client), Err(Ok(Error::DisputeOpen)));
    ctx.env.ledger().set_timestamp(START_TS + 4 * DIA);
    assert_eq!(ctx.c.try_cancel_stream(&id), Err(Ok(Error::DisputeOpen)));
    // 4 ganados + 3 de lo pendiente al programador; 3 al cliente.
    ctx.c.resolve_stream_dispute(&id, &(3 * UNIT));
    assert_eq!(ctx.token.balance(&ctx.freelancer), 7 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 7 * UNIT);
    assert_eq!(ctx.c.get_stream(&id).status, StreamStatus::Canceled);
    cuadra(&ctx);

    let est = setup(Modo::Estricto);
    let eid = stream(&est, "disp-e");
    est.c.open_stream_dispute(&eid, &est.client);
    firmas(&est, &[&est.client], "resolve_stream_dispute", (&eid, 0i128).into_val(&est.env));
    assert!(est.c.try_resolve_stream_dispute(&eid, &0).is_err());
}

#[test]
fn v11_batch_deposit_streams_y_cancel_stream_batch() {
    let ctx = setup(Modo::Libre);
    let a = sid(&ctx, "lote-a");
    let b = sid(&ctx, "lote-b");
    let ids: Vec<String> = Vec::from_array(&ctx.env, [a.clone(), b.clone()]);
    let fs: Vec<Address> = Vec::from_array(&ctx.env, [ctx.freelancer.clone(), ctx.third.clone()]);
    let ams: Vec<i128> = Vec::from_array(&ctx.env, [10 * UNIT, 5 * UNIT]);
    let durs: Vec<u64> = Vec::from_array(&ctx.env, [10 * DIA, 5 * DIA]);
    assert_eq!(ctx.c.batch_deposit_streams(&ctx.client, &ids, &fs, &ams, &durs), 15 * UNIT);
    assert_eq!(ctx.c.try_batch_deposit_streams(&ctx.client, &ids, &fs, &ams, &durs), Err(Ok(Error::AlreadyExists)));
    let corto: Vec<u64> = Vec::from_array(&ctx.env, [DIA]);
    let otros: Vec<String> = Vec::from_array(&ctx.env, [sid(&ctx, "x"), sid(&ctx, "y")]);
    assert_eq!(ctx.c.try_batch_deposit_streams(&ctx.client, &otros, &fs, &ams, &corto), Err(Ok(Error::LengthMismatch)));

    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    let todos: Vec<String> = Vec::from_array(&ctx.env, [a, b, sid(&ctx, "no-existe")]);
    assert_eq!(ctx.c.cancel_stream_batch(&ctx.client, &todos), 2);
    // a: 2 ganados de 10; b: 2 ganados de 5.
    assert_eq!(ctx.token.balance(&ctx.freelancer), 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.third), 7 + 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 4 * UNIT);
    assert_eq!(ctx.c.try_cancel_stream_batch(&ctx.client, &todos), Err(Ok(Error::NotFunded)));
    cuadra(&ctx);
}

#[test]
fn v11_release_milestones_batch_y_tip_project() {
    let ctx = setup(Modo::Libre);
    let plataforma = Address::generate(&ctx.env);
    let id = deposit_two_milestones(&ctx, "hb");
    assert_eq!(ctx.c.try_tip_project(&id, &UNIT), Err(Ok(Error::WrongFreelancer)));
    let idx: Vec<u32> = Vec::from_array(&ctx.env, [0u32, 1u32]);
    let hs: Vec<BytesN<32>> = Vec::from_array(&ctx.env, [hash(&ctx.env, 1), hash(&ctx.env, 2)]);
    let rep: Vec<u32> = Vec::from_array(&ctx.env, [0u32, 0u32]);
    assert_eq!(ctx.c.try_release_milestones_batch(&id, &rep, &ctx.freelancer, &hs, &hs), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.c.release_milestones_batch(&id, &idx, &ctx.freelancer, &hs, &hs), 10 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 10 * UNIT);
    cuadra(&ctx);
    ctx.c.tip_project(&id, &UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 11 * UNIT);
    assert_eq!(ctx.c.try_tip_project(&id, &0), Err(Ok(Error::InvalidAmount)));
    let _ = plataforma;

    // Vencido: no se paga en lote.
    let id2 = deposit_two_milestones(&ctx, "hb2");
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    assert_eq!(ctx.c.try_release_milestones_batch(&id2, &idx, &ctx.freelancer, &hs, &hs), Err(Ok(Error::DeadlinePassed)));
}
