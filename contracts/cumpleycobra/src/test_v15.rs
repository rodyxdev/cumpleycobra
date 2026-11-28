#![cfg(test)]

// Pruebas de v15: operaciones por lote. `Modo::Libre` usa `mock_all_auths`.

extern crate std;

use super::test_v4::{deposit_simple, deposit_two_milestones, setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::*;
use soroban_sdk::{testutils::Ledger as _, Vec};

fn cuadra(ctx: &Ctx) {
    assert_eq!(ctx.c.get_stats().held, ctx.token.balance(&ctx.contract_id));
}

fn dos(ctx: &Ctx, a: &str, b: &str) -> Vec<String> {
    Vec::from_array(&ctx.env, [deposit_simple(ctx, a, 2 * UNIT, DIA), deposit_simple(ctx, b, 3 * UNIT, DIA)])
}

#[test]
fn v15_client_release_batch() {
    let ctx = setup(Modo::Libre);
    let ids = dos(&ctx, "crb-a", "crb-b");
    let fs: Vec<Address> = Vec::from_array(&ctx.env, [ctx.freelancer.clone(), ctx.freelancer.clone()]);
    let uno: Vec<Address> = Vec::from_array(&ctx.env, [ctx.freelancer.clone()]);
    assert_eq!(ctx.c.try_client_release_batch(&ctx.client, &ids, &uno), Err(Ok(Error::LengthMismatch)));
    assert_eq!(ctx.c.try_client_release_batch(&ctx.third, &ids, &fs), Err(Ok(Error::NotParty)));
    assert_eq!(ctx.c.client_release_batch(&ctx.client, &ids, &fs), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    assert_eq!(ctx.c.try_client_release_batch(&ctx.client, &ids, &fs), Err(Ok(Error::NotFunded)));
    cuadra(&ctx);
}

#[test]
fn v15_client_release_milestones_batch() {
    let ctx = setup(Modo::Libre);
    let p = deposit_two_milestones(&ctx, "crmb");
    let idx: Vec<u32> = Vec::from_array(&ctx.env, [0u32, 1u32]);
    let rep: Vec<u32> = Vec::from_array(&ctx.env, [1u32, 1u32]);
    assert_eq!(ctx.c.try_client_release_milestones_batch(&p, &rep, &ctx.freelancer), Err(Ok(Error::NotFunded)));
    ctx.env.ledger().set_timestamp(START_TS + 5 * DIA);
    assert_eq!(ctx.c.client_release_milestones_batch(&p, &idx, &ctx.freelancer), 10 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 10 * UNIT);
    cuadra(&ctx);
}

#[test]
fn v15_extend_y_top_up_por_lote() {
    let ctx = setup(Modo::Libre);
    let ids = dos(&ctx, "et-a", "et-b");
    assert_eq!(ctx.c.extend_deadlines_batch(&ctx.client, &ids, &DIA), 2);
    assert_eq!(ctx.c.get_task(&ids.get(0).unwrap()).deadline, START_TS + 2 * DIA);
    assert_eq!(ctx.c.try_extend_deadlines_batch(&ctx.client, &ids, &(30 * DIA)), Err(Ok(Error::InvalidDeadline)));
    let ams: Vec<i128> = Vec::from_array(&ctx.env, [UNIT, 2 * UNIT]);
    assert_eq!(ctx.c.top_up_tasks_batch(&ctx.client, &ids, &ams), 3 * UNIT);
    assert_eq!(ctx.c.get_task(&ids.get(1).unwrap()).amount, 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 8 * UNIT);
    cuadra(&ctx);
}

#[test]
fn v15_reclaim_bonds_batch() {
    let ctx = setup(Modo::Libre);
    ctx.token.transfer(&ctx.client, &ctx.freelancer, &(3 * UNIT));
    let ids = dos(&ctx, "rb-a", "rb-b");
    for id in ids.iter() {
        ctx.c.assign_freelancer(&id, &ctx.freelancer);
        ctx.c.post_bond(&id, &UNIT);
    }
    assert_eq!(ctx.c.try_reclaim_bonds_batch(&ctx.freelancer, &ids), Err(Ok(Error::NotFunded)));
    for id in ids.iter() {
        ctx.c.client_release(&id, &ctx.freelancer);
    }
    assert_eq!(ctx.c.reclaim_bonds_batch(&ctx.freelancer, &ids), 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT + 5 * UNIT);
    cuadra(&ctx);
}

#[test]
fn v15_cancel_unassigned_tasks_batch() {
    let ctx = setup(Modo::Libre);
    let ids = dos(&ctx, "cu-a", "cu-b");
    assert_eq!(ctx.c.cancel_unassigned_tasks_batch(&ctx.client, &ids), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT);
    let otros = dos(&ctx, "cu-c", "cu-d");
    ctx.c.assign_freelancer(&otros.get(1).unwrap(), &ctx.freelancer);
    assert_eq!(ctx.c.try_cancel_unassigned_tasks_batch(&ctx.client, &otros), Err(Ok(Error::AlreadyAssigned)));
    cuadra(&ctx);
}
