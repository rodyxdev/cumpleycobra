#![cfg(test)]

// Pruebas de la edición ligera de mainnet: las cinco funciones de /mainnet,
// la pausa y las firmas (sin mock_all_auths en la prueba estricta).

extern crate std;

use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger as _, MockAuth, MockAuthInvoke},
    token::{Client as TokenClient, StellarAssetClient},
    Address, BytesN, Env, IntoVal, String,
};

const UNIT: i128 = 10_000_000;
const START: u64 = 1_000_000;

struct Ctx {
    env: Env,
    client: Address,
    freelancer: Address,
    token: TokenClient<'static>,
    id: Address,
    c: CumpleYCobraMainnetClient<'static>,
}

fn setup() -> Ctx {
    let env = Env::default();
    env.mock_all_auths();
    env.ledger().set_timestamp(START);
    let arbiter = Address::generate(&env);
    let client = Address::generate(&env);
    let freelancer = Address::generate(&env);
    let sac = env.register_stellar_asset_contract_v2(Address::generate(&env));
    StellarAssetClient::new(&env, &sac.address()).mint(&client, &(10 * UNIT));
    let id = env.register(CumpleYCobraMainnet, ());
    let c = CumpleYCobraMainnetClient::new(&env, &id);
    c.initialize(&arbiter, &sac.address());
    let token = TokenClient::new(&env, &sac.address());
    Ctx { env, client, freelancer, token, id, c }
}

fn tid(ctx: &Ctx, s: &str) -> String {
    String::from_str(&ctx.env, s)
}

fn h(ctx: &Ctx) -> BytesN<32> {
    BytesN::from_array(&ctx.env, &[7; 32])
}

#[test]
fn deposito_recarga_prorroga_y_pago_manual() {
    let ctx = setup();
    let t = tid(&ctx, "t1");
    ctx.c.deposit(&ctx.client, &t, &(2 * UNIT), &600, &h(&ctx));
    assert_eq!(ctx.c.top_up_task(&t, &UNIT), 3 * UNIT);
    assert_eq!(ctx.c.extend_deadline(&t, &300), START + 900);
    ctx.c.client_release(&t, &ctx.freelancer);
    let task = ctx.c.get_task(&t);
    assert_eq!((task.status, task.amount), (TaskStatus::Released, 3 * UNIT));
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.id), 0);
    // Ya pagada: nada más se mueve.
    assert_eq!(ctx.c.try_client_release(&t, &ctx.freelancer), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.c.try_timeout_refund(&t), Err(Ok(Error::NotFunded)));
}

#[test]
fn reembolso_solo_tras_el_plazo_y_al_cliente() {
    let ctx = setup();
    let t = tid(&ctx, "t2");
    ctx.c.deposit(&ctx.client, &t, &UNIT, &60, &h(&ctx));
    assert_eq!(ctx.c.try_timeout_refund(&t), Err(Ok(Error::DeadlineNotReached)));
    ctx.env.ledger().set_timestamp(START + 60);
    assert_eq!(ctx.c.try_top_up_task(&t, &UNIT), Err(Ok(Error::DeadlinePassed)));
    ctx.c.timeout_refund(&t);
    assert_eq!(ctx.token.balance(&ctx.client), 10 * UNIT);
    assert_eq!(ctx.c.get_task(&t).status, TaskStatus::Refunded);
}

#[test]
fn validaciones() {
    let ctx = setup();
    let t = tid(&ctx, "t3");
    assert_eq!(ctx.c.try_deposit(&ctx.client, &t, &0, &60, &h(&ctx)), Err(Ok(Error::InvalidAmount)));
    assert_eq!(ctx.c.try_deposit(&ctx.client, &t, &UNIT, &0, &h(&ctx)), Err(Ok(Error::InvalidDeadline)));
    ctx.c.deposit(&ctx.client, &t, &UNIT, &60, &h(&ctx));
    assert_eq!(ctx.c.try_deposit(&ctx.client, &t, &UNIT, &60, &h(&ctx)), Err(Ok(Error::AlreadyExists)));
    assert_eq!(ctx.c.try_extend_deadline(&t, &0), Err(Ok(Error::InvalidDeadline)));
    assert_eq!(ctx.c.try_extend_deadline(&t, &(29 * 24 * 3600)), Err(Ok(Error::InvalidDeadline)));
    assert_eq!(ctx.c.try_top_up_task(&t, &0), Err(Ok(Error::InvalidAmount)));
    assert_eq!(ctx.c.try_get_task(&tid(&ctx, "nada")), Err(Ok(Error::NotFound)));
}

#[test]
fn pausa_detiene_depositos_pero_no_pagos_ni_reembolsos() {
    let ctx = setup();
    let t = tid(&ctx, "t4");
    ctx.c.deposit(&ctx.client, &t, &UNIT, &60, &h(&ctx));
    ctx.c.pause();
    assert_eq!(ctx.c.try_pause(), Err(Ok(Error::NoChange)));
    assert_eq!(ctx.c.try_deposit(&ctx.client, &tid(&ctx, "t5"), &UNIT, &60, &h(&ctx)), Err(Ok(Error::Paused)));
    assert_eq!(ctx.c.try_top_up_task(&t, &UNIT), Err(Ok(Error::Paused)));
    ctx.env.ledger().set_timestamp(START + 60);
    ctx.c.timeout_refund(&t);
    assert_eq!(ctx.token.balance(&ctx.client), 10 * UNIT);
    ctx.c.unpause();
}

#[test]
fn estricto_solo_el_cliente_paga_y_nadie_reinicializa() {
    let ctx = setup();
    let t = tid(&ctx, "t6");
    ctx.c.deposit(&ctx.client, &t, &UNIT, &600, &h(&ctx));
    // Sin mock_all_auths: el programador no puede pagarse a sí mismo.
    ctx.env.mock_auths(&[MockAuth {
        address: &ctx.freelancer,
        invoke: &MockAuthInvoke {
            contract: &ctx.id,
            fn_name: "client_release",
            args: (&t, &ctx.freelancer).into_val(&ctx.env),
            sub_invokes: &[],
        },
    }]);
    assert!(ctx.c.try_client_release(&t, &ctx.freelancer).is_err());
    assert_eq!(ctx.c.get_task(&t).status, TaskStatus::Funded);
    ctx.env.mock_all_auths();
    let otro = Address::generate(&ctx.env);
    assert_eq!(ctx.c.try_initialize(&otro, &otro), Err(Ok(Error::AlreadyInitialized)));
}
